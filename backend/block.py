import hashlib
import json
import time

from ecdsa import VerifyingKey, SECP256k1, BadSignatureError

from interfaces import ITransaction, IBlock
from wallet import candidate_addresses, Wallet

DIFFICULTY = 3
DEFAULT_FEE = 0.1
QUORUM = 2

REQUIRED_BODY_FIELDS = (
    "sender_address", "sender_pubkey", "recipient_address",
    "item_id", "action", "amount", "fee", "timestamp", "nonce",
)
ACTIONS = ("BUY", "SELL", "TRANSFER")
ACTIONS_MOVING_FUNDS = ("BUY", "TRANSFER")


def tx_payload(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True).encode()


def compute_tx_id(body: dict, signature: str) -> str:
    return hashlib.sha256(tx_payload(body) + bytes.fromhex(signature)).hexdigest()


def tx_cost(body: dict) -> float:
    amount = float(body.get("amount", 0)) if body.get("action") in ACTIONS_MOVING_FUNDS else 0.0
    return amount + float(body.get("fee", 0))

class MyTx(ITransaction):
    def __init__(self, tx_data: dict):
        self.tx_id = tx_data.get("tx_id")
        self.body = dict(tx_data.get("body", {}))
        self.signature = tx_data.get("signature")

    def to_dict(self) -> dict:
        return {"tx_id": self.tx_id, "body": self.body, "signature": self.signature}

    def get_tx_id(self) -> str:
        return self.tx_id

    @classmethod
    def create(cls, wallet: Wallet, recipient_address: str, item_id: str, action: str,
               amount: float, fee: float = DEFAULT_FEE) -> "MyTx":
        body = {
            "sender_address": wallet.address,
            "sender_pubkey": wallet.public_key,
            "recipient_address": recipient_address.strip(),
            "item_id": item_id.strip(),
            "action": action.upper(),
            "amount": float(amount),
            "fee": float(fee),
            "timestamp": int(time.time()),
            "nonce": str(time.time()),
        }
        signature = wallet.sign(tx_payload(body))
        return cls({"tx_id": compute_tx_id(body, signature), "body": body, "signature": signature})

    @property
    def is_coinbase(self) -> bool:
        return bool(self.body.get("is_coinbase"))

    def verify_signature(self) -> bool:
        vk = VerifyingKey.from_string(bytes.fromhex(self.body["sender_pubkey"]), curve=SECP256k1)
        payload = tx_payload(self.body)
        sig = bytes.fromhex(self.signature)
        for hashfunc in (hashlib.sha1, hashlib.sha256):
            try:
                if vk.verify(sig, payload, hashfunc=hashfunc):
                    return True
            except BadSignatureError:
                continue
        return False

    def tx_id_is_valid(self) -> bool:
        payload = tx_payload(self.body)
        variants = {
            hashlib.sha256(payload + bytes.fromhex(self.signature)).hexdigest(),
            hashlib.sha256(payload + self.signature.encode()).hexdigest(),
        }
        return self.tx_id in variants


def create_coinbase(miner_address: str, total_fees: float, index: int) -> dict:
    return {
        "tx_id": f"coinbase_{index}",
        "body": {
            "is_coinbase": True,
            "sender_address": "COINBASE",
            "recipient_address": miner_address,
            "item_id": "block_reward",
            "action": "REWARD",
            "amount": round(total_fees, 8),
            "fee": 0,
            "timestamp": int(time.time()),
            "nonce": str(time.time()),
        },
        "signature": "system",
    }

