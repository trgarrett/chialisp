import asyncio
import os
import sys

from blspy import G2Element

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
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.wallet import Wallet

ACS: Program = Program.to(1)

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

wallet = Wallet()

puzzle_reveals = dict()

async def migrate_coins(current_puzzlehash, new_puzzlehash, cat_asset_id: str = None):
    try:
        print(f"Migrating coins from {current_puzzlehash.hex()} to {new_puzzlehash.hex()}")
        node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        all_coins_by_hash = await node_client.get_coin_records_by_puzzle_hash(current_puzzlehash, False, 0)
        print(f"Found {len(all_coins_by_hash)} coins")
        sum_by_hash = 0
        for coin_record in all_coins_by_hash:
            sum_by_hash += int(coin_record.coin.amount)

        if sum_by_hash > 0:
            print(f'Hash found {sum_by_hash}. Will migrate {len(all_coins_by_hash)} coins.')

        for coin_record in all_coins_by_hash:
            await spend_coin(node_client, coin_record, new_puzzlehash, address_puzzlehash=current_puzzlehash, cat_asset_id=cat_asset_id)

    finally:
        node_client.close()
        await node_client.await_closed()


async def spend_coin(node_client, coin_record: CoinRecord, hint_puzzlehash: bytes32, address_puzzlehash: bytes32 = None, cat_asset_id = None):
    print(f'spend_coin: {coin_record.coin.name().hex()}')

    if address_puzzlehash is None:
        address_puzzlehash = hint_puzzlehash

    puzzle_reveal = ACS

    if puzzle_reveal is None:
        puzzle_reveal = puzzle_reveals[hint_puzzlehash]

    if puzzle_reveal is None:
        print("WARNING: Checked all known keys for valid puzzle reveal. Failed to find any.")
    else:
        spend_bundle: SpendBundle = None
        primaries = [Payment(hint_puzzlehash, coin_record.coin.amount, [hint_puzzlehash])]
        inner_solution = ACS
        inner_solution = wallet.make_solution(
            primaries=primaries
        )
        if cat_asset_id is not None:
            spend_bundle = await calculate_cat_spend_bundle(coin_record, node_client, cat_asset_id, address_puzzlehash, puzzle_reveal, inner_solution)
        else:
            coin_spend = CoinSpend(
                coin_record.coin,
                puzzle_reveal,
                inner_solution
            )
            spend_bundle = SpendBundle([coin_spend], G2Element())

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
    print('USAGE: python acs_recover.py <NEW XCH ADDRESS>')
    exit(1)


async def main():
    argc = len(sys.argv)
    if argc < 2 or argc > 2:
        usage()

    new_xch_address: str = None

    if argc == 2:
        new_xch_address = sys.argv[1]
        print(f'Will move all coins found to {new_xch_address}. If this is not what you want, cancel NOW (Ctrl+C)!')
        if not new_xch_address.startswith(PREFIX) or len(new_xch_address) != 62:
            usage()

    print('XCH')
    puzzlehash = ACS.get_tree_hash()
    address = encode_puzzle_hash(puzzlehash, PREFIX)
    new_puzzlehash = decode_puzzle_hash(new_xch_address)
    await migrate_coins(puzzlehash, new_puzzlehash)


if __name__ == "__main__":
    asyncio.run(main())
