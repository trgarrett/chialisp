import asyncio
from blspy import G2Element
import json
import sys
import time

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from chia.wallet.transaction_record import TransactionRecord
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

async def spendUnspentCoins(royalty_address, royalty_puzzle_hash, royalty_puzzle, cat_asset_id=None):  
    try:
        if cat_asset_id:
            print(f"\tTrying address {royalty_address} as CAT with TAIL hash {cat_asset_id}")
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_royalty_coins = await node_client.get_coin_records_by_puzzle_hash(royalty_puzzle_hash, False, 2180000)
        for coin_record in all_royalty_coins:
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
            # SpendBundle
            spend_bundle = SpendBundle(
                    # coin spends
                    [coin_spend],
                    # aggregated_signature
                    signature,
                )
            print_json(spend_bundle.to_json_dict())
            status = await node_client.push_tx(spend_bundle)
            print_json(status)            
    finally:
        node_client.close()
        await node_client.await_closed()

def usage():
    print(f"Usage: python royalty_share_spend.py <ROYALTY_ADDRESS> <PATH_TO_CURRIED_ROYALTY_PUZZLE_AS_HEX> \r\n")
    exit(-1)

def calculate_royalty_address(royalty_address, asset_id):
    return (royalty_address, asset_id)

if __name__ == "__main__":

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
    asyncio.run(spendUnspentCoins(royalty_address, royalty_puzzle_hash, royalty_puzzle))

    # It's highly likely you will want to support a different set of these
    # TODO: look at API or CSV import of all/as many as you care about
    cats = {'LKY8': '0x7efa9f202cfd8e174e1376790232f1249e71fbe46dc428f7237a47d871a2b78b'}

    print('Checking CAT spends...')
    for cat in cats:
        asset_id = cats[cat]
        print(cat, asset_id)
        (royalty_address, royalty_puzzle_hash) = calculate_royalty_address(royalty_address, asset_id)
        asyncio.run(spendUnspentCoins(royalty_address, royalty_puzzle_hash, royalty_puzzle, asset_id))
