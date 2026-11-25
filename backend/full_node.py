import json
import os
import sys

import requests

from interfaces import ITransaction, IBlock
from block import MyBlock, MyTx, QUORUM, DIFFICULTY, create_coinbase, select_valid
from blockchain import Blockchain

API_BASE = os.environ.get("API_BASE", "http://prima-412.ru/cgi-bin")
NODE_NAME = os.environ.get("NODE_NAME", "full_node")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
mirror = Blockchain(os.path.join(BASE_DIR, "data", "network_mirror")).initialize(create_genesis=False)


def load_my_address() -> str:
    for path in sys.argv[1:] + [os.path.join(BASE_DIR, "data", "wallet.json")]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)["address"]
    return input("Ваш адрес для награды: ").strip()


def votes_of(votes: dict, tx_id: str) -> int:
    v = votes.get(tx_id, 0)
    return len(v) if isinstance(v, (list, dict)) else int(v or 0)


def sync() -> dict:
    state = requests.get(f"{API_BASE}/api_state.py", timeout=10).json()
    mirror.replace_chain(state.get("chain") or [])
    mirror.replace_mempool(state.get("mempool") or [], state.get("votes") or {})
    return state


def show_mempool(state: dict) -> list:
    mempool = state.get("mempool") or []
    votes = state.get("votes") or {}
    if not mempool:
        print("  Мемпул пуст")
    for i, tx in enumerate(mempool, 1):
        b = tx["body"]
        print(f"  {i:>2}. {tx['tx_id'][:16]}…  {b['action']:<8} {b['amount']:>8} (+{b['fee']})  "
              f"{b['sender_address'][:10]}… → {b['recipient_address'][:10]}…  "
              f"«{b['item_id']}»  голосов: {votes_of(votes, tx['tx_id'])}/{QUORUM}")
    return mempool


def vote(state: dict):
    mempool = show_mempool(state)
    if not mempool:
        return
    num = input("Номер транзакции для голосования: ").strip()
    if not num.isdigit() or not 1 <= int(num) <= len(mempool):
        print("  Неверный номер")
        return
    tx_id = mempool[int(num) - 1]["tx_id"]
    resp = requests.post(f"{API_BASE}/api_tx.py?action=vote",
                         json={"tx_id": tx_id, "node_name": NODE_NAME}, timeout=10)
    print("  Ответ сервера:", resp.text[:300])


def mine_block(state: dict, my_address: str):
    votes = state.get("votes") or {}
    ready = [t for t in state.get("mempool") or [] if votes_of(votes, t["tx_id"]) >= QUORUM]
    balances = state.get("balances") or mirror.balances()
    chain = state.get("chain") or []
    accepted, rejected = select_valid(ready, balances, {t.get("tx_id") for b in chain for t in b["transactions"]})
    for rep in rejected:
        bad = next(c for c in rep["checks"] if c["status"] == "fail")
        print(f"  ✗ {str(rep['tx_id'])[:16]}… отклонена: {bad['name']} — {bad['detail']}")
    if not accepted:
        print("  Нет транзакций с кворумом и верной подписью")
        return
    index = len(chain)
    prev_hash = chain[-1]["hash"] if chain else "0" * 64
    total_fees = sum(float(t["body"]["fee"]) for t in accepted)
    txs = [create_coinbase(my_address, total_fees, index)] + [MyTx(t) for t in accepted]
    block = MyBlock(index, prev_hash, txs, DIFFICULTY)
    print(f"  Майнинг блока #{index} из {len(accepted)} транзакций (награда {total_fees})…")
    block.mine()
    print(f"  Найден nonce={block.nonce}, hash={block.hash} ({block.attempts} попыток, {block.mining_seconds} с)")
    resp = requests.post(f"{API_BASE}/api_block.py", json=block.to_dict(), timeout=10)
    print("  Ответ сервера:", resp.text[:300])


def show_chain(state: dict):
    for b in state.get("chain") or []:
        print(f"  #{b['index']}  {b['hash'][:20]}…  prev {str(b['prev_hash'])[:12]}…  "
              f"tx: {len(b['transactions'])}  nonce: {b['nonce']}")
    print("  Проверка целостности:", mirror.validate_chain(state.get("chain") or []))


my_address = load_my_address()
print(f"Полный узел «{NODE_NAME}», адрес награды: {my_address}\nСервер: {API_BASE}")
menu = {"1": "Синхронизация и мемпул", "2": "Голосовать за транзакцию",
        "3": "Смайнить блок", "4": "Блокчейн", "5": "Баланс", "0": "Выход"}
while True:
    print("\n" + "\n".join(f" {k}. {v}" for k, v in menu.items()))
    choice = input("> ").strip()
    if choice == "0":
        break
    try:
        state = sync()
        if choice == "1":
            show_mempool(state)
        elif choice == "2":
            vote(state)
        elif choice == "3":
            mine_block(state, my_address)
        elif choice == "4":
            show_chain(state)
        elif choice == "5":
            bal = (state.get("balances") or mirror.balances()).get(my_address, 0)
            print(f"  Баланс {my_address}: {bal}")
    except requests.RequestException as err:
        print("  Сервер недоступен:", err)
    except Exception as err:
        print("  Ошибка:", err)