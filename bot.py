import os
import re
import requests
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@PumpTrendingTracker")

HELIUS_TX_URL = "https://api.helius.xyz/v0/transactions/?api-key=" + HELIUS_API_KEY

# ================== IN-MEMORY STATE (MVP) ==================
USER_STATE = {}   # user_id -> dict
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

def verify_txid(txid: str, expected_amount: float) -> bool:
    try:
        r = requests.get(HELIUS_TX_URL + f"&transactionHashes[]={txid}", timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            return False

        tx = data[0]
        if tx.get("nativeTransfers"):
            for t in tx["nativeTransfers"]:
                if t.get("toUserAccount") == PAY_WALLET:
                    lamports = t.get("amount", 0)
                    sol = lamports / 1_000_000_000
                    if sol + 1e-9 >= expected_amount:
                        return True
        return False
    except Exception:
        return False

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 TRENDING", callback_data="TRENDING")]
    ])
    await update.message.reply_text(
        "🚀 Pump-style Trending\n\nChoose an option:",
        reply_markup=kb
    )

async def on_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "TRENDING":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 PumpFun", callback_data="PUMPFUN")]
        ])
        await q.edit_message_text("Select chain:", reply_markup=kb)

    elif q.data == "PUMPFUN":
        USER_STATE[uid] = {"step": "ASK_CA"}
        await q.edit_message_text("Please enter your **CA (Solana)**:")

    elif q.data.startswith("CONFIRM_CA"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱ 3h — 2.10 SOL", callback_data="PKG_3h")],
            [InlineKeyboardButton("⏱ 6h — 3.10 SOL", callback_data="PKG_6h")],
            [InlineKeyboardButton("⏱ 12h — 4.90 SOL", callback_data="PKG_12h")],
            [InlineKeyboardButton("⏱ 24h — 7.90 SOL", callback_data="PKG_24h")],
        ])
        await q.edit_message_text("Choose a package:", reply_markup=kb)

    elif q.data.startswith("PKG_"):
        pkg = q.data.replace("PKG_", "")
        USER_STATE[uid]["package"] = pkg
        USER_STATE[uid]["amount"] = PACKAGES[pkg]
        await q.edit_message_text(
            f"💳 **Payment Required**\n\n"
            f"Send **{PACKAGES[pkg]} SOL** to:\n`{PAY_WALLET}`\n\n"
            f"Then paste your **TXID** below."
        )
        USER_STATE[uid]["step"] = "ASK_TXID"

    elif q.data.startswith("ADMIN_START_"):
        if uid != ADMIN_ID:
            return
        ref = q.data.replace("ADMIN_START_", "")
        payload = context.bot_data.get(ref)
        if not payload:
            await q.edit_message_text("❌ Already started or expired.")
            return

        text = (
            "🔥 **TRENDING**\n\n"
            f"🟢 Token: {payload['ca']}\n"
            f"🟢 Chain: SOL\n"
            f"🟢 Package: {payload['package']}\n"
            f"🕒 Started: {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
            "📈 Visibility live."
        )
        await context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=text,
            disable_web_page_preview=True
        )
        del context.bot_data[ref]
        await q.edit_message_text("✅ Trending started.")

# ================== MESSAGES ==================
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    txt = update.message.text.strip()

    st = USER_STATE.get(uid, {})
    step = st.get("step")

    if step == "ASK_CA":
        if not is_solana_address(txt):
            await update.message.reply_text("❌ Invalid CA. Please send a valid Solana address.")
            return
        st["ca"] = txt
        st["step"] = "CONFIRM"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="CONFIRM_CA")]
        ])
        await update.message.reply_text(
            f"🟢 **Token Preview**\n\nCA:\n`{txt}`\n\nConfirm?",
            reply_markup=kb
        )

    elif step == "ASK_TXID":
        if txt in USED_TXIDS:
            await update.message.reply_text("❌ TXID already used.")
            return
        amount = st.get("amount")
        if not verify_txid(txt, amount):
            await update.message.reply_text("❌ TXID not valid yet. Please check and try again.")
            return

        USED_TXIDS.add(txt)
        ref = f"{uid}_{txt[-6:]}"
        context.bot_data[ref] = {
            "user": uid,
            "ca": st.get("ca"),
            "package": st.get("package"),
        }

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ START TRENDING", callback_data=f"ADMIN_START_{ref}")]
        ])

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🔥 **PAYMENT VERIFIED**\n\n"
                f"CA: `{st.get('ca')}`\n"
                f"Package: {st.get('package')}\n"
                f"Amount: {st.get('amount')} SOL\n"
                f"TXID: `{txt}`"
            ),
            reply_markup=kb
        )

        await update.message.reply_text("✅ Payment verified. Trending will begin shortly.")
        USER_STATE.pop(uid, None)

# ================== MAIN ==================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()

if __name__ == "__main__":
    main()
