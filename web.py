import time
import threading
from fastapi import FastAPI, Request
import uvicorn

# This dict will be shared in-memory
ACTIVE_TRENDING = {}
LAST_BUY_POST = {}

app = FastAPI()

# ===== CONFIG (SAFE DEFAULTS) =====
MIN_BUY_SOL = 0.5
RATE_LIMIT_SECONDS = 60

# ===== UTIL =====
def sol_from_lamports(lamports):
    return lamports / 1_000_000_000


# ===== WEBHOOK ENDPOINT =====
@app.post("/helius-webhook")
async def helius_webhook(req: Request):
    payload = await req.json()

    for tx in payload:
        transfers = tx.get("nativeTransfers", [])
        token_transfers = tx.get("tokenTransfers", [])

        if not transfers or not token_transfers:
            continue

        for t in transfers:
            sol_amount = sol_from_lamports(t.get("amount", 0))
            if sol_amount < MIN_BUY_SOL:
                continue

            mint = token_transfers[0].get("mint")
            if mint not in ACTIVE_TRENDING:
                continue

            now = time.time()
            last = LAST_BUY_POST.get(mint, 0)
            if now - last < RATE_LIMIT_SECONDS:
                continue

            LAST_BUY_POST[mint] = now

            data = ACTIVE_TRENDING[mint]
            bot = data["bot"]

            bot.send_photo(
                chat_id=data["channel"],
                photo=data["logo"],
                caption=(
                    f"🟢 BUY — {sol_amount:.2f} SOL\n\n"
                    f"Token: {data['name']}\n"
                    f"Price: ${data['price']}\n"
                    f"Market Cap: {data['mcap']}"
                ),
                reply_markup=data["keyboard"]
            )

    return {"status": "ok"}


# ===== START SERVER =====
def start_web_server():
    def run():
        uvicorn.run(app, host="0.0.0.0", port=8000)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if __name__ == "__main__":
    start_web_server()

    # Start Telegram bot AFTER web server
    import bot
    bot.main()

    while True:
        time.sleep(60)