def check_transaction(tx_data: dict, balances: dict = None, spent: dict = None,
                      chain_tx_ids: set = None, now: int = None) -> dict:
    checks = []

    def add(name, status, detail=""):
        checks.append({"name": name, "status": status, "detail": detail})

    tx_id = tx_data.get("tx_id") if isinstance(tx_data, dict) else None
    report = {"tx_id": tx_id, "valid": False, "cost": 0.0, "checks": checks}

    if not isinstance(tx_data, dict) or not isinstance(tx_data.get("body"), dict):
        add("Структура", "fail", "Транзакция должна иметь вид {tx_id, body, signature}")
        return report
    body = tx_data["body"]
    if body.get("is_coinbase"):
        add("Структура", "fail", "Coinbase создаёт только майнер, в мемпуле её быть не может")
        return report
    missing = [f for f in REQUIRED_BODY_FIELDS if f not in body]
    if missing or not tx_id or not tx_data.get("signature"):
        add("Структура", "fail", "Нет полей: " + ", ".join(missing or ["tx_id/signature"]))
        return report
    add("Структура", "ok", "Все 9 полей body, tx_id и signature на месте")

    try:
        amount, fee = float(body["amount"]), float(body["fee"])
        ts = int(body["timestamp"])
    except (TypeError, ValueError):
        add("Значения", "fail", "amount/fee/timestamp должны быть числами")
        return report
    now = now or int(time.time())
    problems = []
    if amount <= 0:
        problems.append("amount должен быть > 0")
    if fee < 0:
        problems.append("fee не может быть отрицательной")
    if str(body["action"]).upper() not in ACTIONS:
        problems.append(f"неизвестное действие {body['action']}")
    if body["sender_address"] == body["recipient_address"]:
        problems.append("отправитель и получатель совпадают")
    if ts > now + 300:
        problems.append("время транзакции в будущем")
    if problems:
        add("Значения", "fail", "; ".join(problems))
        return report
    add("Значения", "ok", f"{body['action']} {amount} + комиссия {fee}")

    tx = MyTx(tx_data)
    try:
        id_ok = tx.tx_id_is_valid()
    except ValueError:
        id_ok = False
    if not id_ok:
        add("Целостность TxID", "fail", "tx_id не равен SHA-256(body + signature) — данные изменены")
        return report
    add("Целостность TxID", "ok", "SHA-256(body + signature) совпадает")

    try:
        sig_ok = tx.verify_signature()
    except Exception as err:
        sig_ok = False
        add("Подпись ECDSA", "fail", f"Ошибка разбора ключа или подписи: {err}")
        return report
    if not sig_ok:
        add("Подпись ECDSA", "fail", "Подпись не соответствует публичному ключу отправителя")
        return report
    add("Подпись ECDSA", "ok", "SECP256k1, подпись верна")

    if body["sender_address"] in candidate_addresses(body["sender_pubkey"]):
        add("Адрес отправителя", "ok", "Адрес выведен из публичного ключа")
    else:
        add("Адрес отправителя", "warn", "Адрес выдан владельцем сети, схему вывода проверить нельзя")

    if chain_tx_ids is not None and tx_id in chain_tx_ids:
        add("Повтор", "fail", "Транзакция уже включена в блокчейн (double spend)")
        return report
    add("Повтор", "ok", "В блокчейне такой транзакции нет")

    cost = tx_cost(body)
    report["cost"] = cost
    if balances is None:
        add("Средства", "warn", "Балансы неизвестны — проверка пропущена")
    else:
        sender = body["sender_address"]
        available = float(balances.get(sender, 0)) - float((spent or {}).get(sender, 0))
        if available + 1e-9 < cost:
            add("Средства", "fail", f"Нужно {cost:.4f}, доступно {available:.4f}")
            return report
        add("Средства", "ok", f"Нужно {cost:.4f}, доступно {available:.4f}")

    report["valid"] = True
    return report


def select_valid(txs: list, balances: dict = None, chain_tx_ids: set = None):
    spent, accepted, rejected, seen = {}, [], [], set()
    for tx in sorted(txs, key=lambda t: int(t.get("body", {}).get("timestamp", 0) or 0)):
        if tx.get("tx_id") in seen:
            continue
        seen.add(tx.get("tx_id"))
        rep = check_transaction(tx, balances, spent, chain_tx_ids)
        if rep["valid"]:
            sender = tx["body"]["sender_address"]
            spent[sender] = spent.get(sender, 0) + rep["cost"]
            accepted.append(tx)
        else:
            rejected.append(rep)
    return accepted, rejected


def verify_transaction(ready_tsx: list) -> float:
    total_fees = 0.0
    for tx_raw in ready_tsx:
        if tx_raw.get("body", {}).get("is_coinbase"):
            continue
        tx = MyTx(tx_raw)
        try:
            ok = tx.verify_signature()
        except Exception as err:
            raise ValueError(f"Ошибка верификации подписи: {err}")
        if not ok:
            raise ValueError(f"Неверная подпись для транзакции: {tx.get_tx_id()}")
        total_fees += float(tx.body.get("fee", 0))
    return total_fees

class MyBlock(IBlock):
    def __init__(self, index: int, prev_hash: str, transactions: list, difficulty: int = DIFFICULTY):
        txs = [t.to_dict() if isinstance(t, ITransaction) else t for t in transactions]
        super().__init__(index, prev_hash, txs, difficulty)
        self.attempts = 0
        self.mining_seconds = 0.0

    def calculate_hash(self) -> str:
        data = self.to_dict()
        del data["hash"]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def mine(self):
        target = "0" * self.difficulty
        started = time.time()
        self.nonce = 0
        while True:
            self.hash = self.calculate_hash()
            self.attempts += 1
            if self.hash.startswith(target):
                break
            self.nonce += 1
        self.mining_seconds = round(time.time() - started, 3)
        return self.hash

    @classmethod
    def from_dict(cls, data: dict) -> "MyBlock":
        block = cls(data["index"], data["prev_hash"], data.get("transactions", []),
                    data.get("difficulty", DIFFICULTY))
        block.nonce = data.get("nonce", 0)
        block.hash = data.get("hash")
        return block


def mine(ready_tsx: list, miner_address: str, prev_hash: str, index: int = None,
         difficulty: int = DIFFICULTY) -> MyBlock:
    total_fees = verify_transaction(ready_tsx)
    index = index if index is not None else int(time.time())
    block_txs = [create_coinbase(miner_address, total_fees, index)] + list(ready_tsx)
    block = MyBlock(index=index, prev_hash=prev_hash, transactions=block_txs, difficulty=difficulty)
    block.mine()
    return block