import os
import time
import requests
from fastapi import FastAPI, Request
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import uvicorn

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
MIN_BUY_SOL = float(os.getenv("MIN_BUY_SOL", 0.5))
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 60))

bot = Bot(BOT_TOKEN)
app = FastAPI()

# ===== STATE (IN-MEMORY) =====
ACTIVE_TRENDING = {}     # mint -> token data
LAST_POST_TIME = {}     # mint -> timestamp


# ===== HEALTH CHECK =====
@app.get("/")
def health():
    return {"status": "ok"}


# ===== REGISTER TRENDING TOKEN (CALLED BY BOT) =====
@app.post("/activate")
async def activate(req: Request):
    data = await req.json()
    mint = data["mint"]

    ACTIVE_TRENDING[mint] = data
    LAST_POST_TIME[mint] = 0

    return {"activated": True}


# ===== HELIUS WEBHOOK =====
@app.post("/helius-webhook")
async def helius_webhook(req: Request):
    payload = await req.json()

    for tx in payload:
        native_transfers = tx.get("nativeTransfers", [])
        token_transfers = tx.get("tokenTransfers", [])

        if not native_transfers or not token_transfers:
            continue

        mint = token_transfers[0].get("mint")
        if mint not in ACTIVE_TRENDING:
            continue

        # SOL amount
        lamports = native_transfers[0].get("amount", 0)
        sol = lamports / 1_000_000_000
        if sol < MIN_BUY_SOL:
            continue

        now = time.time()
        if now - LAST_POST_TIME.get(mint, 0) < RATE_LIMIT_SECONDS:
            continue

        LAST_POST_TIME[mint] = now
        token = ACTIVE_TRENDING[mint]

        caption = (
            f"🟢 BUY — {sol:.2f} SOL\n\n"
            f"Token: {token['name']}\n"
            f"Price: ${token['price']}\n"
            f"Market Cap: {token['mcap']}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Dexscreener", url=token["dex"])]
        ])

        bot.send_photo(
            chat_id=CHANNEL_USERNAME,
            photo=token["logo"],
            caption=caption,
            reply_markup=keyboard
        )

    return {"ok": True}


# ===== START SERVER =====
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
