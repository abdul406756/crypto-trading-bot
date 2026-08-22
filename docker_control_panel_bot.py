from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from database import get_connection

import os
import json
import socket
import urllib.request


# =========================================================
# TELEGRAM CONFIG
# =========================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not configured"
    )


BOT_CONTAINER = "trading-bot"


# =========================================================
# DOCKER API
# =========================================================

def docker_request(method, path):

    sock = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM
    )

    sock.settimeout(30)

    sock.connect(
        "/var/run/docker.sock"
    )

    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Content-Length: 0\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    sock.sendall(
        request.encode()
    )

    response = b""

    while True:

        chunk = sock.recv(8192)

        if not chunk:
            break

        response += chunk

    sock.close()


    header, _, body = response.partition(
        b"\r\n\r\n"
    )


    first_line = header.split(
        b"\r\n",
        1
    )[0].decode(
        errors="ignore"
    )


    try:

        status_code = int(
            first_line.split()[1]
        )

    except Exception:

        status_code = 500


    # -----------------------------------------
    # Decode HTTP chunked response
    # -----------------------------------------

    if (
        b"transfer-encoding: chunked"
        in header.lower()
    ):

        decoded_body = b""
        remaining = body

        while remaining:

            line_end = remaining.find(
                b"\r\n"
            )

            if line_end == -1:
                break


            size_line = remaining[
                :line_end
            ]


            try:

                chunk_size = int(
                    size_line.split(
                        b";"
                    )[0],
                    16
                )

            except ValueError:

                break


            remaining = remaining[
                line_end + 2:
            ]


            if chunk_size == 0:
                break


            decoded_body += remaining[
                :chunk_size
            ]


            remaining = remaining[
                chunk_size + 2:
            ]


        body = decoded_body


    return status_code, body


# =========================================================
# DOCKER CONTAINER CONTROL
# =========================================================

def docker_bot_action(action):

    paths = {

        "start":
            f"/containers/"
            f"{BOT_CONTAINER}/start",

        "stop":
            f"/containers/"
            f"{BOT_CONTAINER}/stop?t=3",

        "restart":
            f"/containers/"
            f"{BOT_CONTAINER}/restart?t=3",

        "kill":
            f"/containers/"
            f"{BOT_CONTAINER}/kill",
    }


    if action not in paths:

        return False, "Invalid action"


    try:

        code, body = docker_request(
            "POST",
            paths[action]
        )


        if code == 204:

            return (
                True,
                f"{action.capitalize()} successful"
            )


        if code == 304:

            if action == "start":

                return (
                    True,
                    "Bot is already running"
                )

            if action == "stop":

                return (
                    True,
                    "Bot is already stopped"
                )

            return (
                True,
                "Command already applied"
            )


        error_text = body.decode(
            errors="ignore"
        )


        return (
            False,
            error_text
            or f"Docker HTTP {code}"
        )


    except Exception as e:

        return False, str(e)


# =========================================================
# DOCKER STATUS
# =========================================================

def get_container_info(
    container_name=BOT_CONTAINER
):

    try:

        code, body = docker_request(
            "GET",
            f"/containers/"
            f"{container_name}/json"
        )


        if code != 200:
            return None


        return json.loads(
            body.decode()
        )


    except Exception as e:

        print(
            "DOCKER INFO ERROR:",
            e
        )

        return None


def docker_bot_running():

    info = get_container_info()

    if not info:
        return False


    return (
        info
        .get("State", {})
        .get("Running", False)
    )


# =========================================================
# DOCKER LOGS
# =========================================================

def decode_docker_logs(body):

    if not body:
        return ""


    output = []
    position = 0


    while position + 8 <= len(body):

        try:

            size = int.from_bytes(
                body[
                    position + 4:
                    position + 8
                ],
                byteorder="big"
            )


            if (
                size <= 0
                or
                position + 8 + size
                > len(body)
            ):

                break


            payload = body[
                position + 8:
                position + 8 + size
            ]


            output.append(
                payload.decode(
                    errors="ignore"
                )
            )


            position += (
                8 + size
            )


        except Exception:

            break


    if output:

        return "".join(output)


    return body.decode(
        errors="ignore"
    )


def get_docker_logs(tail=50):

    try:

        code, body = docker_request(

            "GET",

            f"/containers/"
            f"{BOT_CONTAINER}"
            f"/logs?"
            f"stdout=1&"
            f"stderr=1&"
            f"timestamps=0&"
            f"tail={tail}"
        )


        if code != 200:

            return (
                f"Docker log error "
                f"HTTP {code}"
            )


        logs = decode_docker_logs(
            body
        )


        if not logs.strip():

            return "No logs available"


        return logs[-3500:]


    except Exception as e:

        return str(e)


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

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

        print(
            "BALANCE ERROR:",
            e
        )

        return None


def get_open_trades():

    try:

        conn = get_connection()
        cur = conn.cursor()


        cur.execute("""
            SELECT
                symbol,
                side,
                entry_price,
                quantity
            FROM trades
            WHERE status = 'OPEN'
            ORDER BY id DESC
        """)


        result = cur.fetchall()


        cur.close()
        conn.close()


        return result


    except Exception as e:

        print(
            "TRADE ERROR:",
            e
        )

        return []


