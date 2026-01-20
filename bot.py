import os
import re
import requests
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

ENTER_CA_IMAGE_URL = ENTER_CA_IMAGE_URL = "https://raw.githubusercontent.com/edenalpha687/pumpfun-trending-bot/main/589CF67D-AF43-433F-A8AB-B43E9653E703.png"

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
def is_solana_address(addr: str) -> bool:
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", addr))


def fmt_usd(v):
    if not v:
        return "—"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"


def fetch_dex_data(ca: str):
    r = requests.get(f"{DEX_TOKEN_URL}{ca}", timeout=15)
    r.raise_for_status()
    pairs = r.json().get("pairs", [])
    if not pairs:
        return None

    pair = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))

    telegram_link = None
    for link in (pair.get("info") or {}).get("links", []):
        if link.get("type") == "telegram":
            telegram_link = link.get("url")

    return {
        "name": pair.get("baseToken", {}).get("name", "Unknown"),
        "symbol": pair.get("baseToken", {}).get("symbol", ""),
        "price": pair.get("priceUsd"),
        "liquidity": (pair.get("liquidity") or {}).get("usd"),
        "mcap": pair.get("fdv"),
        "pair_url": pair.get("url"),
        "logo": (pair.get("info") or {}).get("imageUrl"),
        "telegram": telegram_link,
    }


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

# ================= COMMANDS =================
def start(update: Update, context: CallbackContext):
    kb = [[InlineKeyboardButton("🚀 Start Trending", callback_data="START")]]
    update.message.reply_text(
        "🔥 Pump-Fun Trending\n\n"
        "Boost visibility for your token on PumpFun.\n"
        "Fast activation • Manual control • Real visibility",
        reply_markup=InlineKeyboardMarkup(kb),
    )


def buttons(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = q.from_user.id
    state = USER_STATE.get(uid)

    if q.data == "START":
        USER_STATE[uid] = {"step": "ASK_CA"}
        q.message.delete()
        context.bot.send_photo(
            chat_id=uid,
            photo=ENTER_CA_IMAGE_URL,
            caption="🟢 Please enter your token contract address (CA)",
        )

    elif q.data == "SHOW_PACKAGES":
        kb = [[InlineKeyboardButton(f"{k} — {v} SOL", callback_data=f"PKG_{k}")] for k, v in PACKAGES.items()]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="START")])
        q.message.delete()
        context.bot.send_message(
            chat_id=uid,
            text="Select trending duration:",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif q.data.startswith("PKG_"):
        pkg = q.data.replace("PKG_", "")
        state["package"] = pkg
        state["amount"] = PACKAGES[pkg]

        caption = (
            "🟢 Token Detected\n\n"
            f"Name: {state['name']}\n"
            f"💠 Symbol: {state['symbol']}\n"
            f"💵 Price: ${state['price']}\n"
            f"💧 Liquidity: {fmt_usd(state['liquidity'])}\n"
            f"📊 Market Cap: {fmt_usd(state['mcap'])}\n\n"
            f"⏱ Selected Package: {pkg}"
        )

        q.message.delete()
        context.bot.send_photo(
            chat_id=uid,
            photo=state["logo"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="PAY")],
                [InlineKeyboardButton("⬅️ Back", callback_data="SHOW_PACKAGES")],
            ]),
        )

    elif q.data == "PAY":
        state["step"] = "ASK_TXID"
        context.bot.send_message(
            chat_id=uid,
            text=(
                "Activation address\n\n"
                f"`{PAY_WALLET}`\n\n"
                "🛎️ Send TXID to confirm"
            ),
            parse_mode="Markdown",
        )

    elif q.data.startswith("ADMIN_START_") and uid == ADMIN_ID:
        ref = q.data.replace("ADMIN_START_", "")
        payload = context.bot_data.pop(ref, None)
        if not payload:
            return

        context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=(
                "🔥 Trending Live\n\n"
                f"{payload['name']} ({payload['symbol']})\n"
                f"CA: {payload['ca']}\n"
                f"Started: {datetime.utcnow().strftime('%H:%M UTC')}"
            ),
        )
        q.edit_message_text("Trending activated.")

# ================= TEXT =================
def messages(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    txt = update.message.text.strip()
    state = USER_STATE.get(uid)

    if not state:
        return

    # ---- CA INPUT ----
    if state["step"] == "ASK_CA":
        if not is_solana_address(txt):
            update.message.reply_text("Invalid CA. Please try again.")
            return

        data = fetch_dex_data(txt)
        if not data:
            update.message.reply_text("Token not found on Dexscreener.")
            return

        state.update(data)
        state["ca"] = txt
        state["step"] = "PREVIEW"

        name_line = (
            f'🔗 Name: <a href="{data["telegram"]}">{data["name"]}</a>'
            if data["telegram"]
            else f"Name: {data['name']}"
        )

        caption = (
            "🟢 Token Detected\n\n"
            f"{name_line}\n"
            f"💠 Symbol: {data['symbol']}\n"
            f'💵 Price: <a href="{data["pair_url"]}">${data["price"]}</a>\n'
            f"💧 Liquidity: {fmt_usd(data['liquidity'])}\n"
            f"📊 Market Cap: {fmt_usd(data['mcap'])}"
        )

        context.bot.send_photo(
            chat_id=uid,
            photo=data["logo"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="SHOW_PACKAGES")],
                [InlineKeyboardButton("⬅️ Back", callback_data="START")],
            ]),
        )

    # ---- TXID INPUT ----
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

        # SUCCESS
        USED_TXIDS.add(txt)
        ref = f"{uid}_{txt[-6:]}"
        context.bot_data[ref] = state.copy()

        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🛎️ Payment received\n"
                "Pending activation.\n\n"
                f"{state['name']} ({state['symbol']})\n"
                f"CA: {state['ca']}\n"
                f"Package: {state['package']}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ START TRENDING", callback_data=f"ADMIN_START_{ref}")]
            ]),
        )

        update.message.reply_text("🟢 Payment received.\nPending activation.")
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
    from web import start_web_server
    start_web_server()
    main()
