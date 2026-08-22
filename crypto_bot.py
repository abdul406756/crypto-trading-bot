# === Imports ===
from binance.client import Client
from binance.enums import *
import pandas as pd
from datetime import datetime, timedelta
import time
import csv
from telegram import Bot
import asyncio
import threading
from decimal import Decimal
import math
import os

# === Database ===
from database import (
    save_trade,
    save_order,
    save_error,
    update_bot_status,
    save_balance,
    save_log,
    close_trade
)

# === API Keys (Real Account Mode) ===
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key, api_secret, testnet=True)

# === Telegram Bot Setup ===
status_bot_token = os.getenv("STATUS_BOT_TOKEN")
signal_bot_token = os.getenv("SIGNAL_BOT_TOKEN")
daily_summary_bot_token = os.getenv("DAILY_SUMMARY_BOT_TOKEN")
telegram_user_id = 7719570579
status_bot = Bot(token=status_bot_token)
signal_bot = Bot(token=signal_bot_token)
daily_summary_bot = Bot(token=daily_summary_bot_token)

# === Telegram Event Loop ===
telegram_loop = asyncio.new_event_loop()
def start_telegram_loop():
    asyncio.set_event_loop(telegram_loop)
    telegram_loop.run_forever()
threading.Thread(target=start_telegram_loop, daemon=True).start()
def send_async(coro):
    asyncio.run_coroutine_threadsafe(coro, telegram_loop)

async def send_status_message(text):
    await status_bot.send_message(chat_id=telegram_user_id, text=f"✅ Status:\n{text}")

async def send_signal_alert(text):
    await signal_bot.send_message(chat_id=telegram_user_id, text=f"{text}")

async def send_daily_summary(text):
    await daily_summary_bot.send_message(chat_id=telegram_user_id, text=f"{text}")

# === Strategy Settings ===
FIXED_DOLLAR_RISK = 1  # Max loss per trade in USD
TP_DOLLAR_TARGET = 1   # Max reward per trade in USD
COOLDOWN_MINUTES = 1   # Cooldown between trades
SL_PERCENTAGE = 0.006
TP_PERCENTAGE = 0.006

# === Signal Logic Settings ===
IMBALANCE_THRESHOLD = 0.004
LIQUIDITY_WALL_QTY = 2
ORDERBOOK_DEPTH = 10
USE_TREND_FILTER = True  # ✅ Trend filter ENABLED

# === Symbols and Volume Filters ===
SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT', 'ADAUSDT', 'DOTUSDT'
]
VOLUME_THRESHOLDS = {
    'BTCUSDT': 10, 'ETHUSDT': 8, 'BNBUSDT': 6, 'SOLUSDT': 6, 'XRPUSDT': 5,
    'DOGEUSDT': 5, 'LINKUSDT': 5, 'LTCUSDT': 5, 'ADAUSDT': 5, 'DOTUSDT': 5,
}

# === Internal State Tracking ===
last_trade_side_dict = {symbol: None for symbol in SYMBOLS}
last_close_time_dict = {symbol: None for symbol in SYMBOLS}
was_open_dict = {symbol: False for symbol in SYMBOLS}
active_signal_id_dict = {symbol: None for symbol in SYMBOLS}
global_signal_id = 0

# === Daily Trade Tracker ===
daily_trade_stats = {
    'date': datetime.now().strftime('%Y-%m-%d'),
    'total_trades': 0,
    'wins': 0,
    'losses': 0,
    'win_balance': 0.0,
    'loss_balance': 0.0,
}

# === Indicator Functions ===
def ema(df, span=50):
    return df['close'].ewm(span=span, adjust=False).mean()

def rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-6)
    return 100 - (100 / (1 + rs))

def macd(df, fast=12, slow=26, signal=9):
    fast_ma = df['close'].ewm(span=fast, adjust=False).mean()
    slow_ma = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = fast_ma - slow_ma
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

