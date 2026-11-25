import os
import shutil

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from block import (DEFAULT_FEE, DIFFICULTY, QUORUM, MyBlock, MyTx, check_transaction,
                   create_coinbase, select_valid, tx_cost)
from blockchain import Blockchain, _read_json, _write_json
from contracts import contract_check, evaluate_deals
from wallet import Wallet, b58check_is_valid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("NODE_DATA_DIR", os.path.join(BASE_DIR, "data"))
CONFIG_FILE = os.path.join(DATA_DIR, "node_config.json")
WALLET_FILE = os.path.join(DATA_DIR, "wallet.json")
FRONTEND_DIST = os.path.join(BASE_DIR, "..", "frontend", "dist")
TIMEOUT = 10

config = {
    "mode": os.environ.get("NODE_MODE", "remote"),
    "node_name": os.environ.get("NODE_NAME", "full_node"),
    "api_base": os.environ.get("API_BASE", "http://prima-412.ru/cgi-bin"),
}
config.update(_read_json(CONFIG_FILE, {}))

wallet = Wallet.load(WALLET_FILE)
if wallet is None:
    wallet = Wallet.generate()
    wallet.save(WALLET_FILE)

local_chain = Blockchain(os.path.join(DATA_DIR, "local")).initialize(wallet.address)
mirror = Blockchain(os.path.join(DATA_DIR, "network_mirror")).initialize(create_genesis=False)

app = FastAPI(title="Полный узел")
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_origins=["*"],
    allow_headers=["*"],
)

def is_remote() -> bool:
    return config["mode"] == "remote"