def get_trade_history():

    conn = get_connection()
    cur = conn.cursor()


    cur.execute("""
        SELECT
            symbol,
            side,
            entry_price,
            exit_price,
            profit,
            status,
            created_at
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
        SELECT
            level,
            message
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
        SELECT
            asset,
            balance
        FROM balance_history
        ORDER BY id DESC
        LIMIT 20
    """)


    data = cur.fetchall()


    cur.close()
    conn.close()


    return data


def get_daily_summary():

    try:

        conn = get_connection()
        cur = conn.cursor()


        cur.execute("""
            SELECT
                symbol,
                profit,
                closed_at
            FROM trades
            WHERE status = 'CLOSED'
            ORDER BY closed_at DESC NULLS LAST
            LIMIT 20
        """)


        data = cur.fetchall()


        cur.close()
        conn.close()


        return data


    except Exception as e:

        print(
            "SUMMARY ERROR:",
            e
        )

        return []


# =========================================================
# BINANCE CONNECTIVITY CHECK
# =========================================================

def check_binance():

    try:

        request = urllib.request.Request(
            "https://api.binance.com/api/v3/ping",
            headers={
                "User-Agent":
                    "TradingBot-Docker"
            }
        )


        with urllib.request.urlopen(
            request,
            timeout=8
        ) as response:


            if response.status == 200:

                return (
                    "✅ Binance API reachable"
                )


            return (
                f"⚠️ Binance HTTP "
                f"{response.status}"
            )


    except Exception as e:

        return (
            f"❌ Binance connection "
            f"failed:\n{e}"
        )


# =========================================================
# TELEGRAM MESSAGE HELPER
# =========================================================

async def safe_edit(
    query,
    text
):

    if len(text) > 3900:

        text = text[-3900:]


    await query.edit_message_text(
        text
    )