# === Safe Call Wrapper ===
def safe_call(func, *args, retries=3, delay=1, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise e

# === Candle Data Fetching ===
def get_1min_klines(symbol, limit=50):
    candles = safe_call(client.futures_klines, symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
    df = pd.DataFrame(candles, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'quote_asset_volume', 'number_of_trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def get_5min_klines(symbol):
    candles = safe_call(client.futures_klines, symbol=symbol, interval=Client.KLINE_INTERVAL_5MINUTE, limit=1)
    if not candles:
        return None
    return float(candles[-1][4])  # last closing price

# === Order Book Logic ===
def get_order_book(symbol, depth=100):
    book = safe_call(client.futures_order_book, symbol=symbol, limit=depth)
    bids = [(float(p), float(q)) for p, q in book['bids']]
    asks = [(float(p), float(q)) for p, q in book['asks']]
    return bids, asks

def calculate_orderbook_imbalance(bids, asks):
    bid_vol = sum(q for _, q in bids[:ORDERBOOK_DEPTH])
    ask_vol = sum(q for _, q in asks[:ORDERBOOK_DEPTH])
    return (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-6)

def has_liquidity_wall(order_list, threshold_qty):
    return any(qty >= threshold_qty for _, qty in order_list[:ORDERBOOK_DEPTH])

# === Large Trade Filter ===
def get_large_trades(symbol):
    trades = safe_call(client.futures_recent_trades, symbol=symbol)
    return [t for t in trades if float(t['qty']) > VOLUME_THRESHOLDS.get(symbol, 5)]

# === Signal Scoring Logic ===
def generate_signal(symbol):
    try:
        df = get_1min_klines(symbol)
        if df.empty or len(df) < 30:
            return None

        current_price = df['close'].iloc[-1]
        open_price = df['open'].iloc[-1]
        volume = df['volume'].iloc[-1]
        if volume < VOLUME_THRESHOLDS.get(symbol, 5):
            return None

        # === Indicators ===
        ema_50 = ema(df).iloc[-1]
        rsi_14 = rsi(df).iloc[-1]
        macd_line, signal_line = macd(df)
        macd_hist = macd_line.iloc[-1] - signal_line.iloc[-1]
        macd_prev = macd_line.iloc[-2] - signal_line.iloc[-2]

        # === Order Book & Trades ===
        bids, asks = get_order_book(symbol)
        imbalance = calculate_orderbook_imbalance(bids, asks)
        trades = get_large_trades(symbol)

        # === Liquidity Walls ===
        buyer_wall = has_liquidity_wall(bids[:5], LIQUIDITY_WALL_QTY)
        seller_wall = has_liquidity_wall(asks[:5], LIQUIDITY_WALL_QTY)

        # === Candle Body Filter ===
        high = df['high'].iloc[-1]
        low = df['low'].iloc[-1]
        body = abs(current_price - open_price)
        range_total = high - low
        is_good_candle = range_total > 0 and body >= 0.3 * range_total

        # === Trend Filter (Optional) ===
        if USE_TREND_FILTER:
            price_5min = get_5min_klines(symbol)
            if price_5min is None:
                return None
            if (current_price > ema_50 and price_5min < ema_50) or \
               (current_price < ema_50 and price_5min > ema_50):
                print(f"{symbol} blocked by 5-min trend filter")
                return None

        # === BUY Score Calculation ===
        buy_score = 0
        reasons = []

        if imbalance > IMBALANCE_THRESHOLD:
            buy_score += 1
            reasons.append("Imbalance ✅")
        if current_price > ema_50:
            buy_score += 1
            reasons.append("EMA ✅")
        if rsi_14 < 45:
            buy_score += 1
            reasons.append("RSI ✅")
        if macd_hist > 0:
            buy_score += 1
            reasons.append("MACD Histogram ✅")
        if macd_hist > 0 and macd_prev < 0:
            buy_score += 1
            reasons.append("MACD Crossover ✅")
        if buyer_wall:
            buy_score += 1
            reasons.append("Buyer Wall ✅")
        if volume >= VOLUME_THRESHOLDS.get(symbol, 5):
            buy_score += 1
            reasons.append("Volume ✅")
        if is_good_candle:
            buy_score += 1
            reasons.append("Candle Body ✅")

        # === SELL Score Calculation ===
        sell_score = 0
        sell_reasons = []

        if imbalance < -IMBALANCE_THRESHOLD:
            sell_score += 1
            sell_reasons.append("Imbalance ✅")
        if current_price < ema_50:
            sell_score += 1
            sell_reasons.append("EMA ✅")
        if rsi_14 > 55:
            sell_score += 1
            sell_reasons.append("RSI ✅")
        if macd_hist < 0:
            sell_score += 1
            sell_reasons.append("MACD Histogram ✅")
        if macd_hist < 0 and macd_prev > 0:
            sell_score += 1
            sell_reasons.append("MACD Crossover ✅")
        if seller_wall:
            sell_score += 1
            sell_reasons.append("Seller Wall ✅")
        if volume >= VOLUME_THRESHOLDS.get(symbol, 5):
            sell_score += 1
            sell_reasons.append("Volume ✅")
        if is_good_candle:
            sell_score += 1
            sell_reasons.append("Candle Body ✅")

        # === Final Signal Decision ===

        if buy_score >= 1:

            save_log(
                "SIGNAL",
                f"{symbol}|BUY|{buy_score}|{sell_score}"
            )

            print(
                f"{symbol} BUY signal: Score {buy_score}/8 → Triggered"
            )

            print(
                "✔️ " + " | ".join(reasons)
            )

            return "BUY"


        elif sell_score >= 1:

            save_log(
                "SIGNAL",
                f"{symbol}|SELL|{buy_score}|{sell_score}"
            )

            print(
                f"{symbol} SELL signal: Score {sell_score}/8 → Triggered"
            )

            print(
                "✔️ " + " | ".join(sell_reasons)
            )

            return "SELL"


        else:

            save_log(
                "SIGNAL_CHECK",
                f"{symbol}|NONE|{buy_score}|{sell_score}"
            )

            print(
                f"{symbol}: No signal "
                f"(BUY {buy_score}/8, SELL {sell_score}/8)"
            )

            return None

    except Exception as e:
               print(f"Signal error for {symbol}: {e}")
               return None

# === Helpers ===
def get_btc_price(symbol):
    return float(safe_call(client.futures_symbol_ticker, symbol=symbol)['price'])

def get_tick_size(symbol):
    info = safe_call(client.futures_exchange_info)
    symbol_info = next(item for item in info['symbols'] if item['symbol'] == symbol)
    return float([f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'][0]['tickSize'])

def get_step_size(symbol):
    info = safe_call(client.futures_exchange_info)
    symbol_info = next(item for item in info['symbols'] if item['symbol'] == symbol)
    return float([f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])

def round_price_to_tick(price, tick_size):
    tick = Decimal(str(tick_size))
    return float(Decimal(str(price)).quantize(tick))

def round_quantity_to_step(quantity, step_size):
    precision = int(round(-math.log10(step_size)))
    return float(f"{math.floor(quantity * (10 ** precision)) / (10 ** precision):.{precision}f}")

def get_entry_price(symbol):
    positions = safe_call(client.futures_position_information, symbol=symbol)
    for p in positions:
        if float(p['positionAmt']) != 0:
            return float(p['entryPrice'])
    return None

# === Quantity Calculation ===
def calculate_trade_quantity(symbol):
    price = get_btc_price(symbol)
    sl_move = price * SL_PERCENTAGE
    position_size = FIXED_DOLLAR_RISK / sl_move
    raw_quantity = position_size
    step_size = get_step_size(symbol)
    quantity = round_quantity_to_step(raw_quantity, step_size)
    leverage = 50
    try:
        safe_call(client.futures_change_leverage, symbol=symbol, leverage=leverage)
    except Exception as e:
        print(f"Leverage error: {e}")
    return quantity, raw_quantity, leverage

# === Cancel All Orders ===
def cancel_symbol_orders(symbol):
    try:
        open_orders = safe_call(client.futures_get_open_orders, symbol=symbol)
        for order in open_orders:
            safe_call(client.futures_cancel_order, symbol=symbol, orderId=order['orderId'])
    except Exception as e:
        print(f"Cancel error for {symbol}: {e}")

# === Trade Logger ===
def log_trade_detail(date, signal_id, symbol, result, pnl, balance):
    with open('trade_logs.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([date, signal_id, symbol, result, f"${pnl:.2f}", f"${balance:.2f}"])

# === PnL Tracker ===
def update_daily_trade_stats(result, profit_loss):
    if result == 'win':
        daily_trade_stats['wins'] += 1
        daily_trade_stats['win_balance'] += profit_loss
    elif result == 'loss':
        daily_trade_stats['losses'] += 1
        daily_trade_stats['loss_balance'] += profit_loss
    daily_trade_stats['total_trades'] += 1

def get_binance_balance():

    account = safe_call(client.futures_account)

    return float(
        account["totalMarginBalance"]
    )

# === Place Futures Order ===
def place_futures_market_order(symbol, side, quantity, raw_quantity, leverage):
    global global_signal_id
    global_signal_id += 1
    signal_id = global_signal_id
    active_signal_id_dict[symbol] = signal_id
    try:
        # === Set Margin Type ===
        try:
            safe_call(client.futures_change_margin_type, symbol=symbol, marginType='ISOLATED')
        except Exception as e:
            if "No need to change margin type" not in str(e):
                print(f"Margin type error for {symbol}: {e}")

        # === Market Entry ===
        try:
            entry_order = safe_call(
                client.futures_create_order,
                symbol=symbol,
                side=Client.SIDE_BUY if side == 'BUY' else Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
        except:
            fallback_price = get_btc_price(symbol)
            safe_call(client.futures_create_order,
                      symbol=symbol,
                      side=Client.SIDE_BUY if side == 'BUY' else Client.SIDE_SELL,
                      type=Client.ORDER_TYPE_LIMIT,
                      price=str(fallback_price),
                      timeInForce='GTC',
                      quantity=quantity)
            send_async(send_signal_alert(f"⚠️ MARKET failed, used LIMIT for {symbol} (Signal #{signal_id})"))

        # === Entry Price ===
        time.sleep(0.5)
        position = safe_call(client.futures_position_information, symbol=symbol)
        active_pos = [p for p in position if float(p['positionAmt']) != 0]
        if not active_pos:
            send_async(send_signal_alert(f"❌ No active position found for {symbol} (Signal #{signal_id})"))
            return

        entry_price = float(active_pos[0]['entryPrice'])


        # === Save Entry Order to Database ===
        try:
            save_order(
                symbol=symbol,
                order_id=str(entry_order['orderId']),
                order_type="MARKET",
                side=side,
                quantity=quantity,
                price=entry_price,
                status="FILLED"
            )

            save_log(
                "INFO",
                f"Order saved: {symbol} {side} at {entry_price}"
            )

        except Exception as e:
            save_error(str(e))

        # === Save Trade to Database ===
        try:
            save_trade(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                status="OPEN"
            )

            save_log(
                "INFO",
                f"Opened {side} trade for {symbol} at {entry_price}"
            )

        except Exception as e:
            save_error(str(e))

        # === TP/SL With Fixed Dollar Risk/Reward ===
        tick_size = get_tick_size(symbol)
        tick = Decimal(str(tick_size))

        move_sl = FIXED_DOLLAR_RISK / quantity
        move_tp = TP_DOLLAR_TARGET / quantity
        sl_price = entry_price - move_sl if side == 'BUY' else entry_price + move_sl
        tp_price = entry_price + move_tp if side == 'BUY' else entry_price - move_tp

        # Add buffer (2 ticks)
        sl_price = float(Decimal(str(sl_price)) - tick * 2)
        tp_price = float(Decimal(str(tp_price)) + tick * 2)

        sl_price = round_price_to_tick(sl_price, tick_size)
        tp_price = round_price_to_tick(tp_price, tick_size)

        # === Place TP/SL Orders Safely ===
        def safe_order(order_type, stop_price):
            for _ in range(5):
                try:
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=Client.SIDE_SELL if side == 'BUY' else Client.SIDE_BUY,
                        type=order_type,
                        stopPrice=str(stop_price),
                        closePosition=True
                    )

                    # Save TP/SL order to database
                    try:
                        save_order(
                            symbol=symbol,
                            order_id=str(order['orderId']),
                            order_type=order_type,
                            side="CLOSE",
                            quantity=quantity,
                            price=stop_price,
                            status="OPEN"
                        )

                        save_log(
                            "INFO",
                            f"{order_type} created for {symbol}"
                        )

                    except Exception as e:
                        save_error(str(e))

                    return True

                except:
                    time.sleep(0.5)

            return False

        tp_success = safe_order('TAKE_PROFIT_MARKET', tp_price)
        sl_success = safe_order('STOP_MARKET', sl_price)

        # === Emergency Close Fallback ===
        failure_reason = ""
        if not tp_success and not sl_success:
            failure_reason = "❌ TP and SL both failed"
        elif not tp_success:
            failure_reason = "❌ TP failed"
        elif not sl_success:
            failure_reason = "❌ SL failed"

        if failure_reason:
            cancel_symbol_orders(symbol)
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side=Client.SIDE_SELL if side == 'BUY' else Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=quantity
                )
            except:
                try:
                    alt_price = get_btc_price(symbol)
                    client.futures_create_order(
                        symbol=symbol,
                        side=Client.SIDE_SELL if side == 'BUY' else Client.SIDE_BUY,
                        type=Client.ORDER_TYPE_LIMIT,
                        timeInForce='GTC',
                        price=str(alt_price),
                        quantity=quantity
                    )
                except Exception as e:
                    send_async(send_signal_alert(f"❌ Emergency close failed for {symbol} (Signal #{signal_id}): {e}"))

            positions = client.futures_position_information(symbol=symbol)
            still_open = any(float(p['positionAmt']) != 0 for p in positions)

            if still_open:
                send_async(send_signal_alert(f"{failure_reason}, but ❌ Emergency close FAILED for {symbol} (Signal #{signal_id})"))
            else:
                send_async(send_signal_alert(f"{failure_reason}, ✅ Emergency close SUCCESS for {symbol} (Signal #{signal_id})"))

            log_trade_detail(datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                             signal_id, symbol, failure_reason,
                             -FIXED_DOLLAR_RISK, get_binance_balance())
            update_daily_trade_stats('loss', FIXED_DOLLAR_RISK)
            active_signal_id_dict[symbol] = None
            return

        # === TP/SL Result Summary Message ===
        move_tp = abs(tp_price - entry_price)
        move_sl = abs(entry_price - sl_price)
        move_tp_pct = (move_tp / entry_price) * 100
        move_sl_pct = (move_sl / entry_price) * 100
        risk_dollars = move_sl * quantity
        reward_dollars = move_tp * quantity
        rr_ratio = round(reward_dollars / risk_dollars, 2) if risk_dollars else 0

        msg = (
            f"🚨 Signal #{signal_id} Alert:\n"
            f"📈 Signal: {side} at ${entry_price:.4f}\n"
            f"Pair: {symbol}\nQty: {quantity}\nLeverage: {leverage}x\n\n"
            f"🎯 TP: {tp_price} (+${move_tp:.2f}, +{move_tp_pct:.2f}%)\n"
            f"🛑 SL: {sl_price} (-${move_sl:.2f}, -{move_sl_pct:.2f}%)\n\n"
            f"💰 Risk: ${risk_dollars:.2f} | Reward: ${reward_dollars:.2f}\n"
            f"🎯 R/R: 1:{rr_ratio} | TP: {'✅' if tp_success else '❌'} | SL: {'✅' if sl_success else '❌'}"
        )
        send_async(send_signal_alert(msg))

    except Exception as e:
        signal_id = active_signal_id_dict.get(symbol, '❓')
        send_async(send_signal_alert(f"❌ Trade skipped for {symbol} (Signal #{signal_id}): {e}"))
        active_signal_id_dict[symbol] = None

# === Legacy Position Check (for compatibility) ===
def is_position_open(symbol):
    try:
        positions = safe_call(client.futures_position_information, symbol=symbol)
        for p in positions:
            if float(p['positionAmt']) != 0:
                return True
    except:
        pass
    return False

# === Position Check ===
def is_trade_really_closed(symbol):
    try:
        positions = safe_call(client.futures_position_information, symbol=symbol)
        position_open = any(float(p['positionAmt']) != 0 for p in positions)
        open_orders = safe_call(client.futures_get_open_orders, symbol=symbol)
        return not position_open and len(open_orders) == 0
    except:
        return False

# === Timezone Import ===
from pytz import timezone

# === Session Time Filter (China time) ===
def is_allowed_trading_time():
    china_tz = timezone('Asia/Shanghai')
    now = datetime.now(china_tz)
    hour = now.hour
    return 1 <= hour < 24  # Allowed from 15:00 (3 PM) to 00:00 (midnight)

# === Main Bot Loop with Retry Logic ===
def run_multi_pair_strategy():
    send_async(send_status_message("✅ Multi-Pair Bot is live."))
    send_async(send_signal_alert("🚨 Signal Bot is live and monitoring markets."))
    global global_signal_id
    while True:
        try:
            china_tz = timezone('Asia/Shanghai')
            now = datetime.now(china_tz)

            # === Daily Reset ===
            if now.strftime('%H:%M') == '00:00':
                global_signal_id = 1
                time.sleep(60)

            for symbol in SYMBOLS:
                time.sleep(0.3)  # ✅ Delay per symbol to reduce API spam

                # === Check allowed session time ===
                if not is_allowed_trading_time():
                    continue

                for retry in range(3):
                    try:
                        # === Ghost Margin Cleanup ===
                        positions = safe_call(client.futures_position_information, symbol=symbol)
                        for p in positions:
                            if float(p['positionAmt']) == 0 and float(p['entryPrice']) == 0 and float(p['isolatedMargin']) < 0:
                                cancel_symbol_orders(symbol)
                                try:
                                    safe_call(client.futures_create_order,
                                              symbol=symbol,
                                              side=Client.SIDE_BUY,
                                              type=Client.ORDER_TYPE_MARKET,
                                              quantity=0.001)
                                except:
                                    try:
                                        safe_call(client.futures_create_order,
                                                  symbol=symbol,
                                                  side=Client.SIDE_BUY,
                                                  type=Client.ORDER_TYPE_LIMIT,
                                                  price=str(get_btc_price(symbol)),
                                                  timeInForce='GTC',
                                                  quantity=0.001)
                                    except:
                                        send_async(send_signal_alert(f"❌ Ghost close failed for {symbol}"))
                                send_async(send_signal_alert(f"⚠️ Ghost margin auto-flushed for {symbol}"))
                                break

                        # === Position Close Detection ===
                        if is_position_open(symbol):
                            was_open_dict[symbol] = True
                        else:
                            if was_open_dict[symbol]:
                                # ✅ Cancel all leftover open orders
                                open_orders = safe_call(client.futures_get_open_orders, symbol=symbol)
                                if open_orders:
                                    cancel_symbol_orders(symbol)

                                # ✅ Recheck position again
                                positions_check = safe_call(client.futures_position_information, symbol=symbol)
                                position_open = any(float(p['positionAmt']) != 0 for p in positions_check)
                                if not position_open:
                                    old_balance = get_binance_balance()
                                    realized_pnl = 0.0
                                    try:
                                        income = safe_call(client.futures_income_history,
                                                           symbol=symbol,
                                                           incomeType='REALIZED_PNL',
                                                           limit=5)
                                        for item in income:
                                            income_time = datetime.fromtimestamp(item['time'] / 1000)
                                            if 0 <= (now - income_time).total_seconds() <= 60:
                                                realized_pnl = float(item['income'])
                                                break
                                    except:
                                        pass

                                    new_balance = get_binance_balance()
                                    balance_delta = round(new_balance - old_balance, 2)

                                    if realized_pnl == 0.0:
                                        if balance_delta > 0.01:
                                            realized_pnl = balance_delta
                                            result_type = "✅ TP Hit"
                                        elif balance_delta < -0.01:
                                            realized_pnl = balance_delta
                                            result_type = "❌ SL Hit"
                                        else:
                                            result_type = "⚠️ Unknown Result"
                                    else:
                                        result_type = "✅ TP Hit" if realized_pnl > 0 else "❌ SL Hit"

                                    signal_id = active_signal_id_dict.get(symbol, '❓')
                                    msg = (
                                        f"{result_type} (Signal #{signal_id}) at ${get_btc_price(symbol):.2f}\n"
                                        f"Pair: {symbol}\n"
                                        f"💰 {'Profit' if realized_pnl > 0 else 'Loss' if realized_pnl < 0 else 'Neutral'}: ${realized_pnl:.2f}\n"
                                        f"📦 Balance: ${new_balance:.2f}"
                                    )
                                    send_async(send_signal_alert(msg))

                                    try:
                                        close_trade(
                                            symbol,
                                            get_btc_price(symbol),
                                            realized_pnl
                                        )

                                    except Exception as e:
                                        save_error(str(e))

                                    update_daily_trade_stats('win' if realized_pnl > 0 else 'loss', abs(realized_pnl))
                                    log_trade_detail(now.strftime('%Y-%m-%d %H:%M:%S'),
                                                     signal_id, symbol, result_type,
                                                     realized_pnl, new_balance)
                                    active_signal_id_dict[symbol] = None
                                    was_open_dict[symbol] = False
                                    last_close_time_dict[symbol] = now

                        # === Cooldown Check ===
                        if last_close_time_dict[symbol] and (now - last_close_time_dict[symbol]).total_seconds() < COOLDOWN_MINUTES * 60:
                            break

                        # === Signal Generation ===
                        signal = generate_signal(symbol)
                        if signal and signal != last_trade_side_dict[symbol]:
                            if is_position_open(symbol):
                                continue
                            open_orders = safe_call(client.futures_get_open_orders, symbol=symbol)
                            has_tp_sl = any(o['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET'] for o in open_orders)
                            if has_tp_sl:
                                continue
                            quantity, raw_quantity, leverage = calculate_trade_quantity(symbol)
                            place_futures_market_order(symbol, signal, quantity, raw_quantity, leverage)
                            last_trade_side_dict[symbol] = signal
                            break  # ✅ Success, skip retry loop

                    except Exception as e:
                        if retry == 2:
                            send_async(send_signal_alert(f"🚫 Skipped {symbol} after 3 failures: {e}"))
                        else:
                            time.sleep(1)
        except Exception as e:
            send_async(send_signal_alert(f"⚠️ Main Loop Error: {e}"))
            time.sleep(10)

# === 1-Minute Status Updater Thread ===
def run_status_updater():
    while True:
        try:
            status_lines = []
            china_tz = timezone('Asia/Shanghai')
            now = datetime.now(china_tz)

            # === Save Balance to Database ===
            try:
                current_balance = get_binance_balance()

                save_balance(
                    "USDT",
                    current_balance
                )

            except Exception as e:
                save_error(str(e))

            for sym in SYMBOLS:
                if is_position_open(sym):
                    status = f"{sym}: Trade Running"
                elif last_close_time_dict[sym] and (
                    now - last_close_time_dict[sym]
                ).total_seconds() < COOLDOWN_MINUTES * 60:
                    status = f"{sym}: Cooldown"
                else:
                    status = f"{sym}: No Signal"

                status_lines.append(f"{status} [{now.strftime('%H:%M:%S')}]")

            send_async(send_status_message("\n".join(status_lines)))

        except Exception as e:
            send_async(send_signal_alert(f"⚠️ Status update error: {e}"))

        time.sleep(60)

# === Daily Summary (23:59) ===
def append_to_csv():
    daily_balance = get_binance_balance()
    net_balance = daily_trade_stats['win_balance'] - daily_trade_stats['loss_balance']
    with open('daily_trade_summary.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            daily_trade_stats['date'],
            daily_trade_stats['total_trades'],
            daily_trade_stats['wins'],
            daily_trade_stats['losses'],
            f"${net_balance:.2f}",
            f"${daily_balance:.2f}"
        ])

def run_daily_summary_task():
    send_async(send_daily_summary("✅ Daily Summary Bot is live. Will report at 23:59."))
    while True:
        china_tz = timezone('Asia/Shanghai')
        now = datetime.now(china_tz)
        if now.strftime('%H:%M') == '23:59':
            btc_price = get_btc_price('BTCUSDT')
            balance = get_binance_balance()
            net_pnl = daily_trade_stats['win_balance'] - daily_trade_stats['loss_balance']
            summary_msg = (
                f"📅 {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"💼 Balance: ${balance:.2f}\n"
                f"💵 BTC: ${btc_price:.2f}\n"
                f"📊 Trades: {daily_trade_stats['total_trades']}\n"
                f"✅ Wins: {daily_trade_stats['wins']}\n"
                f"❌ Losses: {daily_trade_stats['losses']}\n"
                f"💰 Net P&L: ${net_pnl:.2f}"
            )
            send_async(send_daily_summary(summary_msg))
            append_to_csv()
            time.sleep(60)
        time.sleep(1)

# === Start Threads ===

# Save bot startup status
try:
    update_bot_status(
        "RUNNING",
        "Crypto bot started successfully"
    )

    save_log(
        "INFO",
        "Crypto bot started"
    )

except Exception as e:
    save_error(str(e))


threading.Thread(target=run_status_updater, daemon=True).start()
threading.Thread(target=run_daily_summary_task, daemon=True).start()
run_multi_pair_strategy()

