import abc
import hashlib
import time
import json
from ecdsa import VerifyingKey, SECP256k1

class ITransaction(abc.ABC):
    @abc.abstractmethod
    def to_dict(self) -> dict:
        pass

    @abc.abstractmethod
    def get_tx_id(self) -> str:
        pass

class IBlock(abc.ABC):
    def __init__(self, index: int, prev_hash: str, transactions: list, difficulty: int = 3):
        self.index = index
        self.prev_hash = prev_hash
        self.transactions = transactions
        self.difficulty = difficulty
        self.nonce = 0
        self.hash = None

    @abc.abstractmethod
    def calculate_hash(self) -> str:
        pass

    @abc.abstractmethod
    def mine(self):
        pass

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "hash": self.hash
        }

class MyTx(ITransaction):
    def __init__(self, tx_data: dict):
        self.tx_id = tx_data.get("tx_id")
        self.body = tx_data.get("body", {})
        self.signature = tx_data.get("signature")

    def to_dict(self):
        return {
            "tx_id": self.tx_id,
            "body": self.body,
            "signature": self.signature
        }

    def get_tx_id(self):
        return self.tx_id

class MyBlock(IBlock):
    def calculate_hash(self):
        data = self.to_dict()
        del data["hash"]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def mine(self):
        t_pref = "0" * self.difficulty
        while True:
            self.hash() = self.calculate_hash()
            if self.hash.startswith(t_pref):
                break
            self.nonce += 1
        return

def verify_transaction(ready_tsx):
    total_fees = 0.0
    for tx_raw in ready_tsx:
        body = tx_raw.get("body", {})
        signature = tx_raw.get("signature")
        pubkey = body.get("sender_pubkey")
        if body.get("is_coinbase"):
            continue
        try:
            vk = VerifyingKey.from_string(bytes.fromhex(pubkey), curve=SECP256k1)
            payload = json.dumps(body, sort_keys=True).encode()
            if not vk.verify(bytes.fromhex(signature), payload):
                raise ValueError(f"Неверная подпись для транзакции: {tx_raw.get('tx_id')}")
        except Exception as err:
            raise ValueError(f"Ошибка верификации подписи: {str(err)}")
        total_fees += float(body.get("fee", 0))
    return total_fees

def create_coinbase(miner_address, total_fees, index):
    return {
        "tx_id": f"coinbase_{index}",
        "body": {
            "is_coinbase": True,
            "sender_address": "COINBASE",
            "recipient_address": miner_address,
            "item_id": "block_reward",
            "action": "REWARD",
            "amount": total_fees,
            "fee": 0,
            "timestamp": int(time.time()),
            "nonce": str(time.time())
        },
        "signature": "system"
    }

def mine(ready_tsx, miner_address, prev_hash):
    total_fees = verify_transaction(ready_tsx)
    index = int(time.time())
    coinbase = create_coinbase(miner_address, total_fees, index)
    block_trs = list(ready_tsx)
    block_trs.insert(0, coinbase)
    block = MyBlock(index=index, prev_hash=prev_hash, transactions=block_trs, difficulty=3)
    block.mine()
    return block.to_dict()