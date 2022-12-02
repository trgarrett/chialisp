import asyncio
from blspy import G2Element
from collections import deque
import json
import os
import sys
import time
from typing import List

from chia.consensus.default_constants import DEFAULT_CONSTANTS
AGG_SIG_ME_ADDITIONAL_DATA = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
MAX_BLOCK_COST_CLVM = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_for_solution
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from chia.util.keychain import Keychain
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
from chia.wallet.puzzles.puzzle_utils import make_assert_coin_announcement
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet import Wallet
from clvm_tools.clvmc import compile_clvm

from pathlib import Path

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256
prefix = "xch"

global wallet_keys
wallet_keys = []

MIN_FEE = 1
MAX_FEE = 50000
DERIVATIONS = 1000

ASSERT_COIN_ANNOUNCEMENT = os.environ.get('ASSERT_COIN_ANNOUNCEMENT', True) is True
print(f'ASSERT_COIN_ANNOUNCEMENT: {ASSERT_COIN_ANNOUNCEMENT}')

recent_fee_coins: deque = deque([], 10)

def print_json(dict):
    print(json.dumps(dict, sort_keys=True, indent=4))

async def spend_unspent_coins(royalty_address, royalty_puzzle_hash, royalty_puzzle: Program, cat_asset_id=None, add_fees=False):  
    try:
        if cat_asset_id:
            print(f"\tTrying address {royalty_address} as CAT with TAIL hash {cat_asset_id}")
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
        all_royalty_coins = await node_client.get_coin_records_by_puzzle_hash(royalty_puzzle_hash, False, 0)
        for coin_record in all_royalty_coins:
            try:
                coin_record = await node_client.get_coin_record_by_name(coin_record.coin.name())
                print(f"unspent coin_record: \r\n{coin_record}")    
                
                # calculate total number of shares
                mod, curried_args = royalty_puzzle.uncurry()
                if mod == CAT_MOD:
                    mod, curried_args = curried_args.at("rrf").uncurry()
                payout_scheme = curried_args.first()

                total_shares = 0
                for entry in payout_scheme.as_iter():
                    total_shares += entry.rest().first().as_int()
                

                #Spent Coin
                coin_spend = CoinSpend(
                    coin_record.coin,
                    royalty_puzzle,
                    Program.to([coin_record.coin.amount, total_shares])
                )
                # empty signature i.e., c00000.....
                signature = G2Element()

                spend_bundle: SpendBundle = None

                if cat_asset_id:
                    spend_bundle = await calculate_cat_spend_bundle(coin_record, node_client, cat_asset_id, royalty_address, royalty_puzzle)
                else:
                    # SpendBundle
                    spend_bundle = SpendBundle(
                            # coin spends
                            [coin_spend],
                            # aggregated_signature
                            signature,
                        )

                if add_fees is True:
                    print(f'Adding fees: {MIN_FEE}')
                    spend_bundle = await add_fees_and_sign_spend_bundle(spend_bundle, node_client, wallet_client)

                print(f'{spend_bundle}')

                status = await node_client.push_tx(spend_bundle)
                print_json(status)
            except Exception as e: 
                print('Failed on: ')
                print(repr(e))
                print('\r\n...Continuing to next coin')
    finally:
        node_client.close()
        wallet_client.close()
        await node_client.await_closed()