# =========================================================
# TELEGRAM MENU
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [

        [
            InlineKeyboardButton(
                "▶️ Start Crypto Bot",
                callback_data="start"
            ),

            InlineKeyboardButton(
                "⏹ Stop Crypto Bot",
                callback_data="stop"
            )
        ],


        [
            InlineKeyboardButton(
                "🔄 Restart Bot",
                callback_data="restart"
            ),

            InlineKeyboardButton(
                "☠️ Full Kill",
                callback_data="kill"
            )
        ],


        [
            InlineKeyboardButton(
                "📊 Status",
                callback_data="status"
            ),

            InlineKeyboardButton(
                "📈 Open Trades",
                callback_data="trades"
            )
        ],


        [
            InlineKeyboardButton(
                "🔍 Process Check",
                callback_data="process"
            )
        ],


        [
            InlineKeyboardButton(
                "📜 View Log",
                callback_data="log"
            ),

            InlineKeyboardButton(
                "🔴 Live Log",
                callback_data="live_log"
            )
        ],


        [
            InlineKeyboardButton(
                "📈 Daily Summary",
                callback_data="summary"
            )
        ],


        [
            InlineKeyboardButton(
                "🔎 Binance Check",
                callback_data="binance"
            )
        ],


        [
            InlineKeyboardButton(
                "📜 Trade History",
                callback_data="history"
            ),

            InlineKeyboardButton(
                "💰 Balance",
                callback_data="balance"
            )
        ],


        [
            InlineKeyboardButton(
                "📝 DB Logs",
                callback_data="db_logs"
            ),

            InlineKeyboardButton(
                "⚠️ Errors",
                callback_data="errors"
            )
        ]
    ]


    await update.message.reply_text(

        "🤖 DOCKER CRYPTO BOT CONTROL PANEL",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# BUTTON ACTIONS
# =========================================================

async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()


    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if query.data == "start":

        success, result = (
            docker_bot_action(
                "start"
            )
        )


        if success:

            msg = (
                "✅ Crypto Bot Started\n\n"
                f"{result}"
            )

        else:

            msg = (
                "❌ Start Failed\n\n"
                f"{result}"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # STOP
    # -----------------------------------------------------

    elif query.data == "stop":

        success, result = (
            docker_bot_action(
                "stop"
            )
        )


        if success:

            msg = (
                "🛑 Crypto Bot Stopped\n\n"
                f"{result}"
            )

        else:

            msg = (
                "❌ Stop Failed\n\n"
                f"{result}"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # RESTART
    # -----------------------------------------------------

    elif query.data == "restart":

        success, result = (
            docker_bot_action(
                "restart"
            )
        )


        if success:

            msg = (
                "🔄 Crypto Bot Restarted\n\n"
                f"{result}"
            )

        else:

            msg = (
                "❌ Restart Failed\n\n"
                f"{result}"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # KILL
    # -----------------------------------------------------

    elif query.data == "kill":

        success, result = (
            docker_bot_action(
                "kill"
            )
        )


        if success:

            msg = (
                "☠️ Full Kill Executed\n\n"
                f"{result}"
            )

        else:

            msg = (
                "❌ Kill Failed\n\n"
                f"{result}"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    elif query.data == "status":

        running = (
            docker_bot_running()
        )


        balance = (
            get_latest_balance()
        )


        msg = (
            "📊 BOT STATUS\n\n"
        )


        if running:

            msg += (
                "🤖 Status: RUNNING ✅\n"
            )

        else:

            msg += (
                "🤖 Status: STOPPED 🛑\n"
            )


        if balance:

            msg += (
                f"💰 Balance: "
                f"{balance[1]} "
                f"{balance[0]}"
            )

        else:

            msg += (
                "💰 Balance: No data"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # PROCESS CHECK
    # -----------------------------------------------------

    elif query.data == "process":

        info = get_container_info()


        if not info:

            msg = (
                "🔍 PROCESS CHECK\n\n"
                "Container not found"
            )

        else:

            state = info.get(
                "State",
                {}
            )


            msg = (
                "🔍 PROCESS CHECK\n\n"
                f"Container: "
                f"{BOT_CONTAINER}\n"
                f"Running: "
                f"{state.get('Running')}\n"
                f"PID: "
                f"{state.get('Pid')}\n"
                f"Exit Code: "
                f"{state.get('ExitCode')}\n"
                f"OOM Killed: "
                f"{state.get('OOMKilled')}\n"
                f"Started At: "
                f"{state.get('StartedAt')}"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # OPEN TRADES
    # -----------------------------------------------------

    elif query.data == "trades":

        trades = get_open_trades()


        msg = (
            "📈 OPEN TRADES\n\n"
        )


        if trades:

            for trade in trades:

                msg += (
                    f"Symbol: "
                    f"{trade[0]}\n"
                    f"Side: "
                    f"{trade[1]}\n"
                    f"Entry: "
                    f"{trade[2]}\n"
                    f"Quantity: "
                    f"{trade[3]}\n"
                    "----------------\n"
                )

        else:

            msg += (
                "No open trades"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # DOCKER LOG
    # -----------------------------------------------------

    elif query.data == "log":

        logs = get_docker_logs(
            50
        )


        msg = (
            "📜 RECENT DOCKER LOGS\n\n"
            f"{logs}"
        )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # LIVE LOG SNAPSHOT
    # -----------------------------------------------------

    elif query.data == "live_log":

        logs = get_docker_logs(
            100
        )


        msg = (
            "🔴 LIVE LOG SNAPSHOT\n\n"
            f"{logs}"
        )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # DAILY SUMMARY
    # -----------------------------------------------------

    elif query.data == "summary":

        data = get_daily_summary()


        msg = (
            "📈 DAILY SUMMARY\n\n"
        )


        if data:

            for row in data:

                msg += (
                    f"{row[0]}\n"
                    f"Profit: "
                    f"{row[1]}\n"
                    f"Closed: "
                    f"{row[2]}\n"
                    "----------------\n"
                )

        else:

            msg += (
                "No closed trades found"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # BINANCE
    # -----------------------------------------------------

    elif query.data == "binance":

        result = check_binance()


        await safe_edit(

            query,

            "🔎 BINANCE STATUS\n\n"
            f"{result}"
        )

        return


    # -----------------------------------------------------
    # TRADE HISTORY
    # -----------------------------------------------------

    elif query.data == "history":

        data = get_trade_history()


        msg = (
            "📜 TRADE HISTORY\n\n"
        )


        for x in data:

            msg += (
                f"{x[0]} "
                f"{x[1]}\n"
                f"Entry: "
                f"{x[2]}\n"
                f"Exit: "
                f"{x[3]}\n"
                f"Profit: "
                f"{x[4]}\n"
                f"Status: "
                f"{x[5]}\n"
                f"Time: "
                f"{x[6]}\n"
                "----------------\n"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    elif query.data == "balance":

        data = get_balance_history()


        msg = (
            "💰 BALANCE HISTORY\n\n"
        )


        for x in data:

            msg += (
                f"Asset: "
                f"{x[0]}\n"
                f"Balance: "
                f"{x[1]}\n"
                "----------------\n"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # DB LOGS
    # -----------------------------------------------------

    elif query.data == "db_logs":

        data = get_logs()


        msg = (
            "📝 DATABASE LOGS\n\n"
        )


        for x in data:

            msg += (
                f"{x[0]} : "
                f"{x[1]}\n"
            )


        await safe_edit(
            query,
            msg
        )

        return


    # -----------------------------------------------------
    # ERRORS
    # -----------------------------------------------------

    elif query.data == "errors":

        data = get_errors()


        msg = (
            "⚠️ ERRORS\n\n"
        )


        for x in data:

            msg += (
                f"{x[0]}\n"
            )


        await safe_edit(
            query,
            msg
        )

        return


# =========================================================
# START TELEGRAM CONTROL PANEL
# =========================================================

app = (
    Application
    .builder()
    .token(TOKEN)
    .build()
)


app.add_handler(
    CommandHandler(
        "start",
        start
    )
)


app.add_handler(
    CallbackQueryHandler(
        button
    )
)


print(
    "Docker Crypto Control Panel Running...",
    flush=True
)


app.run_polling()
