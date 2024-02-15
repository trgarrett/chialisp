##################################################################
#
# Inferno - offer a set of new NFTs 
#           for a set of deprecated NFTs to be auto-burned
#           upon acceptance of the offer
#
# Sponsored by Monkeyzoo
#
#
##################################################################
#
#  Process a CSV file in the format "nft1,nft2","nft3,nft4",1000
#    in which nft1,nft2 are the "old NFT IDs"
#             nft3,nft4      are replacement NFT IDs
#         and 1000 is the blockchain fee, in mojos.
#
##################################################################

import asyncio
import csv
import logging
import os
import sys

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_hash_for_synthetic_public_key,
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.trading.offer import Offer, NotarizedPayment, OFFER_MOD_HASH
from chia.wallet.wallet import Wallet

from typing import Dict, List, Optional, Set, Tuple

MAX_BLOCK_COST_CLVM = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
BURN_PUZZLEHASH = bytes32.from_hexstr("0x000000000000000000000000000000000000000000000000000000000000dead")
PREFIX = os.environ.get("PREFIX", "xch")
TESTNET = os.environ.get("TESTNET", "testnet10") # default testnet, but only used if prefix==txch
DERIVATIONS = int(os.environ.get("DERIVATIONS", "1000"))
FINGERPRINT = int(os.environ.get("FINGERPRINT", "-1"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger()

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256

agg_sig_config = None
if PREFIX == 'txch':
    try:
        agg_sig_config = bytes32.from_hexstr(config["farmer"]["network_overrides"]["constants"][TESTNET]["AGG_SIG_ME_ADDITIONAL_DATA"])
        logger.info(f"Loaded AGG_SIG_ME_ADDITIONAL_DATA override: {agg_sig_config}")
    except Exception as e:
        logger.warning(f"Tried loading AGG_SIG_ME_ADDITIONAL_DATA from config. Exception {e}")
AGG_SIG_ME_ADDITIONAL_DATA = agg_sig_config or DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA

puzzle_reveals = {}
wallet_keys = []

class Inferno:

    def __init__(self, target, wallet_client, node_client):
        self.target = target
        logger.info(f"Will write to: {self.target}")
        self.wallet_client = wallet_client
        self.node_client = node_client
        self.load_keys(FINGERPRINT)


    def load_keys(self, fingerprint: int):

        if len(wallet_keys) > 0:
            logger.info(f"Found {len(wallet_keys)} pre-loaded wallet keys, skipping")
            return

        logger.info(f"Loading private key for spend bundle signing (fee support and private spends), fingerprint {fingerprint}")
        logger.info(f'Is keychain locked? {Keychain.is_keyring_locked()}')
        keychain = Keychain()
        
        sk = keychain.get_private_key_by_fingerprint(fingerprint)
        assert sk is not None
        
        logger.info(f'Deriving {DERIVATIONS} synthetic private keys')
        for i in range(DERIVATIONS):
            wk1 = master_sk_to_wallet_sk_unhardened(sk[0], i)
            wk2 = master_sk_to_wallet_sk(sk[0], i)
            wallet_keys.append(wk1)
            wallet_keys.append(wk2)

        logger.info(f'Caching {len(wallet_keys)} wallet keys')
        for wallet_key in wallet_keys:
            pk = wallet_key.get_g1()
            puzzle = puzzle_for_pk(pk)
            puzzle_reveals[puzzle.get_tree_hash()] = puzzle


    async def make_burn_offer(self, old_ids: List[str], new_ids: List[str], fee: int=0) -> Offer:
        logger.info(f"make_burn_offer. old: {','.join(old_ids)} ; new: {','.join(new_ids)}")
        requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}

        driver_dict: Dict[bytes32, PuzzleInfo] = {}

        for nft_old_id in old_ids:
            nft_old_launcher_id = decode_puzzle_hash(nft_old_id)
            driver_dict[nft_old_launcher_id] = await self.get_puzzle_info(nft_old_launcher_id)
            requested_payments[nft_old_launcher_id] = [Payment(BURN_PUZZLEHASH, 1, [BURN_PUZZLEHASH])]

        offered_coins = []
        nft_new_launcher_ids = []
        spend_bundles = []

        for nft_new_id in new_ids:
            nft_new_launcher_id = decode_puzzle_hash(nft_new_id)
            driver_dict[nft_new_launcher_id] = await self.get_puzzle_info(nft_new_launcher_id)
            nft_new_launcher_coin_record: CoinRecord = await self.node_client.get_coin_record_by_name(nft_new_launcher_id)
            assert nft_new_launcher_coin_record is not None
            offered_coins.append(nft_new_launcher_coin_record.coin)
            nft_new_launcher_ids.append(nft_new_launcher_id)

        notarized_payments: Dict[bytes32 | None, List[NotarizedPayment]] = Offer.notarize_payments(requested_payments, offered_coins)
        announcements_to_assert: List[Announcement] = Offer.calculate_announcements(notarized_payments, driver_dict)
        announcements_to_assert_bytes = set()

        for announcement in announcements_to_assert:
            announcements_to_assert_bytes.add(announcement.name())

        for i in range(len(offered_coins)):
            nft_new_launcher_id = nft_new_launcher_ids[i]
            tx_bundle, _ = await self.make_transfer_nft_spend_bundle(nft_new_launcher_id, OFFER_MOD_HASH, announcements_to_assert_bytes)
            spend_bundles.append(tx_bundle)

        spend_bundle = None
        if len(spend_bundles) == 1:
            spend_bundle = spend_bundles[0]
        else:
            spend_bundle = SpendBundle.aggregate(spend_bundles)

        offer: Offer = Offer(notarized_payments, spend_bundle, driver_dict)
        return offer
    

    async def write_offer(self, offer: Offer, name: str, path: str):
        with open(path + "/" + name, "w") as f:
            f.write(offer.to_bech32())

    async def find_unspent_descendant(self, coin_record: CoinRecord) -> CoinRecord:
        if not coin_record.spent:
            return coin_record

        child: CoinRecord = (await self.node_client.get_coin_records_by_parent_ids([coin_record.coin.name()]))[0]
        if not child.spent:
            return child
        return await self.find_unspent_descendant(child)


    async def get_puzzle_info(self, coin_id: bytes32) -> PuzzleInfo:
        driver_dict = await self.get_driver_dict(coin_id)
        id = coin_id.hex()
        return PuzzleInfo(driver_dict[id])


    async def get_driver_dict(self, coin_id: bytes32) -> Dict:
        driver_dict = {}
        info = NFTInfo.from_json_dict((await self.wallet_client.get_nft_info(coin_id.hex()))["nft_info"])
        id = info.launcher_id.hex()
        assert isinstance(id, str)
        driver_dict[id] = {
            "type": "singleton",
            "launcher_id": "0x" + id,
            "launcher_ph": "0x" + info.launcher_puzhash.hex(),
            "also": {
                "type": "metadata",
                "metadata": info.chain_info,
                "updater_hash": "0x" + info.updater_puzhash.hex(),
            },
        }
        if info.supports_did:
            assert info.royalty_puzzle_hash is not None
            assert info.royalty_percentage is not None
            driver_dict[id]["also"]["also"] = {
                "type": "ownership",
                "owner": "()",
                "transfer_program": {
                    "type": "royalty transfer program",
                    "launcher_id": "0x" + info.launcher_id.hex(),
                    "royalty_address": "0x" + info.royalty_puzzle_hash.hex(),
                    "royalty_percentage": str(info.royalty_percentage),
                },
            }
        return driver_dict
    

    async def get_synthetic_private_key_for_puzzle_hash(self, puzzle_hash: bytes32):
        # TODO new API from upstream...implement if needed
        return None


    # transfer an NFT, held by the wallet for this app, to a new destination
    async def make_transfer_nft_spend_bundle(self, nft_launcher_id: bytes32, recipient_puzzlehash: bytes32, announcements_to_assert: Set[bytes], fee:int=0) -> Tuple[SpendBundle, bytes32]:
        logger.debug(f"Preparing spend bundle for transfer of NFT {encode_puzzle_hash(nft_launcher_id, 'nft')} to {encode_puzzle_hash(recipient_puzzlehash, PREFIX)}")

        nft_launcher_coin_record = await self.node_client.get_coin_record_by_name(nft_launcher_id)
        assert nft_launcher_coin_record is not None
        coin_record = await self.find_unspent_descendant(nft_launcher_coin_record)
        assert coin_record is not None
        parent_coin_record = await self.node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
        assert parent_coin_record is not None
        puzzle_and_solution: CoinSpend = await self.node_client.get_puzzle_and_solution(coin_id=coin_record.coin.parent_coin_info, height=parent_coin_record.spent_block_index)
        parent_puzzle_reveal = puzzle_and_solution.puzzle_reveal

        nft_program = Program.from_bytes(bytes(parent_puzzle_reveal))
        unft = UncurriedNFT.uncurry(*nft_program.uncurry())
        parent_inner_puzzlehash = unft.nft_state_layer.get_tree_hash()

        _, phs = nft_puzzles.get_metadata_and_phs(unft, puzzle_and_solution.solution)
        p2_puzzle = puzzle_reveals.get(phs)

        assert p2_puzzle is not None

        primaries = []
        primaries.append(Payment(recipient_puzzlehash, 1, [recipient_puzzlehash]))
        innersol = Wallet().make_solution(
            primaries=primaries,
            fee=fee,
            puzzle_announcements_to_assert=announcements_to_assert
        )
        
        if unft is not None:
            lineage_proof = LineageProof(parent_coin_record.coin.parent_coin_info, parent_inner_puzzlehash, 1)
            magic_condition = None
            if unft.supports_did:
                magic_condition = Program.to([-10, None, [], None])
            if magic_condition:
                innersol = Program.to(innersol)
            if unft.supports_did:
                innersol = Program.to([innersol])

            nft_layer_solution: Program = Program.to([innersol])

            if unft.supports_did:
                inner_puzzle = nft_puzzles.recurry_nft_puzzle(unft, puzzle_and_solution.solution.to_program(), p2_puzzle)
            else:
                inner_puzzle = p2_puzzle

            assert unft.singleton_launcher_id == nft_launcher_id

            full_puzzle = nft_puzzles.create_full_puzzle(unft.singleton_launcher_id, unft.metadata, unft.metadata_updater_hash, inner_puzzle)
            assert full_puzzle.get_tree_hash().hex() == coin_record.coin.puzzle_hash.hex()

            assert isinstance(lineage_proof, LineageProof)
            singleton_solution = Program.to([lineage_proof.to_program(), 1, nft_layer_solution])
            coin_spend = CoinSpend(coin_record.coin, full_puzzle, singleton_solution)

            nft_spend_bundle = await sign_coin_spends([coin_spend], wallet_keyf,
                                    self.get_synthetic_private_key_for_puzzle_hash,
                                    AGG_SIG_ME_ADDITIONAL_DATA, MAX_BLOCK_COST_CLVM, [puzzle_hash_for_synthetic_public_key])

            return nft_spend_bundle, inner_puzzle.get_tree_hash()
        else:
            raise RuntimeError("unexpected outcome of NFT transfer")


async def main():
    if os.environ.get("FINGERPRINT") is None:
        usage()

    argc = len(sys.argv)
    if argc != 3:
        usage()
    
    csv_file = sys.argv[1]
    target = sys.argv[2]
    if not os.path.isdir(target):
        os.mkdir(target)
    if not os.path.isfile(csv_file):
        usage()

    wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
    node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)

    try:
        inferno = Inferno(target, wallet_client, node_client)

        logger.info(f"Loading CSV from: {csv_file}")

        with open(csv_file, 'r') as f:
            reader = csv.reader(f, delimiter=',', quotechar='"')
            for row in reader:
                if len(row) > 0 and not row[0].startswith("#"):
                    old_ids = row[0].split(",")
                    new_ids = row[1].split(",")
                    fee = int(row[2])
                    offer: Offer = await inferno.make_burn_offer(old_ids, new_ids, fee)
                    await inferno.write_offer(offer, "_".join(old_ids) + ".offer", target)
    finally:
        wallet_client.close()
        node_client.close()
        await wallet_client.await_closed()
        await node_client.await_closed()


def wallet_keyf(pk):
    logger.info(f'Looking for wallet keys to sign spend, PK: {pk}')
    for wallet_key in wallet_keys:
        synth_key = calculate_synthetic_secret_key(wallet_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        if synth_key.get_g1() == pk:
            logger.info('Found key!')
            return synth_key
    raise RuntimeError("Evaluated all keys without finding PK match!")


def usage():
    logger.info("Usage: FINGERPRINT=<wallet fingerprint> python3 inferno.py <csv file> <offers directory>\n")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
