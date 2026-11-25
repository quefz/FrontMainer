import hashlib
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import uvicorn  
from fastapi import FastAPI, Request  

from block import MyTx  

app = FastAPI()
state = {"chain": [], "mempool": [], "votes": {}, "balances": {}}
START_BALANCE = 100.0


def balance(addr):
    return state["balances"].setdefault(addr, START_BALANCE)


@app.post("/cgi-bin/api_auth.py")
async def api_auth(request: Request):
    data = await request.json()
    return {"status": "ok", "balance": balance(data["address"])}


@app.get("/cgi-bin/api_state.py")
def api_state():
    return state


@app.post("/cgi-bin/api_tx.py")
async def api_tx(request: Request, action: str = None):
    data = await request.json()
    if action == "vote":
        voters = state["votes"].setdefault(data["tx_id"], [])
        if data["node_name"] not in voters:
            voters.append(data["node_name"])
        return {"status": "ok", "votes": len(voters)}
    tx = MyTx(data)
    if not tx.verify_signature():
        return {"status": "error", "message": "bad signature"}
    balance(tx.body["sender_address"])
    balance(tx.body["recipient_address"])
    state["mempool"].append(data)
    return {"status": "ok", "tx_id": tx.tx_id}


@app.post("/cgi-bin/api_block.py")
async def api_block(request: Request):
    block = await request.json()
    data = dict(block)
    h = data.pop("hash")
    if hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() != h or not h.startswith("000"):
        return {"status": "error", "message": "bad hash"}
    prev = state["chain"][-1]["hash"] if state["chain"] else "0" * 64
    if block["prev_hash"] != prev:
        return {"status": "error", "message": "bad prev_hash"}
    state["chain"].append(block)
    ids = {t["tx_id"] for t in block["transactions"]}
    state["mempool"] = [t for t in state["mempool"] if t["tx_id"] not in ids]
    for t in block["transactions"]:
        b = t["body"]
        if b.get("is_coinbase"):
            state["balances"][b["recipient_address"]] = balance(b["recipient_address"]) + b["amount"]
        else:
            state["balances"][b["sender_address"]] = balance(b["sender_address"]) - b["amount"] - b["fee"]
            state["balances"][b["recipient_address"]] = balance(b["recipient_address"]) + b["amount"]
    return {"status": "ok", "height": len(state["chain"])}


uvicorn.run(app, host="127.0.0.1", port=8099)