def wallet_keyf(pk):
    print(f'Looking for wallet keys to sign spend, PK: {pk}')
    for wallet_key in wallet_keys:
        synth_key = calculate_synthetic_secret_key(wallet_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        if synth_key.get_g1() == pk:
            return synth_key
    raise Exception("Evaluated all keys without finding PK match!")

async def estimate_fees_by_mempool(spend_bundle: SpendBundle, node_client: FullNodeRpcClient) -> uint64:
    mempool_size = len(await node_client.get_all_mempool_tx_ids())
    huge_mempool = float(400.0)
    if mempool_size < 10:
        return uint64(MIN_FEE)
    elif mempool_size > huge_mempool:
        return uint64(MAX_FEE)
    else:
        return uint64(MAX_FEE * (mempool_size / huge_mempool))


async def add_fees_and_sign_spend_bundle(spend_bundle: SpendBundle, node_client: FullNodeRpcClient, wallet_client: WalletRpcClient):
    updated_coin_spends = []
    updated_coin_spends.extend(spend_bundle.coin_spends)

    fees_remaining: uint64 = await estimate_fees_by_mempool(spend_bundle, node_client)
    print(f'Calculated target fees of {fees_remaining} using mempool')
    
    fee_coins = await wallet_client.select_coins(amount=uint64(MAX_FEE), wallet_id=1, excluded_coins=list(recent_fee_coins))

    print(f'evaluating {len(fee_coins)} coin(s) for fees')
    for fee_coin in fee_coins:
        print(f'{fee_coin}')
        if fees_remaining <= 0:
            break
        if fee_coin.amount >= fees_remaining:
            recent_fee_coins.append(fee_coin)
            change_spend = await calculate_change_spend(node_client, fee_coin, fees_remaining, spend_bundle.coin_spends)
            updated_coin_spends.append(change_spend)
            fees_remaining = 0
        elif fee_coin.amount < fees_remaining:
            change_spend = await calculate_change_spend(node_client, fee_coin, fee_coin.amount, spend_bundle.coin_spends)
            updated_coin_spends.append(change_spend)
            fees_remaining -= fee_coin.amount
            recent_fee_coins.append(fee_coin)

    spend_bundle = await sign_coin_spends(updated_coin_spends, wallet_keyf, AGG_SIG_ME_ADDITIONAL_DATA, MAX_BLOCK_COST_CLVM)

    return spend_bundle

async def calculate_change_spend(node_client: FullNodeRpcClient, fee_coin: Coin, fee_amount: uint64, peer_coin_spends: List[CoinSpend]):

    puzzle_reveal = None
    for wallet_key in wallet_keys:
        pk = wallet_key.get_g1()
        candidate_puzzle_reveal = puzzle_for_pk(pk)
        if candidate_puzzle_reveal.get_tree_hash() == fee_coin.puzzle_hash:
            puzzle_reveal = candidate_puzzle_reveal
            break
    if puzzle_reveal is None:
        raise Exception("Checked all known keys for valid puzzle reveal. Failed to find any.")

    change_amount = fee_coin.amount - fee_amount
    destination_puzzlehash = fee_coin.puzzle_hash
    primaries = [{"puzzlehash": destination_puzzlehash, "amount": change_amount, "memos": [destination_puzzlehash]}]

    # FIXME - if we further aggregate spend bundles, we need to assert ALL spends
    peer_coin_id = peer_coin_spends[0].coin.name()

    if ASSERT_COIN_ANNOUNCEMENT is True:
        assert_coin_announcement = Announcement(peer_coin_id, b'').name()
        solution = Wallet().make_solution(
            primaries=primaries,
            fee=fee_amount,
            # make sure our bundles aren't separated
            coin_announcements_to_assert = [assert_coin_announcement]
        )
    else:
        solution = Wallet().make_solution(
            primaries=primaries,
            fee=fee_amount
        )

    print(f'solution: {solution}')

    print(f'Prepping change spend of amount {change_amount} mojos')

    return CoinSpend(fee_coin, puzzle_reveal, solution)
    

def usage():
    print(f"Usage: python royalty_share_spend.py <ROYALTY_ADDRESS> <PATH_TO_CURRIED_ROYALTY_PUZZLE_AS_HEX> <optional:WALLET_FINGERPRINT_FOR_SIGNED_SPENDS> \r\n")
    exit(-1)

async def calculate_cat_spend_bundle(coin_record: CoinRecord, node_client: FullNodeRpcClient, cat_asset_id: str, royalty_address: str, royalty_puzzle: Program) -> SpendBundle:
    coin: Coin = coin_record.coin
    parent_coin_record: CoinRecord = await node_client.get_coin_record_by_name(coin.parent_coin_info)

    parent_coin: Coin = parent_coin_record.coin

    # cross-check cat puzzle hash
    cat_puzzle = construct_cat_puzzle(CAT_MOD, bytes.fromhex(cat_asset_id), royalty_puzzle)

    assert cat_puzzle.get_tree_hash() == decode_puzzle_hash(royalty_address)
    assert coin.puzzle_hash == cat_puzzle.get_tree_hash()
    parent_coin_spend: CoinSpend = await node_client.get_puzzle_and_solution(parent_coin.name(), parent_coin_record.spent_block_index)
 
    parent_puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    prog_final, curried_args = parent_puzzle_reveal.uncurry()
    list_args = list(curried_args.as_iter())
    parent_inner_puzzlehash: bytes32 = list_args[-1].get_tree_hash()
    lineage_proof = LineageProof(parent_coin.parent_coin_info, parent_inner_puzzlehash, parent_coin.amount)
    
    # calculate total number of shares
    mod, curried_args = royalty_puzzle.uncurry()
    if mod == CAT_MOD:
        mod, curried_args = curried_args.at("rrf").uncurry()
    payout_scheme = curried_args.first()

    total_shares = 0
    for entry in payout_scheme.as_iter():
        total_shares += entry.rest().first().as_int()

    spendable_cat = SpendableCAT(coin, bytes.fromhex(cat_asset_id), royalty_puzzle, Program.to([coin.amount, total_shares]), Program.to([]), lineage_proof, 0)

    return unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [spendable_cat])

