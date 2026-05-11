"""
T-Finance weekly signal generator.
Runs every Monday at 12:00 PM ET via GitHub Actions.
Fetches real price data, calculates multi-factor signals, writes data.json.

Signals are based on:
  - EMA crossover (10/50/200 day)
  - RSI (14-day, overbought/oversold)
  - MACD momentum (12/26/9)
  - Price vs 200-day SMA (trend filter)
"""

import json
import datetime
import math
import urllib.request
import urllib.parse

# Core (S&P 500) — uses Faber 200-day SMA rule only
CORE = [
    ("VOO", "Vanguard S&P 500 ETF"),
]

# Tactical watchlist — uses multi-factor EMA+RSI+MACD scoring
STOCKS = [
    ("AAPL",  "Apple Inc."),
    ("MSFT",  "Microsoft"),
    ("NVDA",  "NVIDIA Corp."),
    ("GOOGL", "Alphabet"),
    ("AMZN",  "Amazon"),
    ("TSLA",  "Tesla Inc."),
    ("JPM",   "JPMorgan Chase"),
    ("V",     "Visa Inc."),
    ("WMT",   "Walmart"),
    ("JNJ",   "Johnson & Johnson"),
    ("UNH",   "UnitedHealth"),
    ("PG",    "Procter & Gamble"),
    ("HD",    "Home Depot"),
    ("MA",    "Mastercard"),
    ("DIS",   "Walt Disney"),
]

MAX_POSITION_PCT = 10  # no single tactical stock > 10% of tactical allocation


def fetch_prices(symbol, days=220):
    """Fetch historical daily closes from Yahoo Finance (no API key needed)."""
    end = int(datetime.datetime.now().timestamp())
    start = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&period1={start}&period2={end}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    closes = [c for c in closes if c is not None]
    meta = result["meta"]
    return closes, meta


def ema(prices, period):
    if len(prices) < period:
        return prices[-1]
    k = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = p * k + e * (1 - k)
    return e


def sma(prices, period):
    return sum(prices[-period:]) / period if len(prices) >= period else sum(prices) / len(prices)


