from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import subprocess
from database import get_connection
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def run_command(command):
    try:
        result = subprocess.getoutput(command)
        return result[-3000:]
    except Exception as e:
        return str(e)


# =========================
# PostgreSQL Functions
# =========================

def get_bot_status():
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT status, message
            FROM bot_status
            ORDER BY id DESC
            LIMIT 1
        """)

        result = cur.fetchone()

        cur.close()
        conn.close()

        return result

    except Exception as e:
        print("STATUS ERROR:", e)
        return None


def get_latest_balance():
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT asset, balance
            FROM balance_history
            ORDER BY id DESC
            LIMIT 1
        """)

        result = cur.fetchone()

        cur.close()
        conn.close()

        return result

    except Exception as e:
        print("BALANCE ERROR:", e)
        return None


def get_open_trades():
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT symbol, side, entry_price, quantity
            FROM trades
            WHERE status='OPEN'
            ORDER BY id DESC
        """)

        result = cur.fetchall()

        cur.close()
        conn.close()

        return result

    except Exception as e:
        print("TRADE ERROR:", e)
        return []

def get_trade_history():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT symbol, side, entry_price, exit_price, profit, status, created_at
        FROM trades
        ORDER BY id DESC
        LIMIT 20
    """)

    data = cur.fetchall()

    cur.close()
    conn.close()

    return data


def get_logs():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT level, message
        FROM logs
        ORDER BY id DESC
        LIMIT 20
    """)

    data = cur.fetchall()

    cur.close()
    conn.close()

    return data


def get_errors():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT message
        FROM errors
        ORDER BY id DESC
        LIMIT 20
    """)

    data = cur.fetchall()

    cur.close()
    conn.close()

    return data


def get_balance_history():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT asset, balance
        FROM balance_history
        ORDER BY id DESC
        LIMIT 20
    """)

    data = cur.fetchall()

    cur.close()
    conn.close()

    return data

# =========================
# Telegram Menu
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton("▶️ Start Crypto Bot", callback_data="start"),
            InlineKeyboardButton("⏹ Stop Crypto Bot", callback_data="stop")
        ],
        [
            InlineKeyboardButton("🔄 Restart Bot", callback_data="restart"),
            InlineKeyboardButton("☠️ Full Kill", callback_data="kill")
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("📈 Open Trades", callback_data="trades")
        ],
        [
            InlineKeyboardButton("🔍 Process Check", callback_data="process")
        ],
        [
            InlineKeyboardButton("📜 View Log", callback_data="log"),
            InlineKeyboardButton("🔴 Live Log", callback_data="live_log")
        ],
        [
            InlineKeyboardButton("📈 Daily Summary", callback_data="summary")
        ],
        [
            InlineKeyboardButton("🔎 Binance Check", callback_data="binance")
        ],

        [
            InlineKeyboardButton("📜 Trade History", callback_data="history"),
            InlineKeyboardButton("💰 Balance", callback_data="balance")
        ],
        [
            InlineKeyboardButton("📝 DB Logs", callback_data="db_logs"),
            InlineKeyboardButton("⚠️ Errors", callback_data="errors")
        ],
    ]


    await update.message.reply_text(
        "🤖 CRYPTO BOT CONTROL PANEL",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# Button Actions
# =========================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    command = ""
    msg = ""


    if query.data == "start":

        command = "sudo systemctl start crypto_bot"
        msg = "✅ Crypto Bot Started"


    elif query.data == "stop":

        command = "sudo systemctl stop crypto_bot"
        msg = "🛑 Crypto Bot Stopped"


    elif query.data == "restart":

        command = "sudo systemctl restart crypto_bot"
        msg = "🔄 Crypto Bot Restarted"


    elif query.data == "kill":

        command = "sudo systemctl stop crypto_bot && pkill -f crypto_bot.py || true"
        msg = "☠️ Full Kill Executed"


    elif query.data == "status":

        service_status = subprocess.getoutput(
            "systemctl is-active crypto_bot"
        )

        balance = get_latest_balance()

        msg = "📊 BOT STATUS\n\n"

        if service_status == "active":
            msg += "🤖 Status: RUNNING ✅\n"
        else:
            msg += "🤖 Status: STOPPED 🛑\n"

        if balance:
            msg += f"💰 Balance: {balance[1]} {balance[0]}"
        else:
            msg += "💰 Balance: No data"

        await query.edit_message_text(msg)
        return


    elif query.data == "trades":

        trades = get_open_trades()

        msg = "📈 OPEN TRADES\n\n"

        if trades:

            for trade in trades:

                msg += (
                    f"Symbol: {trade[0]}\n"
                    f"Side: {trade[1]}\n"
                    f"Entry: {trade[2]}\n"
                    f"Quantity: {trade[3]}\n"
                    "----------------\n"
                )

        else:
            msg += "No open trades"

        await query.edit_message_text(msg)
        return


    elif query.data == "history":

        data = get_trade_history()

        msg = "📜 TRADE HISTORY\n\n"

        for x in data:

            msg += (
                f"{x[0]} {x[1]}\n"
                f"Entry: {x[2]}\n"
                f"Exit: {x[3]}\n"
                f"Profit: {x[4]}\n"
                f"Status: {x[5]}\n"
                f"Time: {x[6]}\n"
                "----------------\n"
            )

        await query.edit_message_text(msg)
        return


    elif query.data == "balance":

        data = get_balance_history()

        msg = "💰 BALANCE HISTORY\n\n"

        for x in data:

            msg += (
                f"Asset: {x[0]}\n"
                f"Balance: {x[1]}\n"
                "----------------\n"
            )

        await query.edit_message_text(msg)
        return


    elif query.data == "db_logs":

        data = get_logs()

        msg = "📝 DATABASE LOGS\n\n"

        for x in data:

            msg += (
                f"{x[0]} : {x[1]}\n"
            )

        await query.edit_message_text(msg)
        return


    elif query.data == "errors":

        data = get_errors()

        msg = "⚠️ ERRORS\n\n"

        for x in data:

            msg += f"{x[0]}\n"

        await query.edit_message_text(msg)
        return


    elif query.data == "process":

        command = "ps aux | grep crypto_bot.py | grep -v grep"
        msg = "🔍 Process Check"


    elif query.data == "log":

        command = "journalctl -u crypto_bot.service -n 50 --no-pager"
        msg = "📜 Recent Logs"


    elif query.data == "live_log":

        command = "journalctl -u crypto_bot.service -f"
        msg = "🔴 Live Logs"


    elif query.data == "summary":

        command = "tail -n 20 /root/daily_trade_summary.csv"
        msg = "📈 Daily Summary"


    elif query.data == "binance":

        command = "python3 /root/check_binance_status.py"
        msg = "🔎 Binance Status"



    result = run_command(command)

    await query.edit_message_text(
        f"{msg}\n\n```\n{result}\n```",
        parse_mode="Markdown"
    )


# =========================
# Start Bot
# =========================

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))


print("Crypto Control Panel Bot Running...")

app.run_polling()