def calculate_cat_royalty_address(royalty_address, asset_id):
    inner_puzzlehash_bytes32: bytes32 = decode_puzzle_hash(royalty_address)
    prefix = royalty_address[: royalty_address.rfind("1")]
    output_bech32m = True

    # get_tree_hash supports a special "already hashed" list. We'are supposed to
    # curry in the full inner puzzle into CAT_MOD, but we only have its hash.
    # We can still compute the treehash similarly to how the CAT puzzle does it
    # using `puzzle-hash-of-curried-function` in curry_and_treehash.clib.
    outer_puzzlehash = CAT_MOD.curry(
        CAT_MOD.get_tree_hash(), bytes32.from_hexstr(asset_id), inner_puzzlehash_bytes32
    ).get_tree_hash_precalc(inner_puzzlehash_bytes32)

    return (encode_puzzle_hash(outer_puzzlehash, prefix), outer_puzzlehash)    

async def main():
    arg_count = len(sys.argv)
    
    if(arg_count != 3 and arg_count != 4):
        usage()
        exit(1)

    royalty_address = sys.argv[1]
    royalty_puzzle_hash = decode_puzzle_hash(sys.argv[1])
    royalty_puzzle = None
    wallet_fingerprint = None
    text: str = None

    with open(sys.argv[2], 'r') as f:
        text = f.readlines()[0]

    if arg_count == 4:
        wallet_fingerprint = sys.argv[3]

    clvm_blob = bytes.fromhex(text)
    sp = SerializedProgram.from_bytes(clvm_blob)
    royalty_puzzle = Program.from_bytes(bytes(sp))

    if wallet_fingerprint is not None:
        print('Loading private key for spend bundle signing (fee support)')
        print(f'Is keychain locked? {Keychain.is_keyring_locked()}')
        keychain = Keychain()
        
        keychain.get_private_key_by_fingerprint

        all_sks = keychain.get_all_private_keys()

        print(f'Deriving {DERIVATIONS} synthetic private keys')
        for i in range(DERIVATIONS):
            for sk in all_sks:
                wallet_keys.append(master_sk_to_wallet_sk_unhardened(sk[0], i))

    print('Checking XCH spends...')

    add_fees = wallet_fingerprint is not None
    await spend_unspent_coins(royalty_address, royalty_puzzle_hash, royalty_puzzle, cat_asset_id=None, add_fees=add_fees)

    # It's highly likely you will want to support a different set of these
    # TODO: look at API or CSV import of all/as many as you care about
    cats = {
        "LKY8": "e5a8af7124c2737283838e6797b0f0a5293fc81aca1ffd2720f8506c23f2ad88",
        "SBX": "a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913",
        "TEST": "2267357bf318926f9ccaa5b68e1d4527df89b00c4aed41d6d590d75aa6fa0ff4",
        "USDS": "6d95dae356e32a71db5ddcb42224754a02524c615c5fc35f568c2af04774e589"
    }

    print('Checking CAT spends...')
    for cat, asset_id in cats.items():
        print(cat, asset_id)
        (cat_royalty_address, cat_royalty_puzzle_hash) = calculate_cat_royalty_address(royalty_address, asset_id)
        await spend_unspent_coins(cat_royalty_address, cat_royalty_puzzle_hash, royalty_puzzle, asset_id)

def load_clsp_relative(filename: str, search_paths: List[Path] = None):
    if search_paths is None:
        search_paths = [Path("include/")]
    base = Path().parent.resolve()
    source = base / filename
    target = base / f"{filename}.hex"
    searches = [base / s for s in search_paths]
    compile_clvm(source, target, searches)
    clvm = target.read_text()
    clvm_blob = bytes.fromhex(clvm)
    sp = SerializedProgram.from_bytes(clvm_blob)
    return Program.from_bytes(bytes(sp))

if __name__ == "__main__":
    asyncio.run(main())