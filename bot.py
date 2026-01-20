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
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    CallbackContext,
)

# ================== ENV VARIABLES ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

HELIUS_URL = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"

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


def verify_txid(txid: str, amount_expected: float) -> bool:
    try:
        r = requests.get(f"{HELIUS_URL}&transactionHashes[]={txid}", timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return False

        tx = data[0]
        for t in tx.get("nativeTransfers", []):
            if t.get("toUserAccount") == PAY_WALLET:
                sol = t.get("amount", 0) / 1_000_000_000
                if sol >= amount_expected:
                    return True
        return False
    except Exception:
        return False

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("🔥 TRENDING", callback_data="TRENDING")]]
    update.message.reply_text(
        "🚀 PumpFun Trending Bot\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    if query.data == "TRENDING":
        query.edit_message_text(
            "Select chain:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🟢 PumpFun", callback_data="PUMPFUN")]]
            ),
        )

    elif query.data == "PUMPFUN":
        USER_STATE[user_id] = {"step": "ASK_CA"}
        query.edit_message_text("Please enter your **Solana CA**:")

    elif query.data == "CONFIRM_CA":
        keyboard = [
            [InlineKeyboardButton("⏱ 3h — 2.10 SOL", callback_data="PKG_3h")],
            [InlineKeyboardButton("⏱ 6h — 3.10 SOL", callback_data="PKG_6h")],
            [InlineKeyboardButton("⏱ 12h — 4.90 SOL", callback_data="PKG_12h")],
            [InlineKeyboardButton("⏱ 24h — 7.90 SOL", callback_data="PKG_24h")],
        ]
        query.edit_message_text(
            "Choose a package:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("PKG_"):
        pkg = query.data.replace("PKG_", "")
        USER_STATE[user_id]["package"] = pkg
        USER_STATE[user_id]["amount"] = PACKAGES[pkg]
        USER_STATE[user_id]["step"] = "ASK_TXID"

        query.edit_message_text(
            f"💳 **Payment Required**\n\n"
            f"Send **{PACKAGES[pkg]} SOL** to:\n"
            f"`{PAY_WALLET}`\n\n"
            f"Then paste your **TXID**."
        )

    elif query.data.startswith("ADMIN_START_"):
        if user_id != ADMIN_ID:
            return

        ref = query.data.replace("ADMIN_START_", "")
        data = context.bot_data.get(ref)
        if not data:
            query.edit_message_text("❌ Already started or expired.")
            return

        text = (
            "🔥 **TRENDING LIVE**\n\n"
            f"🟢 CA: `{data['ca']}`\n"
            f"🕒 Started: {datetime.utcnow().strftime('%H:%M UTC')}\n"
            f"📈 PumpFun SOL"
        )

        context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=text,
            disable_web_page_preview=True,
        )

        del context.bot_data[ref]
        query.edit_message_text("✅ Trending started.")

# ================== MESSAGES ==================
def message_handler(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    state = USER_STATE.get(user_id)
    if not state:
        return

    if state["step"] == "ASK_CA":
        if not is_solana_address(text):
            update.message.reply_text("❌ Invalid CA. Send a valid Solana address.")
            return

        state["ca"] = text
        state["step"] = "CONFIRM"

        update.message.reply_text(
            f"🟢 **Confirm Token**\n\nCA:\n`{text}`",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ Confirm", callback_data="CONFIRM_CA")]]
            ),
        )

    elif state["step"] == "ASK_TXID":
        if text in USED_TXIDS:
            update.message.reply_text("❌ TXID already used.")
            return

        if not verify_txid(text, state["amount"]):
            update.message.reply_text("❌ TXID not valid yet. Try again.")
            return

        USED_TXIDS.add(text)
        ref = f"{user_id}_{text[-6:]}"

        context.bot_data[ref] = {
            "ca": state["ca"],
            "package": state["package"],
        }

        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🔥 **PAYMENT VERIFIED**\n\n"
                f"CA: `{state['ca']}`\n"
                f"Package: {state['package']}\n"
                f"TXID: `{text}`"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("▶️ START TRENDING", callback_data=f"ADMIN_START_{ref}")]]
            ),
        )

        update.message.reply_text("✅ Payment verified. Trending will begin shortly.")
        USER_STATE.pop(user_id, None)

# ================== MAIN ==================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
