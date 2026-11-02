from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import uvicorn
from block import mine

app = FastAPI(title="Полный узел")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_origins=["*"],
    allow_headers=["*"],
)

API_BASE = "http://prima-412.ru/cgi-bin"

@app.get("/api/state")
def get_block_state():
    try:
        return requests.get(f"{API_BASE}/api_state.py").json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/vote")
def voiting(data: dict):
    tx_id = data.get("tx_id")
    node_name = data.get("node_name")
    try:
        return requests.post(
            f"{API_BASE}/api_tx.py?action=vote",
            json = {"tx_id": tx_id, "node_name": node_name}
        ).json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mine")
def handle_mine(data: dict):
    ready_txs = data.get("ready_txs", [])
    miner_address = data.get("miner_address", "DEFAULT_MINER_ADDRESS")
    prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    try:
        chain = requests.get(f"{API_BASE}/api_state.py").json().get("chain", [])
        if chain:
            prev_hash = chain[-1].get("hash", prev_hash) 
    except Exception as e:
        pass
    try:
        block_payload = mine(ready_txs, miner_address, prev_hash)
        serv_responce = requests.post(f"{API_BASE}/api_block.py", json=block_payload)
        return {
            "success": True,
            "block": block_payload,
            "serv_responce": serv_responce.json(
            )
        }
    except ValueError as v:
        raise HTTPException(status_code=400, detail=str(v))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

uvicorn.run(app, host="127.0.0.1", port=8000)