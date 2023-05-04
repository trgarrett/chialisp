import asyncio
import os
import sys

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.default_constants import DEFAULT_CONSTANTS
AGG_SIG_ME_ADDITIONAL_DATA = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
MAX_BLOCK_COST_CLVM = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.util.keychain import Keychain
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats
)
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.wallet import Wallet


config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555

PREFIX = "xch"

# TODO: Plug in some more CATs you care about here
global CATS
CATS = {
    "USDS": "6d95dae356e32a71db5ddcb42224754a02524c615c5fc35f568c2af04774e589",
    #"MZ": "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105",
    #"DBX": "db1a9020d48d9d4ad22631b66ab4b9ebd3637ef7758ad38881348c5d24c38f20",
}

# DERIVATIONS - how deep to look in the wallet
DERIVATIONS = int(os.environ.get('DERIVATIONS', 8150))

global wallet_keys
wallet_keys = []

wallet = Wallet()

puzzle_reveals = dict()

def wallet_keyf(pk):
    print(f'Looking for wallet keys to sign spend, PK: {pk}')
    for wallet_key in wallet_keys:
        synth_key = calculate_synthetic_secret_key(wallet_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        if synth_key.get_g1() == pk:
            return synth_key
    raise Exception("Evaluated all keys without finding PK match!")

async def fix_unhinted_coins(address, hint_puzzlehash, actual_puzzlehash, cat_asset_id: str = None):
    try:
        coin_records = dict()
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins_by_hash = await node_client.get_coin_records_by_puzzle_hash(actual_puzzlehash, False, 0)
        sum_by_hash = 0
        for coin_record in all_coins_by_hash:
            coin: Coin = coin_record.coin
            coin_records[coin.name().hex()] = coin_record
            sum_by_hash += int(coin.amount)

        sum_by_hint = 0
        all_coins_by_hint = await node_client.get_coin_records_by_hint(hint=hint_puzzlehash)
        for coin_record in all_coins_by_hint:
            coin: Coin = coin_record.coin
            sum_by_hint += int(coin.amount)

        if sum_by_hash > sum_by_hint:
            hash_coin_ids = set(map(lambda x: x.coin.name().hex(), all_coins_by_hash))
            hint_coin_ids = set(map(lambda x: x.coin.name().hex(), all_coins_by_hint))
            difference = hash_coin_ids.difference(hint_coin_ids)
            print(f'Address: {address}.  Hash found {sum_by_hash}, hint found {sum_by_hint}, difference is coins: {difference}')

            for coin_id in difference:
                coin_record = coin_records[coin_id]
                await spend_coin(node_client, coin_record, hint_puzzlehash, address_puzzlehash=actual_puzzlehash, cat_asset_id=cat_asset_id)

        #if len(all_coins_by_hash) > 0:
        #    print(f'Found {len(all_coins_by_hash)} coins by hash')

    finally:
        node_client.close()
        await node_client.await_closed()


async def migrate_coins(current_address, new_puzzlehash, current_actual_puzzlehash, cat_asset_id: str = None):  
    try:
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins_by_hash = await node_client.get_coin_records_by_puzzle_hash(current_actual_puzzlehash, False, 0)
        sum_by_hash = 0
        for coin_record in all_coins_by_hash:
            sum_by_hash += int(coin_record.coin.amount)

        if sum_by_hash > 0:
            print(f'Address: {current_address}.  Hash found {sum_by_hash}. Will migrate {len(all_coins_by_hash)} coins.')

        for coin_record in all_coins_by_hash:
            await spend_coin(node_client, coin_record, new_puzzlehash, address_puzzlehash=current_actual_puzzlehash, cat_asset_id=cat_asset_id)

    finally:
        node_client.close()
        await node_client.await_closed()


async def spend_coin(node_client, coin_record: CoinRecord, hint_puzzlehash: bytes32, address_puzzlehash: bytes32 = None, cat_asset_id = None):
    print(f'spend_coin: {coin_record.coin.name().hex()}')

    if address_puzzlehash is None:
        address_puzzlehash = hint_puzzlehash

    puzzle_reveal = puzzle_reveals[coin_record.coin.puzzle_hash]

    if puzzle_reveal is None:
        puzzle_reveal = puzzle_reveals[hint_puzzlehash]

    if puzzle_reveal is None:
        print("WARNING: Checked all known keys for valid puzzle reveal. Failed to find any.")
    else:
        spend_bundle: SpendBundle = None
        primaries = [{"puzzlehash": hint_puzzlehash, "amount": coin_record.coin.amount, "memos": [hint_puzzlehash]}]
        inner_solution = wallet.make_solution(
            primaries=primaries
        )
        if cat_asset_id is not None:
            spend_bundle = await calculate_cat_spend_bundle(coin_record, node_client, cat_asset_id, address_puzzlehash, puzzle_reveal, inner_solution)
            spend_bundle = await sign_coin_spends(spend_bundle.coin_spends, wallet_keyf, AGG_SIG_ME_ADDITIONAL_DATA, MAX_BLOCK_COST_CLVM)
        else:
            coin_spend = CoinSpend(
                coin_record.coin,
                puzzle_reveal,
                inner_solution
            )
            spend_bundle = await sign_coin_spends([coin_spend], wallet_keyf, AGG_SIG_ME_ADDITIONAL_DATA, MAX_BLOCK_COST_CLVM)

        await node_client.push_tx(spend_bundle)


async def calculate_cat_spend_bundle(coin_record: CoinRecord, node_client: FullNodeRpcClient, cat_asset_id: str, address_puzzlehash: bytes32, puzzle: Program, inner_solution: Program) -> SpendBundle:
    coin: Coin = coin_record.coin
    parent_coin_record: CoinRecord = await node_client.get_coin_record_by_name(coin.parent_coin_info)

    parent_coin: Coin = parent_coin_record.coin

    # cross-check cat puzzle hash
    cat_puzzle = construct_cat_puzzle(CAT_MOD, bytes.fromhex(cat_asset_id), puzzle)

    assert cat_puzzle.get_tree_hash() == address_puzzlehash
    assert coin.puzzle_hash == cat_puzzle.get_tree_hash()
    parent_coin_spend: CoinSpend = await node_client.get_puzzle_and_solution(parent_coin.name(), parent_coin_record.spent_block_index)
 
    parent_puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    _, curried_args = parent_puzzle_reveal.uncurry()
    list_args = list(curried_args.as_iter())
    parent_inner_puzzlehash: bytes32 = list_args[-1].get_tree_hash()
    lineage_proof = LineageProof(parent_coin.parent_coin_info, parent_inner_puzzlehash, parent_coin.amount)
    
    spendable_cat = SpendableCAT(coin, bytes.fromhex(cat_asset_id), puzzle, inner_solution, Program.to([]), lineage_proof, 0)

    spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [spendable_cat])
    #print(f'spend_bundle: {spend_bundle}')
    return spend_bundle