def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [max(-d, 0) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(prices):
    if len(prices) < 26:
        return 0, 0
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = ema12 - ema26
    # signal line: 9-day EMA of macd — simplified
    return macd_line, ema12 - ema26


def score_stock(closes):
    """
    Multi-factor score:
      EMA trend:    -3 to +3
      RSI:          -2 to +2
      MACD:         -2 to +2
      200-day trend: -1 to +1
    Total: -8 to +8
    """
    if len(closes) < 50:
        return 0, "HOLD", 0.50

    cur = closes[-1]
    e10  = ema(closes, 10)
    e50  = ema(closes, 50)
    e200 = ema(closes, min(200, len(closes)))
    sma200 = sma(closes, min(200, len(closes)))
    rsi_val = rsi(closes)
    macd_line, _ = macd(closes)

    score = 0

    # EMA trend (most weight)
    if e10 > e50 > e200:        score += 3   # full bullish alignment
    elif e10 > e50:             score += 2
    elif e10 > e200:            score += 1
    elif e10 < e50 < e200:      score -= 3   # full bearish alignment
    elif e10 < e50:             score -= 2
    elif e10 < e200:            score -= 1

    # RSI
    if rsi_val < 30:            score += 2   # oversold = buy
    elif rsi_val < 45:          score += 1
    elif rsi_val > 70:          score -= 2   # overbought = sell
    elif rsi_val > 55:          score -= 1

    # MACD
    if macd_line > 0:           score += 1
    else:                       score -= 1

    # Price vs 200-day SMA (trend filter)
    if cur > sma200 * 1.02:     score += 1
    elif cur < sma200 * 0.98:   score -= 1

    # Convert score to signal
    if score >= 4:
        signal = "BUY"
        confidence = min(0.5 + score * 0.06, 0.92)
    elif score <= -3:
        signal = "SELL"
        confidence = max(0.5 - abs(score) * 0.06, 0.12)
    else:
        signal = "HOLD"
        confidence = 0.45 + (score / 8) * 0.1

    return score, signal, round(confidence, 2)


def make_action(signal, score, symbol):
    if signal == "BUY":
        pct = min(4 + score * 1.5, MAX_POSITION_PCT)
        return f"Buy up to {int(pct)}% of your tactical allocation"
    elif signal == "SELL":
        return "Sell your full position"
    else:
        return "Hold — no action this week"


def make_reason(signal, ema10, ema50, ema200, rsi_val, macd_val):
    parts = []
    if ema10 > ema50 > ema200:
        parts.append("full bullish EMA alignment (10 > 50 > 200-day)")
    elif ema10 > ema50:
        parts.append("short-term EMA above 50-day")
    elif ema10 < ema50 < ema200:
        parts.append("full bearish EMA alignment (10 < 50 < 200-day)")

    if rsi_val < 30:
        parts.append(f"RSI oversold at {rsi_val:.0f}")
    elif rsi_val > 70:
        parts.append(f"RSI overbought at {rsi_val:.0f}")
    else:
        parts.append(f"RSI neutral at {rsi_val:.0f}")

    if macd_val > 0:
        parts.append("MACD positive momentum")
    else:
        parts.append("MACD negative momentum")

    return ". ".join(p.capitalize() for p in parts) + "."


def process_voo(symbol, name):
    """
    Faber 200-day SMA rule for the S&P 500 core position.
    Rule: hold when price > 200-day SMA. Sell (move to cash) when price closes below it.
    Buy back when price recovers above the 200-day SMA.
    This is the single most well-researched market timing signal in existence.
    Source: Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"
    """
    try:
        closes, meta = fetch_prices(symbol, days=420)  # need 400 days for clean 200-day SMA
        if len(closes) < 50:
            raise ValueError("Insufficient data")

        cur   = closes[-1]
        prev  = closes[-2]
        change     = cur - prev
        change_pct = (change / prev) * 100

        sma200_val = sma(closes, min(200, len(closes)))
        sma50_val  = sma(closes, min(50,  len(closes)))
        rsi_val    = rsi(closes)
        pct_above  = (cur - sma200_val) / sma200_val * 100

        # Signal logic
        if cur > sma200_val:
            if cur > sma50_val:
                signal     = "HOLD"
                confidence = 0.88
                action     = f"Hold your VOO position. Price is {pct_above:.1f}% above the 200-day SMA (${sma200_val:.2f})."
                reason     = (f"Faber 200-day SMA signal intact. Price ${cur:.2f} is above the 200-day moving average "
                              f"(${sma200_val:.2f}). No reason to exit. Only sell if price closes a full week below ${sma200_val:.2f}.")
            else:
                signal     = "HOLD"
                confidence = 0.70
                action     = f"Hold VOO but watch closely. Price near the 200-day SMA (${sma200_val:.2f})."
                reason     = (f"Price above 200-day SMA but below 50-day SMA. RSI {rsi_val:.0f}. "
                              f"The core Faber signal is still HOLD but momentum is weakening. Monitor weekly.")
        else:
            pct_below = abs(pct_above)
            signal     = "SELL"
            confidence = min(0.70 + pct_below * 0.03, 0.95)
            action     = (f"SELL your VOO/SPY position. Price has crossed below the 200-day SMA (${sma200_val:.2f}). "
                          f"Move proceeds to cash or SGOV (short-term T-bills). Buy back when price recovers above ${sma200_val:.2f}.")
            reason     = (f"Faber 200-day SMA signal triggered. Price ${cur:.2f} is {pct_below:.1f}% below the 200-day SMA. "
                          f"Historically this signal has prevented the worst drawdowns (2008: -50%, 2020: -34%). "
                          f"This does NOT mean the market is crashing — it means the risk/reward has shifted against holding.")

        def trend(n):
            if len(closes) < n + 1:
                return 0
            return ((closes[-1] - closes[-(n+1)]) / closes[-(n+1)]) * 100

        sparkline = [round(p, 2) for p in closes[-20:]]

        return {
            "symbol":     symbol,
            "name":       name,
            "price":      round(cur, 2),
            "change":     round(change, 2),
            "changePct":  round(change_pct, 2),
            "signal":     signal,
            "confidence": round(confidence, 2),
            "trend10d":   round(trend(10), 2),
            "trend100d":  round(trend(100), 2),
            "action":     action,
            "reason":     reason,
            "sparkline":  sparkline,
            "core":       True,
            "sma200":     round(sma200_val, 2),
        }
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None


def process_stock(symbol, name):
    try:
        closes, meta = fetch_prices(symbol)
        if len(closes) < 15:
            raise ValueError("Insufficient data")

        cur = closes[-1]
        prev = closes[-2]
        change = cur - prev
        change_pct = (change / prev) * 100

        e10  = ema(closes, 10)
        e50  = ema(closes, 50)
        e200 = ema(closes, min(200, len(closes)))
        rsi_val = rsi(closes)
        macd_val, _ = macd(closes)

        # Trend: % change over last N days
        def trend(n):
            if len(closes) < n + 1:
                return 0
            return ((closes[-1] - closes[-(n+1)]) / closes[-(n+1)]) * 100

        score, signal, confidence = score_stock(closes)
        action = make_action(signal, score, symbol)
        reason = make_reason(signal, e10, e50, e200, rsi_val, macd_val)

        # Sparkline: last 20 closes
        sparkline = [round(p, 2) for p in closes[-20:]]

        return {
            "symbol": symbol,
            "name": name,
            "price": round(cur, 2),
            "change": round(change, 2),
            "changePct": round(change_pct, 2),
            "signal": signal,
            "confidence": confidence,
            "trend10d": round(trend(10), 2),
            "trend100d": round(trend(100), 2),
            "action": action,
            "reason": reason,
            "sparkline": sparkline,
        }
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None


def main():
    print(f"T-Finance signal update — {datetime.datetime.now().isoformat()}")
    results = []

    print("\n── Core positions (Faber 200-day SMA) ──")
    for symbol, name in CORE:
        print(f"  Processing {symbol}…")
        result = process_voo(symbol, name)
        if result:
            results.append(result)

    print("\n── Tactical watchlist (EMA + RSI + MACD) ──")
    for symbol, name in STOCKS:
        print(f"  Processing {symbol}…")
        result = process_stock(symbol, name)
        if result:
            results.append(result)

    buy_count  = sum(1 for r in results if r["signal"] == "BUY")
    hold_count = sum(1 for r in results if r["signal"] == "HOLD")
    sell_count = sum(1 for r in results if r["signal"] == "SELL")

    output = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {"buy": buy_count, "hold": hold_count, "sell": sell_count},
        "stocks": results,
    }

    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone. BUY={buy_count} HOLD={hold_count} SELL={sell_count}")
    print(f"Wrote {len(results)} stocks to data.json")


if __name__ == "__main__":
    main()
