from blspy import G2Element

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.wallet import Wallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT

import asyncio
import json
import sys
import traceback

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256
prefix = "xch"

def print_json(dict):
    print(json.dumps(dict, sort_keys=True, indent=4))

async def spend_nfts(address, puzzle_hash):  
    try:
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins = await node_client.get_coin_records_by_hint(puzzle_hash, False, 0)

        print("************************************************************************************************************************************")
        print(f"* searching {len(all_coins)} unspent coins in address {address} *")
        print("************************************************************************************************************************************")
        for coin_record in all_coins:
            try:
                print('a')
                if coin_record.coin.puzzle_hash != puzzle_hash:
                    parent_coin_record = await node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
                    print('b')
                    assert parent_coin_record is not None
                    puzzle_and_solution: CoinSpend = await node_client.get_puzzle_and_solution(coin_id=coin_record.coin.parent_coin_info, height=parent_coin_record.spent_block_index)
                    parent_puzzle_reveal = puzzle_and_solution.puzzle_reveal
                    print('c')
                    #print(bytes(puzzle_and_solution.puzzle_reveal.to_program().to_serialized_program()).hex())
                    timelock_program_hex = "ff02ffff01ff02ffff01ff04ffff04ff0effff01ff808080ffff04ffff04ff08ffff04ff17ff808080ffff04ffff04ff0cffff04ff0bff808080ffff04ffff04ff0affff04ff05ffff04ff17ffff04ffff04ff05ff8080ff8080808080ff8080808080ffff04ffff01ffff4950ff333cff018080ffff04ffff01c04038316632616464353939653933376264346538633764393461323230653565306638646631363631326461373333316462633331646662343033363937343565ffff04ffff018200b4ff01808080"
                    timelock_clvm_blob = bytes.fromhex(timelock_program_hex)
                    timelock_inner_sp = SerializedProgram.from_bytes(timelock_clvm_blob)
                    p2_puzzle = Program.from_bytes(bytes(timelock_inner_sp))
                    print('d')

                    try:
                        #print(f'parent_puzzle_reveal treehash: {parent_puzzle_reveal.get_tree_hash()}')
                        nft_program = Program.from_bytes(bytes(parent_puzzle_reveal))
                        print('d.1')
                        unft = UncurriedNFT.uncurry(*nft_program.uncurry())
                        print('d.2')

                        parent_puzzle, curried_args = parent_puzzle_reveal.uncurry()
                        print('d.3')

                        list_args = list(curried_args.as_iter())
                        parent_inner_puzzlehash = unft.nft_state_layer.get_tree_hash()
                        print('d.4')

                        #print(f'singleton launcher id {unft.singleton_launcher_id.hex()}')
                        #print(f'metadata: {unft.metadata}')
                        #print(f'metadata_updater_hash: {unft.metadata_updater_hash}')
                        #print(f'p2_puzzle hash: {p2_puzzle.get_tree_hash().hex()}')
                        #assert p2_puzzle.get_tree_hash().hex() == "7607010a48321bc3b184a89d396101598d2098b6de536c1f7d1fe7e68c039a2c"
                        print('e')
                        
                        # metadata = {}
                        # for kv_pair in unft.metadata.as_iter():
                        #     metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
            
                        print(f'coin puzzle_hash: {coin_record.coin.puzzle_hash.hex()}')
                        
                        # print(unft.launcher_puzhash)
                        # print(unft.nft_inner_puzzle_hash)
                        # print(unft.nft_state_layer.to_serialized_program().get_tree_hash())
                        # print(f'p2 {unft.p2_puzzle.get_tree_hash()}')
                        # print(f'transfer program {unft.transfer_program.get_tree_hash().hex()}')

                        if unft is not None and unft.transfer_program_curry_params:
                            nft_puzzle_hash = bytes32.from_bytes(unft.transfer_program_curry_params.as_python()[0][1])
                            print(f"{nft_puzzle_hash.hex()} -> {encode_puzzle_hash(nft_puzzle_hash, 'nft')}")
                            print(f"\tlast solution: '{puzzle_and_solution.solution}'\n\n")
                            
                            lineage_proof = LineageProof(parent_coin_record.coin.parent_coin_info, parent_inner_puzzlehash, 1)
                            #primaries = [{"puzzlehash": puzzle_hash, "amount": 1, "memos": [puzzle_hash]}]
                            new_solution: Program = Program.to([1])
                            # new_solution: Program = Wallet().make_solution(
                            #     primaries=primaries,
                            #     coin_announcements=set((coin_record.coin.name(),))
                            # )
                            magic_condition = None
                            if unft.supports_did:
                                magic_condition = Program.to([-10, None, [], None])
                            if magic_condition:
                                # TODO: This line is a hack, make_solution should allow us to pass extra conditions to it
                                #innersol = Program.to([[], (1, magic_condition.cons(new_solution.at("rfr"))), []])
                                innersol = Program.to([1])
                            if unft.supports_did:
                                innersol = Program.to([innersol])

                            nft_layer_solution: Program = Program.to([innersol])

                            if unft.supports_did:
                                print('recurry for supports_did')
                                inner_puzzle = nft_puzzles.recurry_nft_puzzle(unft, puzzle_and_solution.solution.to_program(), p2_puzzle)
                            else:
                                print('inner puzzle is p2_puzzle')
                                inner_puzzle = p2_puzzle

                            full_puzzle = nft_puzzles.create_full_puzzle(unft.singleton_launcher_id, unft.metadata, unft.metadata_updater_hash, inner_puzzle)
                            print(f'full_puzzle_hash: {full_puzzle.get_tree_hash().hex()}')

                            assert full_puzzle.get_tree_hash().hex() == coin_record.coin.puzzle_hash.hex()

                            assert isinstance(lineage_proof, LineageProof)
                            singleton_solution = Program.to([lineage_proof.to_program(), 1, nft_layer_solution])
                            coin_spend = CoinSpend(coin_record.coin, full_puzzle, singleton_solution)
                            nft_spend_bundle = SpendBundle([coin_spend], G2Element())

                            print(f'spend bundle: {print_json(nft_spend_bundle.to_json_dict())}')
                            status = await node_client.push_tx(nft_spend_bundle)
                            print_json(status)

                    except Exception as e:
                        print(f"Probably not an NFT? {traceback.format_exc(e)}")
                        pass 
            except Exception as e:
                print('Failed on: ')
                print(repr(e))
                print('\r\n...Continuing to next coin')
    finally:
        node_client.close()
        await node_client.await_closed()

def usage():
    print(f"Usage: python spend_nfts_to_self.py <ADDRESS>\r\n")
    exit(-1)

async def main():
    arg_count = len(sys.argv)
    
    if(arg_count != 2):
        usage()
        exit(1)

    address = sys.argv[1]
    puzzle_hash = decode_puzzle_hash(address)

    await spend_nfts(address, puzzle_hash)

if __name__ == "__main__":
    asyncio.run(main())