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

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PAY_WALLET = os.getenv("PAY_WALLET")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

HELIUS_TX_URL = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
HELIUS_META_URL = f"https://api.helius.xyz/v0/token-metadata?api-key={HELIUS_API_KEY}"

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


def ipfs_to_https(uri: str) -> str:
    if uri.startswith("ipfs://"):
        return uri.replace("ipfs://", "https://ipfs.io/ipfs/")
    return uri


def fetch_token_metadata(ca: str):
    try:
        r = requests.post(
            HELIUS_META_URL,
            json={"mintAccounts": [ca]},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None

        token = data[0]
        name = token.get("name")
        symbol = token.get("symbol")
        logo = token.get("logoURI")

        if logo:
            logo = ipfs_to_https(logo)

        return {
            "name": name,
            "symbol": symbol,
            "logo": logo,
        }
    except Exception:
        return None


def verify_txid(txid: str, expected_amount: float) -> bool:
    try:
        r = requests.get(
            f"{HELIUS_TX_URL}&transactionHashes[]={txid}",
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return False

        tx = data[0]
        for t in tx.get("nativeTransfers", []):
            if t.get("toUserAccount") == PAY_WALLET:
                sol = t.get("amount", 0) / 1_000_000_000
                if sol >= expected_amount:
                    return True
        return False
    except Exception:
        return False

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("🔥 Trending", callback_data="TRENDING")]]
    update.message.reply_text(
        "PumpFun Trending\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
                [[InlineKeyboardButton("PumpFun", callback_data="PUMPFUN")]]
            ),
        )

    elif q.data == "PUMPFUN":
        USER_STATE[uid] = {"step": "ASK_CA"}
        q.edit_message_text("Please enter your token CA:")

    elif q.data == "BACK_TO_CHAIN":
        q.edit_message_text(
            "Select chain:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("PumpFun", callback_data="PUMPFUN")]]
            ),
        )

    elif q.data == "CONFIRM_CA":
        keyboard = [
            [InlineKeyboardButton("3h — 2.10 SOL", callback_data="PKG_3h")],
            [InlineKeyboardButton("6h — 3.10 SOL", callback_data="PKG_6h")],
            [InlineKeyboardButton("12h — 4.90 SOL", callback_data="PKG_12h")],
            [InlineKeyboardButton("24h — 7.90 SOL", callback_data="PKG_24h")],
            [InlineKeyboardButton("⬅️ Back", callback_data="BACK_TO_CHAIN")],
        ]
        q.edit_message_text(
            "Select trending duration:",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="CONFIRM_CA")]]
            ),
            parse_mode="Markdown",
        )

    elif q.data.startswith("ADMIN_START_"):
        if uid != ADMIN_ID:
            return

        ref = q.data.replace("ADMIN_START_", "")
        payload = context.bot_data.get(ref)
        if not payload:
            q.edit_message_text("Already activated.")
            return

        text = (
            "Trending Live\n\n"
            f"Token: {payload['name']} ({payload['symbol']})\n"
            f"CA: {payload['ca']}\n"
            f"Started: {datetime.utcnow().strftime('%H:%M UTC')}"
        )

        context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=text,
            disable_web_page_preview=True,
        )

        del context.bot_data[ref]
        q.edit_message_text("Trending activated.")

# ================== TEXT HANDLER ==================
def messages(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    txt = update.message.text.strip()
    state = USER_STATE.get(uid)

    if not state:
        return

    if state["step"] == "ASK_CA":
        if not is_solana_address(txt):
            update.message.reply_text("Invalid CA. Please try again.")
            return

        meta = fetch_token_metadata(txt)
        if not meta:
            update.message.reply_text("Unable to fetch token details.")
            return

        state.update(meta)
        state["ca"] = txt
        state["step"] = "CONFIRM"

        caption = (
            f"Token detected\n\n"
            f"Name: {meta['name']}\n"
            f"Symbol: {meta['symbol']}\n"
            f"Chain: Solana"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm", callback_data="CONFIRM_CA")],
            [InlineKeyboardButton("⬅️ Back", callback_data="BACK_TO_CHAIN")],
        ])

        if meta.get("logo"):
            context.bot.send_photo(
                chat_id=uid,
                photo=meta["logo"],
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            update.message.reply_text(caption, reply_markup=keyboard)

    elif state["step"] == "ASK_TXID":
        if txt in USED_TXIDS:
            update.message.reply_text("TXID already used.")
            return

        if not verify_txid(txt, state["amount"]):
            update.message.reply_text("Invalid TXID. Please try again.")
            return

        USED_TXIDS.add(txt)
        ref = f"{uid}_{txt[-6:]}"

        context.bot_data[ref] = {
            "ca": state["ca"],
            "name": state["name"],
            "symbol": state["symbol"],
        }

        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "Payment received.\n"
                "Pending activation.\n\n"
                f"Token: {state['name']} ({state['symbol']})\n"
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