def vote_names(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return [str(k) for k in value]
    try:
        return [f"узел {i + 1}" for i in range(int(value))]
    except (TypeError, ValueError):
        return []

def response_json(resp: requests.Response):
    try:
        return resp.json()
    except ValueError:
        return {"status_code": resp.status_code, "text": resp.text[:500]}

def fetch_remote_state() -> dict:
    data = requests.get(f"{config['api_base']}/api_state.py", timeout=TIMEOUT).json()
    chain = data.get("chain") or []
    mempool = data.get("mempool") or []
    votes = {k: vote_names(v) for k, v in (data.get("votes") or {}).items()}
    mirror.replace_chain(chain)
    mirror.replace_mempool(mempool, votes)
    balances = data.get("balances")
    return {"chain": chain, "mempool": mempool, "votes": votes,
            "balances": balances if isinstance(balances, dict) and balances else mirror.balances()}

def current_state() -> dict:
    if not is_remote():
        return {"source": "local", "stale": False, "error": None, "chain": local_chain.chain,
                "mempool": local_chain.current_transactions, "votes": local_chain.votes,
                "balances": local_chain.balances()}
    try:
        state = fetch_remote_state()
        state.update(source="remote", stale=False, error=None)
        return state
    except Exception as err:
        return {"source": "mirror", "stale": True, "error": f"Сервер сети недоступен: {err}",
                "chain": mirror.chain, "mempool": mirror.current_transactions,
                "votes": mirror.votes, "balances": mirror.balances()}

def pending_spent(mempool: list, exclude: str = None) -> dict:
    spent = {}
    for t in mempool:
        if t.get("tx_id") == exclude or t.get("body", {}).get("is_coinbase"):
            continue
        s = t["body"].get("sender_address")
        spent[s] = spent.get(s, 0) + tx_cost(t["body"])
    return spent

def chain_ids(chain: list) -> set:
    return {tx.get("tx_id") for b in chain for tx in b.get("transactions", [])}

def full_report(tx: dict, state: dict) -> dict:
    report = check_transaction(tx, state["balances"],
                               pending_spent(state["mempool"], exclude=tx.get("tx_id")),
                               chain_ids(state["chain"]))
    if report["valid"]:
        report["checks"].append(contract_check(tx, state["chain"], state["mempool"]))
    return report

def decorate_mempool(state: dict) -> list:
    out = []
    for tx in state["mempool"]:
        voters = state["votes"].get(tx.get("tx_id"), [])
        out.append({**tx, "votes": len(voters), "voters": voters,
                    "ready": len(voters) >= QUORUM,
                    "voted_by_me": config["node_name"] in voters})
    return out

def save_config():
    _write_json(CONFIG_FILE, config)

@app.get("/api/node")
def node_info():
    return {
        "node_name": config["node_name"],
        "mode": config["mode"],
        "api_base": config["api_base"],
        "quorum": QUORUM,
        "difficulty": DIFFICULTY,
        "default_fee": DEFAULT_FEE,
        "wallet": wallet.to_dict(),
        "local_height": len(local_chain.chain),
        "mirror_height": len(mirror.chain),
        "data_dir": DATA_DIR,
    }

@app.post("/api/node/config")
def update_config(data: dict):
    if "mode" in data:
        if data["mode"] not in ("remote", "local"):
            raise HTTPException(400, "mode: remote или local")
        config["mode"] = data["mode"]
    if data.get("node_name"):
        config["node_name"] = str(data["node_name"]).strip()[:40]
    if data.get("api_base"):
        config["api_base"] = str(data["api_base"]).strip().rstrip("/")
    save_config()
    return node_info()

@app.post("/api/node/reset-local")
def reset_local():
    global local_chain
    shutil.rmtree(local_chain.data_dir, ignore_errors=True)
    local_chain = Blockchain(os.path.join(DATA_DIR, "local")).initialize(wallet.address)
    return {"genesis": local_chain.chain[0]}

@app.get("/api/disk")
def disk_listing():
    files = []
    for root, _, names in os.walk(DATA_DIR):
        for name in sorted(names):
            if name.endswith(".tmp"):
                continue
            path = os.path.join(root, name)
            files.append({"path": os.path.relpath(path, DATA_DIR), "bytes": os.path.getsize(path)})
    target = local_chain if not is_remote() else mirror
    blocks = target.load_blocks()
    return {"data_dir": DATA_DIR, "files": sorted(files, key=lambda f: f["path"]),
            "blocks_read_from_disk": len(blocks),
            "transactions_on_disk": len(target.load_transactions())}

@app.get("/api/state")
def get_block_state():
    state = current_state()
    return {**state, "mempool": decorate_mempool(state), "quorum": QUORUM}

@app.get("/api/mempool")
def get_mempool():
    state = current_state()
    return {"source": state["source"], "error": state["error"], "quorum": QUORUM,
            "transactions": decorate_mempool(state)}

@app.get("/api/mempool/{tx_id}/verify")
def verify_from_mempool(tx_id: str):
    state = current_state()
    tx = next((t for t in state["mempool"] if t.get("tx_id") == tx_id), None)
    if tx is None:
        raise HTTPException(404, "Транзакция не найдена в мемпуле")
    return full_report(tx, state)

@app.post("/api/tx/verify")
def verify_any(tx: dict):
    return full_report(tx, current_state())

@app.post("/api/tx/submit")
def submit_signed(tx: dict):
    return submit_tx(tx)

def submit_tx(tx: dict) -> dict:
    if is_remote():
        state = current_state()
        report = full_report(tx, state)
        if not report["valid"]:
            failed = next(c for c in report["checks"] if c["status"] == "fail")
            raise HTTPException(400, f"{failed['name']}: {failed['detail']}")
        try:
            resp = requests.post(f"{config['api_base']}/api_tx.py", json=tx, timeout=TIMEOUT)
        except Exception as err:
            raise HTTPException(502, f"Сервер сети недоступен: {err}")
        return {"success": resp.ok, "tx": tx, "report": report, "server_response": response_json(resp)}
    try:
        report = local_chain.add_transaction(tx)
    except ValueError as err:
        raise HTTPException(400, str(err))
    report["checks"].append(contract_check(tx, local_chain.chain, local_chain.current_transactions))
    return {"success": True, "tx": tx, "report": report,
            "server_response": {"status": "saved", "file": os.path.relpath(local_chain.tx_file, DATA_DIR)}}

@app.get("/api/wallet")
def wallet_info():
    state = current_state()
    addr = wallet.address
    history = []
    for block in state["chain"]:
        for tx in block.get("transactions", []):
            b = tx.get("body", {})
            if addr in (b.get("sender_address"), b.get("recipient_address")):
                history.append({**tx, "status": "confirmed", "block_index": block.get("index")})
    for tx in state["mempool"]:
        b = tx.get("body", {})
        if addr in (b.get("sender_address"), b.get("recipient_address")):
            history.append({**tx, "status": "pending", "block_index": None})
    history.sort(key=lambda t: int(t["body"].get("timestamp", 0) or 0), reverse=True)
    balance = float(state["balances"].get(addr, 0))
    locked = pending_spent(state["mempool"]).get(addr, 0)
    return {**wallet.to_dict(), "balance": balance, "locked": round(locked, 8),
            "available": round(balance - locked, 8), "history": history,
            "source": state["source"], "error": state["error"]}

@app.post("/api/wallet/generate")
def wallet_generate(data: dict = None):
    global wallet
    wallet = Wallet.generate(login=(data or {}).get("login"))
    wallet.save(WALLET_FILE)
    return wallet.to_dict()

@app.post("/api/wallet/import")
def wallet_import(data: dict):
    global wallet
    try:
        wallet = Wallet.from_keys(data)
    except Exception as err:
        raise HTTPException(400, f"Не удалось загрузить ключи: {err}")
    wallet.save(WALLET_FILE)
    return wallet.to_dict()

@app.get("/api/wallet/export")
def wallet_export():
    return wallet.to_dict(include_private=True)

@app.post("/api/wallet/send")
def wallet_send(data: dict):
    recipient = str(data.get("recipient_address", "")).strip()
    item_id = str(data.get("item_id", "")).strip()
    action = str(data.get("action", "TRANSFER")).upper()
    if not recipient or not item_id:
        raise HTTPException(400, "Укажите адрес получателя и item_id")
    try:
        amount = float(data.get("amount"))
        fee = float(data.get("fee", DEFAULT_FEE))
    except (TypeError, ValueError):
        raise HTTPException(400, "amount и fee должны быть числами")
    tx = MyTx.create(wallet, recipient, item_id, action, amount, fee).to_dict()
    result = submit_tx(tx)
    if recipient[:1] in "13" and not b58check_is_valid(recipient):
        result["warning"] = "Адрес получателя похож на Bitcoin-адрес, но контрольная сумма не сходится"
    return result

@app.post("/api/vote")
def voiting(data: dict):
    tx_id = data.get("tx_id")
    node_name = (data.get("node_name") or config["node_name"]).strip()
    if not tx_id:
        raise HTTPException(400, "Нужен tx_id")
    if is_remote():
        try:
            resp = requests.post(f"{config['api_base']}/api_tx.py?action=vote",
                                 json={"tx_id": tx_id, "node_name": node_name}, timeout=TIMEOUT)
            return {"success": resp.ok, "server_response": response_json(resp)}
        except Exception as err:
            raise HTTPException(502, f"Сервер сети недоступен: {err}")
    try:
        votes = local_chain.vote(tx_id, node_name)
    except ValueError as err:
        raise HTTPException(400, str(err))
    return {"success": True, "votes": votes, "node_name": node_name}


@app.post("/api/mine")
def handle_mine(data: dict = None):
    data = data or {}
    tx_ids = data.get("tx_ids") or None
    miner_address = data.get("miner_address") or wallet.address
    if not is_remote():
        try:
            return {"success": True, "source": "local", **local_chain.mine_block(miner_address, tx_ids)}
        except ValueError as err:
            raise HTTPException(400, str(err))

    try:
        state = fetch_remote_state()
    except Exception as err:
        raise HTTPException(502, f"Сервер сети недоступен: {err}")
    ready = [t for t in state["mempool"] if len(state["votes"].get(t.get("tx_id"), [])) >= QUORUM]
    if tx_ids:
        ready = [t for t in ready if t.get("tx_id") in set(tx_ids)]
    accepted, rejected = select_valid(ready, state["balances"], chain_ids(state["chain"]))
    if not accepted:
        raise HTTPException(400, "Нет проверенных транзакций с кворумом голосов для блока")
    chain = state["chain"]
    prev_hash = chain[-1].get("hash", "0" * 64) if chain else "0" * 64
    index = len(chain)
    fees = sum(float(t["body"].get("fee", 0)) for t in accepted)
    block = MyBlock(index, prev_hash, [create_coinbase(miner_address, fees, index)] + accepted, DIFFICULTY)
    block.mine()
    payload = block.to_dict()
    try:
        resp = requests.post(f"{config['api_base']}/api_block.py", json=payload, timeout=TIMEOUT)
    except Exception as err:
        raise HTTPException(502, f"Блок смайнен, но сервер недоступен: {err}")
    return {"success": resp.ok, "source": "remote", "block": payload, "rejected": rejected,
            "attempts": block.attempts, "seconds": block.mining_seconds,
            "serv_responce": response_json(resp)}

@app.get("/api/chain")
def get_chain(from_disk: bool = False):
    target = mirror if is_remote() else local_chain
    if is_remote() and not from_disk:
        current_state()
    chain = target.load_blocks() if from_disk else target.chain
    return {"source": "disk" if from_disk else config["mode"], "chain": chain,
            "validation": target.validate_chain(chain)}

@app.get("/api/deals")
def get_deals():
    state = current_state()
    return {"deals": evaluate_deals(state["chain"], state["mempool"])}

if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="wallet")

uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))