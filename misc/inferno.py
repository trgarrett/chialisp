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

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.puzzle_drivers import PuzzleInfo

from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger()

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256


class Inferno:

    def __init__(self, target, wallet_client):
        self.target = target
        logger.info(f"Will write to: {self.target}")
        self.wallet_client = wallet_client
    
    async def make_burn_offer(self, old_ids: List[str], new_ids: List[str], fee: int=0):
        logger.info(f"make_burn_offer. old: {','.join(old_ids)} ; new: {','.join(new_ids)}")

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
                "owner": "0x" + info.owner_did.hex() if info.owner_did is not None else "()",
                "transfer_program": {
                    "type": "royalty transfer program",
                    "launcher_id": "0x" + info.launcher_id.hex(),
                    "royalty_address": "0x" + info.royalty_puzzle_hash.hex(),
                    "royalty_percentage": str(info.royalty_percentage),
                },
            }
        return driver_dict


async def main():
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

    try:
        inferno = Inferno(target, wallet_client)

        logger.info(f"Loading CSV from: {csv_file}")

        with open(csv_file, 'r') as f:
            reader = csv.reader(f, delimiter=',', quotechar='"')
            for row in reader:
                if not row[0].startswith("#"):
                    old_ids = row[0].split(",")
                    new_ids = row[1].split(",")
                    fee = row[2]
                    await inferno.make_burn_offer(old_ids, new_ids, fee)
    finally:
        wallet_client.close()
        await wallet_client.await_closed()



def usage():
    logger.info("Usage: python3 inferno.py <csv file> <offers directory>\n")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
