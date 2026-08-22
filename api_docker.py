from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from binance.client import Client

import os
import subprocess
import ccxt

from database import get_connection


# ==========================
# FastAPI Setup
# ==========================

app = FastAPI()

# ==========================
# Binance API
# ==========================

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

binance_client = Client(
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    testnet=True
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


templates = Jinja2Templates(
    directory="templates"
)


# ==========================
# Root
# ==========================

@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


# ==========================
# Dashboard Page
# ==========================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    conn = get_connection()
    cur = conn.cursor()


    # ==========================
    # RECENT TRADES
    # Live Binance OPEN positions
    # + Today's CLOSED DB trades
    # ==========================

    trades = []


    # ==========================
    # LIVE OPEN TRADES FROM BINANCE
    # ==========================

    try:

        positions = binance_client.futures_position_information()

        for position in positions:

            position_amt = float(position["positionAmt"])

            if position_amt != 0:

                symbol = position["symbol"]

                side = "BUY" if position_amt > 0 else "SELL"

                entry_price = float(position["entryPrice"])

                quantity = abs(position_amt)

                live_pnl = float(
                    position.get("unRealizedProfit", 0)
                )


                live_trade = (
                    None,           # 0 id
                    symbol,         # 1 symbol
                    side,           # 2 side
                    entry_price,    # 3 entry_price
                    None,           # 4 exit_price
                    quantity,       # 5 quantity
                    live_pnl,       # 6 live PnL
                    "OPEN",         # 7 status
                    None,           # 8 created_at
                    None            # 9 closed_at
                )


                trades.append(
                    live_trade
                )


    except Exception as e:

        print(
            "LIVE RECENT TRADES ERROR:",
            e
        )


    # ==========================
    # TODAY'S CLOSED TRADES
    # PostgreSQL history
    # ==========================

    cur.execute("""
        SELECT *
        FROM trades

        WHERE status = 'CLOSED'

        AND closed_at IS NOT NULL

        AND closed_at::date =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date

        ORDER BY closed_at DESC

        LIMIT 20
    """)

    closed_today = cur.fetchall()


    trades.extend(
        closed_today
    )


    # Maximum 20 rows in Recent Trades
    trades = trades[:20]


    # ==========================
    # Current Balance
    # ==========================

    cur.execute("""
        SELECT balance
        FROM balance_history
        ORDER BY id DESC
        LIMIT 1
    """)

    balance_result = cur.fetchone()


    if balance_result:

        balance = round(
            float(balance_result[0]),
            2
        )

    else:

        balance = 0



    # ==========================
    # Live OPEN Trade PnL
    # ==========================

    exchange = ccxt.binance({
        "enableRateLimit": True
    })

    updated_trades = []


    for trade in trades:

        trade = list(trade)


        if trade[7] == "OPEN":

            try:

                symbol = trade[1].replace(
                    "USDT",
                    "/USDT"
                )

                ticker = exchange.fetch_ticker(symbol)

                current_price = float(
                    ticker["last"]
                )

                entry_price = float(
                    trade[3]
                )

                quantity = float(
                    trade[5]
                )


                if trade[2] == "BUY":

                    live_pnl = (
                        current_price
                        -
                        entry_price
                    ) * quantity

                else:

                    live_pnl = (
                        entry_price
                        -
                        current_price
                    ) * quantity


                trade[6] = round(
                    live_pnl,
                    2
                )


            except Exception as e:

                print(
                    "LIVE PNL ERROR:",
                    trade[1],
                    e
                )

                trade[6] = 0


        updated_trades.append(
            tuple(trade)
        )


    trades = updated_trades


    # ==========================
    # Current Balance
    # ==========================

    cur.execute("""
        SELECT balance
        FROM balance_history
        ORDER BY id DESC
        LIMIT 1
    """)

    balance_result = cur.fetchone()


    if balance_result:

        balance = round(
            float(balance_result[0]),
            2
        )

    else:

        balance = 0


    # ==========================
    # TODAY'S TOTAL TRADES
    #
    # created_at is old UTC-style
    # timestamp, therefore convert
    # it to China time first.
    # ==========================

    cur.execute("""
        SELECT COUNT(*)
        FROM trades

        WHERE
        (
            created_at
            AT TIME ZONE 'UTC'
            AT TIME ZONE 'Asia/Shanghai'
        )::date
        =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    total_trades = cur.fetchone()[0]


    # ==========================
    # LIVE OPEN TRADES - BINANCE
    # ==========================

    try:

        positions = binance_client.futures_position_information()

        open_trades = sum(
            1
            for position in positions
            if float(position["positionAmt"]) != 0
        )

    except Exception as e:

        print("LIVE OPEN TRADES ERROR:", e)

        open_trades = 0


    # ==========================
    # Errors
    # ==========================

    cur.execute("""
        SELECT COUNT(*)
        FROM errors
    """)

    errors = cur.fetchone()[0]

    # ==========================
    # REAL SIGNAL METRICS
    # ==========================

    cur.execute("""
        SELECT COUNT(*)
        FROM logs
        WHERE level IN ('SIGNAL', 'SIGNAL_CHECK')
        AND (
            created_at
            AT TIME ZONE 'UTC'
            AT TIME ZONE 'Asia/Shanghai'
        )::date =
        (
        
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    signals_processed = cur.fetchone()[0]


    # ==========================
    # OVERALL MARKET INSIGHT
    # Latest signal from each pair
    # ==========================

    cur.execute("""
        SELECT DISTINCT ON (
            split_part(message, '|', 1)
        )
            message

        FROM logs

        WHERE level IN ('SIGNAL', 'SIGNAL_CHECK')

        ORDER BY
            split_part(message, '|', 1),
            id DESC
    """)

    latest_signals = cur.fetchall()


    total_buy_score = 0
    total_sell_score = 0
    pair_count = 0


    for row in latest_signals:

        try:

            parts = row[0].split("|")

            if len(parts) >= 4:

                buy_score = int(parts[2])
                sell_score = int(parts[3])

                total_buy_score += buy_score
                total_sell_score += sell_score

                pair_count += 1

        except Exception as e:

            print(
                "PAIR SIGNAL PARSE ERROR:",
                e
            )


    market_signal = "Monitoring"
    signal_confidence = 0


    if pair_count > 0:

        max_total_score = pair_count * 8

        buy_percent = round(
            (total_buy_score / max_total_score) * 100,
            1
        )

        sell_percent = round(
            (total_sell_score / max_total_score) * 100,
            1
        )


        if total_buy_score > total_sell_score:

            market_signal = "Bullish ↑"

            signal_confidence = buy_percent


        elif total_sell_score > total_buy_score:

            market_signal = "Bearish ↓"

            signal_confidence = sell_percent


    else:

        market_signal = "Neutral →"

        signal_confidence = round(
            (
                total_buy_score
                /
                max_total_score
            )
            * 100,
            1
        )

    # ==========================
    # TODAY'S REALIZED PROFIT
    # ==========================

    cur.execute("""
        SELECT COALESCE(
            SUM(profit),
            0
        )

        FROM trades

        WHERE status = 'CLOSED'

        AND closed_at IS NOT NULL

        AND closed_at::date =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    total_profit_result = cur.fetchone()[0]

    total_profit = round(
        float(total_profit_result),
        2
    )

    

    # ==========================
    # TODAY'S WINNING TRADES
    # ==========================

    cur.execute("""
        SELECT COUNT(*)

        FROM trades

        WHERE status = 'CLOSED'

        AND profit > 0

        AND closed_at IS NOT NULL

        AND closed_at::date =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    winning_trades = cur.fetchone()[0]


    # ==========================
    # TODAY'S LOSING TRADES
    # ==========================

    cur.execute("""
        SELECT COUNT(*)

        FROM trades

        WHERE status = 'CLOSED'

        AND profit < 0

        AND closed_at IS NOT NULL

        AND closed_at::date =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    losing_trades = cur.fetchone()[0]


    # ==========================
    # TODAY'S CLOSED TRADES
    # ==========================

    cur.execute("""
        SELECT COUNT(*)

        FROM trades

        WHERE status = 'CLOSED'

        AND closed_at IS NOT NULL

        AND closed_at::date =
        (
            CURRENT_TIMESTAMP
            AT TIME ZONE 'Asia/Shanghai'
        )::date
    """)

    closed_trades = cur.fetchone()[0]


    # ==========================
    # TODAY'S WIN RATE
    # ==========================

    if closed_trades > 0:

        win_rate = round(
            (
                winning_trades
                /
                closed_trades
            )
            * 100,
            2
        )

    else:

        win_rate = 0


    cur.close()
    conn.close()


    # ==========================
    # Render Dashboard
    # ==========================

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "trades": trades,
            "balance": balance,
            "total_trades": total_trades,
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "errors": errors,
            "total_profit": total_profit,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "signals_processed": signals_processed,
            "market_signal": market_signal,
            "signal_confidence": signal_confidence
        }
    )
# ==========================
# Docker API Helper
# ==========================

def docker_request(method, path):

    import socket

    sock = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM
    )

    sock.settimeout(30)
    sock.connect("/var/run/docker.sock")

    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Content-Length: 0\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    sock.sendall(request.encode())

    response = b""

    while True:

        chunk = sock.recv(4096)

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
    )[0].decode()

    try:
        status_code = int(
            first_line.split()[1]
        )
    except Exception:
        status_code = 500


    # ==========================
    # Decode HTTP chunked body
    # ==========================

    if b"transfer-encoding: chunked" in header.lower():

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
                    size_line.split(b";")[0],
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


# ==========================
# Bot Control
# Docker Version
# ==========================

@app.post("/control/{action}")
def control_bot(action: str):

    allowed_actions = {
        "start",
        "stop",
        "restart",
        "kill"
    }

    if action not in allowed_actions:

        return {
            "success": False,
            "error": "Invalid action"
        }

    try:

        container_name = "trading-bot"

        if action == "start":

            path = (
                f"/containers/{container_name}/start"
            )

        elif action == "stop":

            path = (
                f"/containers/{container_name}/stop?t=3"
            )

        elif action == "restart":

            path = (
                f"/containers/{container_name}/restart?t=3"
            )

        else:

            path = (
                f"/containers/{container_name}/kill"
            )

        status_code, body = docker_request(
            "POST",
            path
        )

        success = status_code in {
            204,
            304
        }

        if status_code == 304:

            if action == "start":
                message = "Bot is already running"

            elif action == "stop":
                message = "Bot is already stopped"

            else:
                message = "Command completed"

        elif success:

            message = (
                f"Bot {action} command "
                f"executed successfully"
            )

        else:

            message = (
                body.decode(
                    errors="ignore"
                )
                or
                f"Docker returned HTTP {status_code}"
            )

        return {
            "success": success,
            "action": action,
            "message": message
        }

    except Exception as e:

        return {
            "success": False,
            "action": action,
            "error": str(e)
        }



# ==========================
# Service Status
# Docker Version
# ==========================

@app.get("/status")
def status():

    import json

    def get_container_status(container_name):

        try:

            status_code, body = docker_request(
                "GET",
                f"/containers/{container_name}/json"
            )

            if status_code != 200:
                return "inactive"

            data = json.loads(
                body.decode()
            )

            if data.get("State", {}).get("Running", False):
                return "active"

            return "inactive"

        except Exception as e:

            print(
                "DOCKER STATUS ERROR:",
                container_name,
                e
            )

            return "unknown"

    return {
        "crypto_bot": get_container_status(
            "trading-bot"
        ),

        "control_panel": get_container_status(
            "trading-control-panel"
        ),

        "dashboard": get_container_status(
            "trading-dashboard"
        )
    }


# ==========================
# Balance Chart
# Last 100 Balance Records
# ==========================

@app.get("/balance_chart")
def balance_chart():

    conn = get_connection()
    cur = conn.cursor()


    cur.execute("""
        SELECT created_at, balance

        FROM (
            SELECT
                id,
                created_at,
                balance

            FROM balance_history

            ORDER BY id DESC

            LIMIT 100
        ) AS latest

        ORDER BY id ASC
    """)


    rows = cur.fetchall()


    cur.close()
    conn.close()


    data = []


    for row in rows:

        data.append({
            "time": row[0],
            "balance": float(row[1])
        })


    return {
        "balance": data
    }


# ==========================
# Profit Chart
# Last 60 Closed Trades
# ==========================

@app.get("/profit_chart")
def profit_chart():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            closed_at,
            profit
        FROM (
            SELECT
                closed_at,
                profit
            FROM trades
            WHERE status = 'CLOSED'
              AND closed_at IS NOT NULL
              AND profit IS NOT NULL
              AND profit <> 0
            ORDER BY closed_at DESC
            LIMIT 60
        ) AS latest
        ORDER BY closed_at ASC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    data = []

    for row in rows:

        data.append({
            "time": row[0].isoformat() if row[0] else None,
            "profit": round(float(row[1]), 2)
        })

    return {
        "profit": data
    }
