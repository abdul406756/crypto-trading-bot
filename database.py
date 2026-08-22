import os
import psycopg2


def get_connection():
    return psycopg2.connect(
        database=os.getenv("DB_NAME", "trading_bot"),
        user=os.getenv("DB_USER", "bot_user"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432")
    )


# ==========================
# Save new trade
# ==========================

def save_trade(symbol, side, entry_price, quantity, status="OPEN"):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO trades
        (
            symbol,
            side,
            entry_price,
            quantity,
            status
        )
        VALUES (%s,%s,%s,%s,%s)
    """, (
        symbol,
        side,
        entry_price,
        quantity,
        status
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Update closed trade by ID
# ==========================

def update_trade(
    trade_id,
    exit_price,
    profit,
    status="CLOSED"
):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE trades

        SET
            exit_price = %s,
            profit = %s,
            status = %s,
            closed_at = (
                CURRENT_TIMESTAMP
                AT TIME ZONE 'Asia/Shanghai'
            )

        WHERE id = %s
    """, (
        exit_price,
        profit,
        status,
        trade_id
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Save order information
# ==========================

def save_order(
    symbol,
    order_id,
    order_type,
    side,
    quantity,
    price,
    status
):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders
        (
            symbol,
            order_id,
            order_type,
            side,
            quantity,
            price,
            status
        )

        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        symbol,
        order_id,
        order_type,
        side,
        quantity,
        price,
        status
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Update bot status
# ==========================

def update_bot_status(status, message):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO bot_status
        (
            status,
            message
        )

        VALUES (%s,%s)
    """, (
        status,
        message
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Save account balance
# ==========================

def save_balance(asset, balance):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO balance_history
        (
            asset,
            balance
        )

        VALUES (%s,%s)
    """, (
        asset,
        balance
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Save errors
# ==========================

def save_error(message):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO errors
        (
            message
        )

        VALUES (%s)
    """, (
        message,
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Save system logs
# ==========================

def save_log(level, message):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO logs
        (
            level,
            message
        )

        VALUES (%s,%s)
    """, (
        level,
        message
    ))

    conn.commit()

    cur.close()
    conn.close()


# ==========================
# Close trade by symbol
# ==========================

def close_trade(
    symbol,
    exit_price,
    profit
):

    try:

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE trades

            SET
                exit_price = %s,
                profit = %s,
                status = 'CLOSED',
                closed_at = (
                    CURRENT_TIMESTAMP
                    AT TIME ZONE 'Asia/Shanghai'
                )

            WHERE symbol = %s
            AND status = 'OPEN'
        """, (
            exit_price,
            profit,
            symbol
        ))

        conn.commit()

        cur.close()
        conn.close()

    except Exception as e:

        print(
            "CLOSE TRADE ERROR:",
            e
        )


# ==========================
# Test connection
# ==========================

if __name__ == "__main__":

    conn = get_connection()

    print(
        "PostgreSQL connected successfully!"
    )

    conn.close()
