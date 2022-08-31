import asyncio
from blspy import G2Element
import json
import sys
import time

from chia.consensus.default_constants import DEFAULT_CONSTANTS
MAX_BLOCK_COST_CLVM = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash
from chia.util.condition_tools import conditions_for_solution
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet import Wallet

from pathlib import Path
from chia.util.byte_types import hexstr_to_bytes
from sim import load_clsp_relative

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256
prefix = "xch"


def print_json(dict):
    print(json.dumps(dict, sort_keys=True, indent=4))

async def spend_unspent_coins(royalty_address, royalty_puzzle_hash, royalty_puzzle, cat_asset_id=None):  
    try:
        if cat_asset_id:
            print(f"\tTrying address {royalty_address} as CAT with TAIL hash {cat_asset_id}")
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_royalty_coins = await node_client.get_coin_records_by_puzzle_hash(royalty_puzzle_hash, False, 2180000)
        for coin_record in all_royalty_coins:
            try:
                coin_record = await node_client.get_coin_record_by_name(coin_record.coin.name())
                print(f"unspent coin_record: \r\n{coin_record}")        

                #Spent Coin
                coin_spend = CoinSpend(
                    coin_record.coin,
                    royalty_puzzle,
                    Program.to([coin_record.coin.amount])
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

                # TODO: coin selection and fee calculation
                # general approach: 
                # add fee coin(s) to coin_spend with puzzlehash=*my wallet* with amount=(coin amount - max fees) -> allow remainder to go to farmer
                # update spend bundle aggregated signature
                # if max_fees > 0:
                #    spend_bundle = add_fees_to_spend_bundle(spend_bundle, max_fees)

                print_json(spend_bundle.to_json_dict())
                status = await node_client.push_tx(spend_bundle)
                print_json(status)
            except Exception as e: 
                print('Failed on: ')
                print(repr(e))
                print('\r\n...Continuing to next coin')
    finally:
        node_client.close()
        await node_client.await_closed()

def usage():
    print(f"Usage: python royalty_share_spend.py <ROYALTY_ADDRESS> <PATH_TO_CURRIED_ROYALTY_PUZZLE_AS_HEX> \r\n")
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

    spendable_cat = SpendableCAT(coin, bytes.fromhex(cat_asset_id), royalty_puzzle, Program.to([coin.amount]), Program.to([]), lineage_proof, 0)

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
    ).get_tree_hash(inner_puzzlehash_bytes32)

    return (encode_puzzle_hash(outer_puzzlehash, prefix), outer_puzzlehash)    

async def main():

    if(len(sys.argv) != 3):
        usage()
        exit(1)

    royalty_address = sys.argv[1]
    royalty_puzzle_hash = decode_puzzle_hash(sys.argv[1])
    royalty_puzzle = None
    text: str = None

    with open(sys.argv[2], 'r') as f:
        text = f.readlines()[0]

    clvm_blob = bytes.fromhex(text)
    sp = SerializedProgram.from_bytes(clvm_blob)
    royalty_puzzle = Program.from_bytes(bytes(sp))

    print('Checking XCH spends...')
    await spend_unspent_coins(royalty_address, royalty_puzzle_hash, royalty_puzzle)

    # It's highly likely you will want to support a different set of these
    # TODO: look at API or CSV import of all/as many as you care about
    cats = {
        "LKY8": "e5a8af7124c2737283838e6797b0f0a5293fc81aca1ffd2720f8506c23f2ad88",
        "SBX": "a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913"
    }

    print('Checking CAT spends...')
    for cat, asset_id in cats.items():
        print(cat, asset_id)
        (cat_royalty_address, cat_royalty_puzzle_hash) = calculate_cat_royalty_address(royalty_address, asset_id)
        await spend_unspent_coins(cat_royalty_address, cat_royalty_puzzle_hash, royalty_puzzle, asset_id)

if __name__ == "__main__":
    asyncio.run(main())