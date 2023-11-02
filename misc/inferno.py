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
import logging
import sys

from chia.types.blockchain_format.sized_bytes import bytes32

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger()


class Inferno:
    
    async def make_burn_offer(self, old_id: bytes32, new_id: bytes32):
        logger.info(f"make_burn_offer: new {new_id.hex()}, old {old_id.hex()}, will burn old")

async def main():
    logger.info("main")
    argc = len(sys.argv)
    if argc != 3:
        usage()

def usage():
    logger.info("Usage: python3 inferno.py <csv file> <offers directory>\n")
    sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
