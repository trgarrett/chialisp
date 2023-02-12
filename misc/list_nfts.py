import asyncio
import json
import sys

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256
prefix = "xch"

async def list_nfts(address, puzzle_hash):  
    try:
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins = await node_client.get_coin_records_by_hint(puzzle_hash, False, 0)

        print("************************************************************************************************************************************")
        print(f"* searching {len(all_coins)} unspent coins in address {address} *")
        print("************************************************************************************************************************************")
        for coin_record in all_coins:
            try:
                if coin_record.coin.puzzle_hash != puzzle_hash:
                    parent_coin_record = await node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
                    assert parent_coin_record is not None
                    puzzle_and_solution: CoinSpend = await node_client.get_puzzle_and_solution(coin_id=coin_record.coin.parent_coin_info, height=parent_coin_record.spent_block_index)
                    parent_puzzle_reveal = puzzle_and_solution.puzzle_reveal

                    try:
                        nft_program = Program.from_bytes(bytes(parent_puzzle_reveal))
                        nft = UncurriedNFT.uncurry(*nft_program.uncurry())

                        if nft is not None and nft.transfer_program_curry_params:
                            nft_puzzle_hash = bytes32.from_bytes(nft.transfer_program_curry_params.as_python()[0][1])
                            print(f"{nft_puzzle_hash.hex()} -> {encode_puzzle_hash(nft_puzzle_hash, 'nft')}")
                            print(f"\t last solution: '{puzzle_and_solution.solution}'\n\n")
                    except Exception as e:
                        print(f"Probably not an NFT? {repr(e)}")
                        pass 
            except Exception as e: 
                print('Failed on: ')
                print(repr(e))
                print('\r\n...Continuing to next coin')
    finally:
        node_client.close()
        await node_client.await_closed()

def usage():
    print(f"Usage: python list_nfts.py <ADDRESS>\r\n")
    exit(-1)

async def main():
    arg_count = len(sys.argv)
    
    if(arg_count != 2):
        usage()
        exit(1)

    address = sys.argv[1]
    puzzle_hash = decode_puzzle_hash(address)

    await list_nfts(address, puzzle_hash)

if __name__ == "__main__":
    asyncio.run(main())