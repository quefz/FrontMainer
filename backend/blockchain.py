import glob
import json
import os
import threading
import time

from block import (DIFFICULTY, QUORUM, MyBlock, MyTx, check_transaction, select_valid,
                   create_coinbase, tx_cost, ACTIONS_MOVING_FUNDS)

GENESIS_PREV_HASH = "0" * 64
GENESIS_SUPPLY = 1000.0

def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


class Blockchain:
    def __init__(self, data_dir: str = "data/local", difficulty: int = DIFFICULTY):
        self.chain = []        
        self.current_transactions = [] 

        self.votes = {}                 
        self.difficulty = difficulty
        self.data_dir = data_dir
        self.blocks_dir = os.path.join(data_dir, "blocks")
        self.tx_file = os.path.join(data_dir, "mempool.json")
        self.votes_file = os.path.join(data_dir, "votes.json")
        self.lock = threading.RLock()

    def initialize(self, owner_address: str = None, create_genesis: bool = True) -> "Blockchain":
        with self.lock:
            self.chain = self.load_blocks()
            self.current_transactions = self.load_transactions()
            self.votes = _read_json(self.votes_file, {})
            if not self.chain and create_genesis:
                self.create_genesis_block(owner_address or "GENESIS_OWNER")
        return self

    def create_genesis_block(self, owner_address: str, supply: float = GENESIS_SUPPLY) -> dict:
        genesis_tx = {
            "tx_id": "genesis",
            "body": {
                "is_coinbase": True,
                "sender_address": "GENESIS",
                "recipient_address": owner_address,
                "item_id": "genesis_supply",
                "action": "GENESIS",
                "amount": float(supply),
                "fee": 0,
                "timestamp": int(time.time()),
                "nonce": str(time.time()),
                "message": "Genesis block: инициализация узла частной сети",
            },
            "signature": "system",
        }
        block = MyBlock(index=0, prev_hash=GENESIS_PREV_HASH, transactions=[genesis_tx],
                        difficulty=self.difficulty)
        block.mine()
        genesis = block.to_dict()
        with self.lock:
            self.chain = [genesis]
            self.save_block(genesis, 0)
        return genesis

    def save_transactions(self):
        with self.lock:
            _write_json(self.tx_file, self.current_transactions)
            _write_json(self.votes_file, self.votes)

    def load_transactions(self) -> list:
        data = _read_json(self.tx_file, [])
        return data if isinstance(data, list) else []

    def _block_path(self, position: int) -> str:
        return os.path.join(self.blocks_dir, f"block_{position:06d}.json")

    def save_block(self, block: dict, position: int):
        _write_json(self._block_path(position), block)

    def save_chain(self):
        with self.lock:
            os.makedirs(self.blocks_dir, exist_ok=True)
            for old in glob.glob(os.path.join(self.blocks_dir, "block_*.json")):
                os.remove(old)
            for pos, block in enumerate(self.chain):
                self.save_block(block, pos)

    def load_blocks(self) -> list:
        blocks = []
        for path in sorted(glob.glob(os.path.join(self.blocks_dir, "block_*.json"))):
            block = _read_json(path, None)
            if isinstance(block, dict) and "hash" in block:
                blocks.append(block)
        return blocks

    @property
    def last_block(self) -> dict:
        return self.chain[-1] if self.chain else None

    def chain_tx_ids(self) -> set:
        return {tx.get("tx_id") for b in self.chain for tx in b.get("transactions", [])}

    def balances(self) -> dict:
        """Балансы по подтверждённым блокам."""
        bal = {}
        for block in self.chain:
            for tx in block.get("transactions", []):
                body = tx.get("body", {})
                amount = float(body.get("amount", 0) or 0)
                recipient = body.get("recipient_address")
                if body.get("is_coinbase"):
                    bal[recipient] = bal.get(recipient, 0) + amount
                    continue
                sender = body.get("sender_address")
                bal[sender] = bal.get(sender, 0) - tx_cost(body)
                if body.get("action") in ACTIONS_MOVING_FUNDS:
                    bal[recipient] = bal.get(recipient, 0) + amount
        return {k: round(v, 8) for k, v in bal.items()}

    def vote_count(self, tx_id: str) -> int:
        return len(self.votes.get(tx_id, []))

    def add_transaction(self, tx_data: dict) -> dict:
        with self.lock:
            if any(t.get("tx_id") == tx_data.get("tx_id") for t in self.current_transactions):
                raise ValueError("Такая транзакция уже есть в мемпуле")
            pending = {}
            for t in self.current_transactions:
                s = t["body"]["sender_address"]
                pending[s] = pending.get(s, 0) + tx_cost(t["body"])
            report = check_transaction(tx_data, self.balances(), pending, self.chain_tx_ids())
            if not report["valid"]:
                failed = next(c for c in report["checks"] if c["status"] == "fail")
                raise ValueError(f"{failed['name']}: {failed['detail']}")
            self.current_transactions.append(MyTx(tx_data).to_dict())
            self.save_transactions()
            return report

    def vote(self, tx_id: str, node_name: str) -> int:
        with self.lock:
            if not any(t.get("tx_id") == tx_id for t in self.current_transactions):
                raise ValueError("Транзакции нет в мемпуле")
            voters = self.votes.setdefault(tx_id, [])
            if node_name in voters:
                raise ValueError(f"Узел {node_name} уже голосовал за эту транзакцию")
            voters.append(node_name)
            self.save_transactions()
            return len(voters)

    def ready_transactions(self, quorum: int = QUORUM) -> list:
        return [t for t in self.current_transactions if self.vote_count(t["tx_id"]) >= quorum]

    def mine_block(self, miner_address: str, tx_ids: list = None, quorum: int = QUORUM) -> dict:
        with self.lock:
            candidates = self.ready_transactions(quorum)
            if tx_ids:
                candidates = [t for t in candidates if t["tx_id"] in set(tx_ids)]
            accepted, rejected = select_valid(candidates, self.balances(), self.chain_tx_ids())
            if not accepted:
                raise ValueError("Нет проверенных транзакций с кворумом голосов для блока")
            index = len(self.chain)
            fees = sum(float(t["body"]["fee"]) for t in accepted)
            block = MyBlock(index, self.last_block["hash"],
                            [create_coinbase(miner_address, fees, index)] + accepted, self.difficulty)
            block.mine()
            self.add_block(block.to_dict())
            return {"block": block.to_dict(), "rejected": rejected,
                    "attempts": block.attempts, "seconds": block.mining_seconds}

    def add_block(self, block: dict):
        errors = self.validate_block(block, self.last_block)
        if errors:
            raise ValueError("; ".join(errors))
        with self.lock:
            self.chain.append(block)
            self.save_block(block, len(self.chain) - 1)
            included = {t.get("tx_id") for t in block["transactions"]}
            self.current_transactions = [t for t in self.current_transactions if t["tx_id"] not in included]
            for tx_id in included:
                self.votes.pop(tx_id, None)
            self.save_transactions()

    def validate_block(self, block: dict, prev: dict) -> list:
        errors = []
        obj = MyBlock.from_dict(block)
        if obj.calculate_hash() != block.get("hash"):
            errors.append(f"Блок {block.get('index')}: хэш не совпадает с содержимым")
        if not str(block.get("hash", "")).startswith("0" * int(block.get("difficulty", 0))):
            errors.append(f"Блок {block.get('index')}: не выполнен Proof-of-Work")
        if prev is not None and block.get("prev_hash") != prev.get("hash"):
            errors.append(f"Блок {block.get('index')}: prev_hash не указывает на предыдущий блок")
        txs = block.get("transactions", [])
        coinbases = [i for i, t in enumerate(txs) if t.get("body", {}).get("is_coinbase")]
        if prev is not None:
            if coinbases != [0]:
                errors.append(f"Блок {block.get('index')}: coinbase должна быть одна и первой")
            fees = sum(float(t["body"].get("fee", 0)) for t in txs[1:])
            if txs and float(txs[0]["body"].get("amount", 0)) > fees + 1e-9:
                errors.append(f"Блок {block.get('index')}: награда больше суммы комиссий")
        for tx in txs:
            if tx.get("body", {}).get("is_coinbase"):
                continue
            try:
                ok = MyTx(tx).verify_signature()
            except Exception:
                ok = False
            if not ok:
                errors.append(f"Блок {block.get('index')}: неверная подпись {tx.get('tx_id')}")
        return errors

    def validate_chain(self, chain: list = None) -> dict:
        chain = self.chain if chain is None else chain
        errors = []
        for i, block in enumerate(chain):
            errors += self.validate_block(block, chain[i - 1] if i else None)
        return {"valid": not errors, "blocks": len(chain), "errors": errors}

    def replace_chain(self, chain: list):
        with self.lock:
            self.chain = list(chain)
            self.save_chain()

    def replace_mempool(self, mempool: list, votes: dict):
        with self.lock:
            self.current_transactions = list(mempool)
            self.votes = votes
            self.save_transactions()