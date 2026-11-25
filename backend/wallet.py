import hashlib
import json
import os
import secrets

from ecdsa import SigningKey, VerifyingKey, SECP256k1

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def ripemd160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", data).digest()

def b58encode(raw: bytes) -> str:
    num = int.from_bytes(raw, "big")
    out = ""
    while num > 0:
        num, rem = divmod(num, 58)
        out = B58_ALPHABET[rem] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    num = 0
    for ch in text:
        num = num * 58 + B58_ALPHABET.index(ch)
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(text) - len(text.lstrip("1"))
    return b"\x00" * pad + raw


def b58check_encode(version: bytes, payload: bytes) -> str:
    data = version + payload
    checksum = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    return b58encode(data + checksum)


def b58check_is_valid(text: str) -> bool:
    try:
        raw = b58decode(text)
    except ValueError:
        return False
    if len(raw) < 5:
        return False
    data, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4] == checksum

def compressed_pubkey(pubkey_raw: bytes) -> bytes:
    """64 байта (X||Y) -> 33 байта: 02/03 + X (сжатый ключ Bitcoin)."""
    x, y = pubkey_raw[:32], pubkey_raw[32:]
    prefix = b"\x02" if y[-1] % 2 == 0 else b"\x03"
    return prefix + x


def hash160(data: bytes) -> bytes:
    return ripemd160(hashlib.sha256(data).digest())


def btc_address_from_pubkey(pubkey_hex: str, compressed: bool = True) -> str:
    raw = bytes.fromhex(pubkey_hex)
    key = compressed_pubkey(raw) if compressed else b"\x04" + raw
    return b58check_encode(b"\x00", hash160(key))


def private_key_to_wif(private_key_hex: str, compressed: bool = True) -> str:
    payload = bytes.fromhex(private_key_hex) + (b"\x01" if compressed else b"")
    return b58check_encode(b"\x80", payload)


def candidate_addresses(pubkey_hex: str) -> set:
    raw = bytes.fromhex(pubkey_hex)
    return {
        btc_address_from_pubkey(pubkey_hex, True),
        btc_address_from_pubkey(pubkey_hex, False),
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(raw).hexdigest()[:40],
        hashlib.sha256(pubkey_hex.encode()).hexdigest(),
        hashlib.sha256(pubkey_hex.encode()).hexdigest()[:40],
        hash160(raw).hex(),
    }

class Wallet:
    def __init__(self, private_key_hex: str, address: str = None, login: str = None):
        self.signing_key = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
        self.verifying_key = self.signing_key.get_verifying_key()
        self.private_key = private_key_hex
        self.public_key = self.verifying_key.to_string().hex()
        self.btc_address = btc_address_from_pubkey(self.public_key)
        self.address = address or self.btc_address
        self.login = login

    @classmethod
    def generate(cls, login: str = None) -> "Wallet":
        sk = SigningKey.from_string(secrets.token_bytes(32), curve=SECP256k1)
        return cls(sk.to_string().hex(), login=login)

    @classmethod
    def from_keys(cls, data: dict) -> "Wallet":
        priv = (data.get("private_key") or "").strip()
        if not priv:
            raise ValueError("В файле ключей нет поля private_key")
        wallet = cls(priv, address=(data.get("address") or None), login=data.get("login"))
        pub = (data.get("public_key") or "").strip().lower()
        if pub and pub not in (wallet.public_key, "04" + wallet.public_key):
            raise ValueError("public_key не соответствует private_key")
        return wallet

    def sign(self, payload: bytes) -> str:
        return self.signing_key.sign(payload).hex()

    def to_dict(self, include_private: bool = False) -> dict:
        data = {
            "login": self.login,
            "address": self.address,
            "public_key": self.public_key,
            "btc_address": self.btc_address,
            "compressed_public_key": compressed_pubkey(bytes.fromhex(self.public_key)).hex(),
        }
        if include_private:
            data["private_key"] = self.private_key
            data["wif"] = private_key_to_wif(self.private_key)
        return data

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(include_private=True), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str):
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return cls.from_keys(json.load(fh))