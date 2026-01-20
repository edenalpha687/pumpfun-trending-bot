import os
import re
import time
import requests
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

HELIUS_TX_URL = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/"

# ================== STATE ==================
USER_STATE = {}
USED_TXIDS = set()

PACKAGES = {
    "3h": 2.10,
    "6h": 3.10,
    "12h": 4.90,
    "24h": 7.90,
}

# ================== HELPERS ==================
def is_solana_address(addr: str) -> bool:
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", addr))


def fetch_dexscreener_data(ca: str):
    try:
        r = requests.get(f"{DEX_URL}{ca}", timeout=15)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None

        # pick highest liquidity pair
        pair = max(
            pairs,
            key=lambda p: (p.get("liquidity", {}) or {}).get("usd", 0)
        )

        return {
            "name": pair.get("baseToken", {}).get("name", "Unknown"),
            "symbol": pair.get("baseToken", {}).get("symbol", ""),
            "price": pair.get("priceUsd"),
            "liquidity": (pair.get("liquidity") or {}).get("usd"),
            "mcap": pair.get("fdv"),
            "logo": pair.get("info", {}).get("imageUrl"),
        }
    except Exception:
        return None


def verify_txid(txid: str, expected_amount: float):
    try:
        r = requests.get(
            f"{HELIUS_TX_URL}&transactionHashes[]={txid}",
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return "PENDING"

        tx = data[0]
        for t in tx.get("nativeTransfers", []):
            if t.get("toUserAccount") == PAY_WALLET:
                sol = t.get("amount", 0) / 1_000_000_000
                if sol >= expected_amount:
                    return "OK"
        return "INVALID"
    except Exception:
        return "PENDING"


def fmt_usd(v):
    if not v:
        return "—"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    kb = [[InlineKeyboardButton("🔥 Trending", callback_data="TRENDING")]]
    update.message.reply_text(
        "PumpFun Trending\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(kb),
    )


def buttons(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = q.from_user.id
    state = USER_STATE.get(uid, {})

    if q.data == "TRENDING":
        q.edit_message_text(
            "Select chain:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🟢 PumpFun", callback_data="PUMPFUN")]]
            ),
        )

    elif q.data == "PUMPFUN":
        USER_STATE[uid] = {"step": "ASK_CA"}
        q.edit_message_text("Please enter token CA:")

    elif q.data == "BACK_TO_CHAIN":
        q.edit_message_text(
            "Select chain:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🟢 PumpFun", callback_data="PUMPFUN")]]
            ),
        )

    elif q.data == "CONFIRM_CA":
        kb = [
            [InlineKeyboardButton("3h — 2.10 SOL", callback_data="PKG_3h")],
            [InlineKeyboardButton("6h — 3.10 SOL", callback_data="PKG_6h")],
            [InlineKeyboardButton("12h — 4.90 SOL", callback_data="PKG_12h")],
            [InlineKeyboardButton("24h — 7.90 SOL", callback_data="PKG_24h")],
            [InlineKeyboardButton("⬅️ Back", callback_data="BACK_TO_CHAIN")],
        ]
        q.edit_message_text(
            "Select trending duration:",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif q.data.startswith("PKG_"):
        pkg = q.data.replace("PKG_", "")
        state["package"] = pkg
        state["amount"] = PACKAGES[pkg]
        state["step"] = "ASK_TXID"

        q.edit_message_text(
            f"Activation address\n\n"
            f"`{PAY_WALLET}`\n\n"
            f"🛎️ Send TXID to confirm",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="CONFIRM_CA")]]
            ),
        )

    elif q.data.startswith("ADMIN_START_"):
        if uid != ADMIN_ID:
            return

        ref = q.data.replace("ADMIN_START_", "")
        payload = context.bot_data.get(ref)
        if not payload:
            q.edit_message_text("Already activated.")
            return

        msg = (
            "🔥 Trending Live\n\n"
            f"{payload['name']} ({payload['symbol']})\n"
            f"CA: {payload['ca']}\n"
            f"Started: {datetime.utcnow().strftime('%H:%M UTC')}"
        )

        context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=msg,
            disable_web_page_preview=True,
        )

        del context.bot_data[ref]
        q.edit_message_text("Trending activated.")

# ================== TEXT ==================
def messages(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    txt = update.message.text.strip()
    state = USER_STATE.get(uid)

    if not state:
        return

    if state["step"] == "ASK_CA":
        if not is_solana_address(txt):
            update.message.reply_text("Invalid CA. Try again.")
            return

        data = fetch_dexscreener_data(txt)
        if not data:
            update.message.reply_text("Token not found on Dexscreener.")
            return

        state.update(data)
        state["ca"] = txt
        state["step"] = "CONFIRM"

        caption = (
            "🟢 Token detected\n\n"
            f"Name: {data['name']}\n"
            f"Symbol: {data['symbol']}\n"
            f"Price: ${data['price']}\n"
            f"Liquidity: {fmt_usd(data['liquidity'])}\n"
            f"Market Cap: {fmt_usd(data['mcap'])}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="CONFIRM_CA")],
            [InlineKeyboardButton("⬅️ Back", callback_data="BACK_TO_CHAIN")],
        ])

        if data.get("logo"):
            context.bot.send_photo(
                chat_id=uid,
                photo=data["logo"],
                caption=caption,
                reply_markup=kb,
            )
        else:
            update.message.reply_text(caption, reply_markup=kb)

    elif state["step"] == "ASK_TXID":
        if txt in USED_TXIDS:
            update.message.reply_text("TXID already used.")
            return

        res = verify_txid(txt, state["amount"])
        if res == "PENDING":
            update.message.reply_text(
                "Transaction not indexed yet.\n"
                "Please wait 30 seconds and resend TXID."
            )
            return
        if res == "INVALID":
            update.message.reply_text("Invalid TXID. Please try again.")
            return

        USED_TXIDS.add(txt)
        ref = f"{uid}_{txt[-6:]}"
        context.bot_data[ref] = state.copy()

        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🛎️ Payment received\n"
                "Pending activation.\n\n"
                f"{state['name']} ({state['symbol']})\n"
                f"CA: {state['ca']}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ START TRENDING", callback_data=f"ADMIN_START_{ref}")]
            ]),
        )

        update.message.reply_text("Payment received.\nPending activation.")
        USER_STATE.pop(uid, None)

# ================== MAIN ==================
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
