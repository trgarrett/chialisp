import asyncio

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.default_constants import DEFAULT_CONSTANTS
AGG_SIG_ME_ADDITIONAL_DATA = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
MAX_BLOCK_COST_CLVM = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.util.keychain import Keychain
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
)
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
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
}

# DERIVATIONS - how deep to look in the wallet
DERIVATIONS = 8150

global wallet_keys
wallet_keys = []


def wallet_keyf(pk):
    print(f'Looking for wallet keys to sign spend, PK: {pk}')
    for wallet_key in wallet_keys:
        synth_key = calculate_synthetic_secret_key(wallet_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        if synth_key.get_g1() == pk:
            return synth_key
    raise Exception("Evaluated all keys without finding PK match!")

async def fix_unhinted_coins(address, hint_puzzlehash, actual_puzzlehash):  
    try:
        coins = dict()
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins_by_hash = await node_client.get_coin_records_by_puzzle_hash(actual_puzzlehash, False, 0)
        sum_by_hash = 0
        for coin_record in all_coins_by_hash:
            coin: Coin = coin_record.coin
            coins[coin.name().hex()] = coin
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
                coin = coins[coin_id]
                await spend_coin(node_client, coin, hint_puzzlehash)

    finally:
        node_client.close()
        await node_client.await_closed()

async def spend_coin(node_client, coin: Coin, hint_puzzlehash: bytes32):
    print(f'spend_coin: {coin}')

    puzzle_reveal = None
    #print(f'checking {len(wallet_keys)} wallet keys')
    for wallet_key in wallet_keys:
        pk = wallet_key.get_g1()
        candidate_puzzle_reveal = puzzle_for_pk(pk)
        if candidate_puzzle_reveal.get_tree_hash() == coin.puzzle_hash:
            puzzle_reveal = candidate_puzzle_reveal
            break

    primaries = [{"puzzlehash": coin.puzzle_hash, "amount": coin.amount, "memos": [hint_puzzlehash]}]
    solution = Wallet().make_solution(
        primaries=primaries
    )

    if puzzle_reveal is None:
        print("WARNING: Checked all known keys for valid puzzle reveal. Failed to find any.")
    else:
        coin_spend = CoinSpend(
            coin,
            puzzle_reveal,
            solution
        )
        spend_bundle = await sign_coin_spends([coin_spend], wallet_keyf, AGG_SIG_ME_ADDITIONAL_DATA, MAX_BLOCK_COST_CLVM)
        await node_client.push_tx(spend_bundle)


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

async def main():
    print('Loading private keys from keychain')
    print(f'Is keychain locked? {Keychain.is_keyring_locked()}')
    keychain = Keychain()
    all_sks = keychain.get_all_private_keys()
    print(f'Deriving {DERIVATIONS} addresses (both hardened and unhardened)')
    addresses = set()
    #addresses.add("xch1ep9qna5fdvpscpztqaeyq25nd2ljmzm22fhfd33khwtdr452z5gsr6u0r7")
    for i in range(DERIVATIONS):
        for sk in all_sks:
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
    
    print('XCH')
    for address in addresses:
        puzzlehash = decode_puzzle_hash(address)
        await fix_unhinted_coins(address, puzzlehash, puzzlehash)

    for cat, asset_id in CATS.items():
        print(cat, asset_id)
        for address in addresses:
            (cat_address, cat_puzzlehash) = calculate_cat_address(address, asset_id)
            raw_puzzlehash = decode_puzzle_hash(address)
            await fix_unhinted_coins(cat_address, raw_puzzlehash, cat_puzzlehash)


if __name__ == "__main__":
    asyncio.run(main())