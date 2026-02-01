import os
import re
import time
import requests
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

WEBHOOK_BASE = "https://worker-production-56e9.up.railway.app"

ENTER_CA_IMAGE_URL = "https://raw.githubusercontent.com/edenalpha687/pumpfun-trending-bot/main/589CF67D-AF43-433F-A8AB-B43E9653E703.png"

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/"
HELIUS_TX_URL = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"

PACKAGES = {
    "3H": 2.10,
    "6H": 3.10,
    "12H": 4.90,
    "24H": 7.90,
}

USER_STATE = {}
USED_TXIDS = set()

# ================= HELPERS =================
def is_solana_address(addr):
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", addr))


def fmt_usd(v):
    if not v:
        return "—"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"


def fetch_dex_data(ca):
    r = requests.get(f"{DEX_TOKEN_URL}{ca}", timeout=15)
    r.raise_for_status()
    pairs = r.json().get("pairs", [])
    if not pairs:
        return None

    pair = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))

    telegram_link = None
    for l in (pair.get("info") or {}).get("links", []):
        if l.get("type") == "telegram":
            telegram_link = l.get("url")

    return {
        "name": pair["baseToken"]["name"],
        "symbol": pair["baseToken"]["symbol"],
        "price": pair.get("priceUsd"),
        "liquidity": (pair.get("liquidity") or {}).get("usd"),
        "mcap": pair.get("fdv"),
        "pair_url": pair.get("url"),
        "logo": (pair.get("info") or {}).get("imageUrl"),
        "telegram": telegram_link,
    }


def verify_txid(txid):
    try:
        r = requests.get(
            f"{HELIUS_TX_URL}&transactionHashes[]={txid}",
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return bool(data)
    except Exception:
        return False


def activate_trending(payload):
    requests.post(
        f"{WEBHOOK_BASE}/activate",
        json={
            "mint": payload["ca"],
            "name": payload["name"],
            "price": payload["price"],
            "mcap": payload["mcap"],
            "logo": payload["logo"],
            "dex": payload["pair_url"],
        },
        timeout=10,
    )

# ================= START =================
def start(update: Update, context: CallbackContext):
    kb = [[InlineKeyboardButton("🔥 Start Trending", callback_data="START")]]
    update.message.reply_text(
        "🔥 Pump-Fun Trending\n\n"
        "Boost visibility for your token.\n"
        "Fast activation • Manual control • Real visibility",
        reply_markup=InlineKeyboardMarkup(kb),
    )

# ================= BUTTONS =================
def buttons(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = q.from_user.id
    state = USER_STATE.get(uid)

    if q.data == "START":
        USER_STATE[uid] = {"step": "CA"}
        q.message.delete()
        sent = context.bot.send_photo(
            chat_id=uid,
            photo=ENTER_CA_IMAGE_URL,
            caption="🟢 Please enter your token contract address (CA)",
        )
        USER_STATE[uid]["prompt_msg_id"] = sent.message_id

    elif q.data == "PACKAGES":
        kb = [[InlineKeyboardButton(f"{k} — {v} SOL", callback_data=f"PKG_{k}")]
              for k, v in PACKAGES.items()]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="START")])
        q.message.delete()
        context.bot.send_message(chat_id=uid, text="Select trending duration:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("PKG_"):
        pkg = q.data.replace("PKG_", "")
        state["package"] = pkg
        state["amount"] = PACKAGES[pkg]

        q.message.delete()
        context.bot.send_photo(
            chat_id=uid,
            photo=state["logo"],
            caption=(
                "🟢 Token Detected\n\n"
                f"{state['name']} ({state['symbol']})\n"
                f"Liquidity: {fmt_usd(state['liquidity'])}\n"
                f"Market Cap: {fmt_usd(state['mcap'])}\n\n"
                f"⏱ Package: {pkg}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="PAY")],
            ]),
        )

    elif q.data == "PAY":
        state["step"] = "TXID"
        context.bot.send_message(
            chat_id=uid,
            text=f"Send payment to:\n\n`{PAY_WALLET}`\n\nThen send TXID.",
            parse_mode="Markdown",
        )

    elif q.data.startswith("ADMIN_START_") and uid == ADMIN_ID:
        ref = q.data.replace("ADMIN_START_", "")
        payload = context.bot_data.pop(ref, None)
        if not payload:
            return

        activate_trending(payload)

        context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=(
                "🔥 Trending Live\n\n"
                f"{payload['name']} ({payload['symbol']})\n"
                f"CA: {payload['ca']}\n"
                f"Started: {datetime.utcnow().strftime('%H:%M UTC')}"
            ),
        )

        q.edit_message_text("✅ Trending activated.")

# ================= TEXT =================
def messages(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    txt = update.message.text.strip()
    state = USER_STATE.get(uid)

    if not state:
        return

    if state["step"] == "CA":
        if not is_solana_address(txt):
            update.message.reply_text("Invalid CA.")
            return

        data = fetch_dex_data(txt)
        if not data:
            update.message.reply_text("Token not found.")
            return

        state.update(data)
        state["ca"] = txt
        state["step"] = "PREVIEW"

        context.bot.send_photo(
            chat_id=uid,
            photo=data["logo"],
            caption=f"🟢 {data['name']} ({data['symbol']})",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data="PACKAGES")]]),
        )

    elif state["step"] == "TXID":
        if txt in USED_TXIDS:
            update.message.reply_text("TXID already used.")
            return

        update.message.reply_text("🔍 Verifying transaction...")

        if not verify_txid(txt):
            update.message.reply_text("❌ Invalid TXID.")
            return

        USED_TXIDS.add(txt)

        ref = f"{uid}_{txt[-6:]}"
        context.bot_data[ref] = state.copy()

        # USER RECEIPT
        update.message.reply_text(
            "🟢 Payment Confirmed\n\n"
            "🧾 Trending Receipt\n"
            f"Token: {state['name']} ({state['symbol']})\n"
            f"Package: {state['package']}\n"
            f"Amount: {state['amount']} SOL\n"
            "Status: Pending activation"
        )

        # ADMIN NOTIFY
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🛎️ Payment received\n\n"
                f"{state['name']} ({state['symbol']})\n"
                f"CA: {state['ca']}\n"
                f"Package: {state['package']}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ START TRENDING", callback_data=f"ADMIN_START_{ref}")]
            ]),
        )

        USER_STATE.pop(uid, None)

# ================= MAIN =================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(buttons))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, messages))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
