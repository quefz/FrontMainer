def _side(tx: dict, confirmed: bool) -> dict:
    body = tx["body"]
    return {
        "tx_id": tx.get("tx_id"),
        "amount": float(body.get("amount", 0)),
        "timestamp": body.get("timestamp"),
        "confirmed": confirmed,
    }


def evaluate_deals(chain: list, mempool: list) -> list:
    deals = {}

    def feed(tx, confirmed):
        body = tx.get("body", {})
        action = str(body.get("action", "")).upper()
        if body.get("is_coinbase") or action not in ("BUY", "SELL"):
            return
        if action == "SELL":
            seller, buyer = body.get("sender_address"), body.get("recipient_address")
        else:
            buyer, seller = body.get("sender_address"), body.get("recipient_address")
        key = (seller, buyer, body.get("item_id"))
        deal = deals.setdefault(key, {"seller": seller, "buyer": buyer, "item_id": key[2],
                                      "sell": None, "buy": None})
        slot = "sell" if action == "SELL" else "buy"
        if deal[slot] is None or (confirmed and not deal[slot]["confirmed"]):
            deal[slot] = _side(tx, confirmed)

    for block in chain:
        for tx in block.get("transactions", []):
            feed(tx, True)
    for tx in mempool:
        feed(tx, False)

    result = []
    for deal in deals.values():
        sell, buy = deal["sell"], deal["buy"]
        if sell and buy and abs(sell["amount"] - buy["amount"]) > 1e-9:
            status = "price_mismatch"
        elif sell and buy and sell["confirmed"] and buy["confirmed"]:
            status = "completed"
        elif sell and buy:
            status = "pending"
        elif sell:
            status = "awaiting_payment"
        else:
            status = "awaiting_offer"
        deal["status"] = status
        result.append(deal)
    order = {"pending": 0, "awaiting_payment": 1, "awaiting_offer": 2, "price_mismatch": 3, "completed": 4}
    result.sort(key=lambda d: order[d["status"]])
    return result


def contract_check(tx: dict, chain: list, mempool: list) -> dict:
    body = tx.get("body", {})
    if str(body.get("action", "")).upper() != "BUY":
        return {"name": "Смарт-контракт", "status": "ok", "detail": "Не покупка — условие не требуется"}
    for deal in evaluate_deals(chain, [t for t in mempool if t.get("tx_id") != tx.get("tx_id")]):
        if (deal["seller"] == body.get("recipient_address") and deal["buyer"] == body.get("sender_address")
                and deal["item_id"] == body.get("item_id") and deal["sell"]):
            if abs(deal["sell"]["amount"] - float(body.get("amount", 0))) < 1e-9:
                return {"name": "Смарт-контракт", "status": "ok",
                        "detail": f"Есть предложение SELL на «{deal['item_id']}» по той же цене"}
            return {"name": "Смарт-контракт", "status": "warn",
                    "detail": f"Цена не совпадает с предложением продавца ({deal['sell']['amount']})"}
    return {"name": "Смарт-контракт", "status": "warn",
            "detail": "Встречного SELL от получателя нет — сделка не состоится, будет обычный перевод"}