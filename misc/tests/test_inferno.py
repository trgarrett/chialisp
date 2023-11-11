from time import sleep

import logging
import os
import pytest

from inferno import Inferno

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig

from typing import Tuple


PREFIX = "txch"

config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
self_hostname = "localhost"
full_node_rpc_port = config["full_node"]["rpc_port"] # 8555
wallet_rpc_port = config["wallet"]["rpc_port"] # 9256

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger()

##################################################################################################################
# NOTE: use one you have in your local simulator here!
FINGERPRINT = int(os.environ.get('FINGERPRINT', '1307711849'))
PRIMARY_PUZZLEHASH = os.environ.get('PRIMARY_PUZZLEHASH', '0x5052e86b33daa590496f886010235095e8f41f57f94db555a6ae1cedabe73cf6')


##################################################################################################################

class TestInferno:

    @pytest.mark.asyncio
    async def test(self):
        self.node_client = await FullNodeRpcClient.create(self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config)
        self.wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)

        did_id, _ = await self.create_did()
        recipient_puzzlehash = bytes32.from_hexstr(PRIMARY_PUZZLEHASH)
        old_id: bytes32 = await self.mint_nft(did_id, recipient_puzzlehash, 1)
        new_id: bytes32 = await self.mint_nft(did_id, recipient_puzzlehash, 2)

        inferno = Inferno()
        offer = await inferno.make_burn_offer(old_id, new_id)


    async def create_did(self) -> Tuple[str, bytes32]:
        logger.info("Creating DID wallet")
        res = await self.wallet_client.create_new_did_wallet(1)
        assert res["success"] is True
        did_id = res.get("my_did")
        did_coin_id = decode_puzzle_hash(did_id)
        did_launcher_coin_record = None
        did_launcher_coin_record = await self.wait_for_coin_record(did_coin_id)

        did_coin_record = await self.find_unspent_descendant(did_launcher_coin_record)
        assert did_coin_record is not None
        return did_id, did_coin_id


    async def mint_nft(self, did_id: str, recipient_puzzlehash: bytes32, suffix:int=1) -> bytes32:
        logger.info("Minting a fake NFT")

        res = await self.wallet_client.create_new_nft_wallet(did_id=did_id)
        assert res.get("success")
        wallet_id = res["wallet_id"]

        data_hash_param = "0xD4584AD463139FA8C0D9F68F4B59F185"
        address = encode_puzzle_hash(recipient_puzzlehash, prefix=PREFIX)

        tx_config = TXConfig(min_coin_amount=1, max_coin_amount=9999999999999, excluded_coin_amounts=[], excluded_coin_ids=[], reuse_puzhash=True)

        res = await self.wallet_client.mint_nft(
            wallet_id,
            address,
            address,
            data_hash_param,
            [f"https://example.com/img/{suffix}"],
            tx_config=tx_config,
            did_id=did_id
        )
        assert res.get("success")

        nft_id = res.get("nft_id")
        launcher_id = decode_puzzle_hash(nft_id)
        logger.info(f" {nft_id} -> {launcher_id}")
        return launcher_id
    

    async def wait_for_coin_record(self, coin_id: bytes32) -> CoinRecord:
        coin_record: CoinRecord = None
        for i in range(1, 20):
            logger.warning(f"Waiting for coin record...{coin_id.hex()}")
            coin_record = await self.node_client.get_coin_record_by_name(coin_id)
            sleep(i * 0.25)
            if coin_record is not None:
                break
        assert coin_record is not None
        return coin_record


    async def find_unspent_descendant(self, coin_record: CoinRecord) -> CoinRecord:
        if not coin_record.spent:
            return coin_record

        child: CoinRecord = (await self.node_client.get_coin_records_by_parent_ids([coin_record.coin.name()]))[0]
        if not child.spent:
            return child
        return await self.find_unspent_descendant(child)