def calculate_cat_address(address, asset_id):
    inner_puzzlehash_bytes32: bytes32 = decode_puzzle_hash(address)
    prefix = address[: address.rfind("1")]

    # get_tree_hash supports a special "already hashed" list. We'are supposed to
    # curry in the full inner puzzle into CAT_MOD, but we only have its hash.
    # We can still compute the treehash similarly to how the CAT puzzle does it
    # using `puzzle-hash-of-curried-function` in curry_and_treehash.clib.
    outer_puzzlehash = CAT_MOD.curry(
        CAT_MOD.get_tree_hash(), bytes32.from_hexstr(asset_id), inner_puzzlehash_bytes32
    ).get_tree_hash_precalc(inner_puzzlehash_bytes32)

    return (encode_puzzle_hash(outer_puzzlehash, prefix), outer_puzzlehash)    


def usage():
    print('USAGE: python wallet_repair.py <WALLET_FINGERPRINT_TO_FIX> <optional:NEW XCH ADDRESS>')
    exit(1)


async def main():
    argc = len(sys.argv)
    if argc < 2 or argc > 3:
        usage()

    fingerprint = int(sys.argv[1])
    new_xch_address: str = None

    if argc == 3:
        new_xch_address = sys.argv[2]
        print(f'Will move all coins found to {new_xch_address}. If this is not what you want, cancel NOW (Ctrl+C)!')
        if not new_xch_address.startswith(PREFIX) or len(new_xch_address) != 62:
            usage()

    print(f'Loading private keys from keychain for fingerprint {fingerprint}')
    print(f'Is keychain locked? {Keychain.is_keyring_locked()}')
    keychain = Keychain()
    sk = keychain.get_private_key_by_fingerprint(fingerprint)

    print(f'Deriving {DERIVATIONS} addresses (both hardened and unhardened)')
    addresses = set()
    for i in range(DERIVATIONS):
        wk1 = master_sk_to_wallet_sk_unhardened(sk[0], i)
        wk2 = master_sk_to_wallet_sk(sk[0], i)
        wallet_keys.append(wk1)
        wallet_keys.append(wk2)
        # unhardened
        ph = create_puzzlehash_for_pk(wk1.get_g1())
        address = encode_puzzle_hash(ph, PREFIX)
        addresses.add(address)
        # hardened
        ph = create_puzzlehash_for_pk(wk2.get_g1())
        address = encode_puzzle_hash(ph, PREFIX)
        addresses.add(address)

    print(f'Caching {len(wallet_keys)} wallet keys')
    for wallet_key in wallet_keys:
        pk = wallet_key.get_g1()
        puzzle = puzzle_for_pk(pk)
        puzzle_reveals[puzzle.get_tree_hash()] = puzzle
    
    print('XCH')
    for address in addresses:
        puzzlehash = decode_puzzle_hash(address)
        if new_xch_address is None:
            await fix_unhinted_coins(address, puzzlehash, puzzlehash)
        else:
            new_hint_puzzlehash = decode_puzzle_hash(new_xch_address)
            await migrate_coins(address, new_hint_puzzlehash, puzzlehash)

    for cat, asset_id in CATS.items():
        print(cat, asset_id)
        for address in addresses:
            (cat_address, cat_puzzlehash) = calculate_cat_address(address, asset_id)
            raw_puzzlehash = decode_puzzle_hash(address)
            if new_xch_address is None:
                await fix_unhinted_coins(cat_address, raw_puzzlehash, cat_puzzlehash, asset_id)
            else:
                new_hint_puzzlehash = decode_puzzle_hash(new_xch_address)
                await migrate_coins(address, new_hint_puzzlehash, puzzlehash)



if __name__ == "__main__":
    asyncio.run(main())
