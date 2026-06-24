#!/usr/bin/env python3
"""
INFY EMA Crossover Backtest - Last 20 Trading Days
Exchange: NSE | Interval: Daily
Strategy: EMA(5) / EMA(13) crossover
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ── Config ───────────────────────────────────────────────────────────────────
SYMBOL         = "INFY"
EXCHANGE       = "NSE"
INTERVAL       = "D"
TRADING_DAYS   = 20
INIT_CASH      = 100_000.0   # Rs 1 lakh starting capital
FEES_PCT       = 0.00111     # 0.111% (delivery brokerage + STT)
FIXED_FEES     = 20.0        # Rs 20 per order
EMA_FAST       = 5
EMA_SLOW       = 13

# ── Data Fetch ────────────────────────────────────────────────────────────────
data = None
source_used = ""

# 1. Try OpenAlgo API
try:
    from openalgo import api as OpenAlgoAPI
    api_key = os.getenv("OPENALGO_API_KEY", "").strip().strip("'\"")
    host    = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000").strip().strip("'\"")

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=40)   # ~40 cal days → ~28 trading days buffer
    start_str  = start_date.strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")

    client = OpenAlgoAPI(api_key=api_key, host=host)
    resp   = client.history(symbol=SYMBOL, exchange=EXCHANGE,
                            interval=INTERVAL,
                            start_date=start_str, end_date=end_str)
    rows = resp.get("data", [])
    if rows:
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].sort_index()
        data = df
        source_used = "OpenAlgo"
        print(f"Fetched {len(data)} rows from OpenAlgo")
except Exception as e:
    print(f"OpenAlgo not available ({type(e).__name__}: {e})")

# 2. Fallback to yfinance
if data is None or data.empty:
    try:
        import yfinance as yf
        print(f"Fetching {SYMBOL}.NS from yfinance ...")
        ticker = yf.Ticker(f"{SYMBOL}.NS")
        df = ticker.history(period="3mo", interval="1d")
        df.columns = [c.lower() for c in df.columns]
        df.index   = pd.to_datetime(df.index).tz_localize(None)
        df         = df[["open", "high", "low", "close", "volume"]].dropna()
        data       = df
        source_used = "yfinance"
        print(f"Fetched {len(data)} rows from yfinance")
    except Exception as e:
        print(f"yfinance also failed: {e}")
        sys.exit(1)

# ── Trim to last N trading days ───────────────────────────────────────────────
data  = data.tail(TRADING_DAYS).copy()
close = data["close"]

print(f"\nData source : {source_used}")
print(f"Date range  : {data.index[0].date()} → {data.index[-1].date()}")
print(f"Trading days: {len(data)}")

# ── Indicators ────────────────────────────────────────────────────────────────
data["ema_fast"] = close.ewm(span=EMA_FAST, adjust=False).mean()
data["ema_slow"] = close.ewm(span=EMA_SLOW, adjust=False).mean()

# ── Signal Generation ─────────────────────────────────────────────────────────
data["entry"] = (data["ema_fast"] > data["ema_slow"]) & \
                (data["ema_fast"].shift(1) <= data["ema_slow"].shift(1))
data["exit"]  = (data["ema_fast"] < data["ema_slow"]) & \
                (data["ema_fast"].shift(1) >= data["ema_slow"].shift(1))
data["entry"] = data["entry"].fillna(False)
data["exit"]  = data["exit"].fillna(False)

# ── Portfolio Simulation ──────────────────────────────────────────────────────
def simulate(close_s, entries, exits, init_cash=INIT_CASH,
             fees_pct=FEES_PCT, fixed=FIXED_FEES):
    """Simple long-only equity curve simulation."""
    cash      = init_cash
    position  = 0           # shares held
    equity    = [init_cash]
    in_trade  = False
    trades    = []

    for i in range(1, len(close_s)):
        price = close_s.iloc[i]
        prev_price = close_s.iloc[i - 1]

        if entries.iloc[i] and not in_trade:
            cost      = cash * (1 - fees_pct) - fixed
            shares    = max(int(cost // price), 0)
            if shares > 0:
                spent    = shares * price * (1 + fees_pct) + fixed
                cash    -= spent
                position = shares
                in_trade = True
                buy_price = price
                buy_date  = close_s.index[i]

        elif (exits.iloc[i] or i == len(close_s) - 1) and in_trade:
            proceeds  = position * price * (1 - fees_pct) - fixed
            pnl       = proceeds - (position * buy_price * (1 + fees_pct) + fixed)
            cash     += proceeds
            trades.append({
                "entry_date":  buy_date,
                "exit_date":   close_s.index[i],
                "entry_price": buy_price,
                "exit_price":  price,
                "shares":      position,
                "pnl":         pnl,
                "return_pct":  (price / buy_price - 1) * 100,
            })
            position = 0
            in_trade = False

        total_equity = cash + position * price
        equity.append(total_equity)

    equity = pd.Series(equity, index=close_s.index)
    return equity, pd.DataFrame(trades)


# EMA Crossover
ema_equity, ema_trades = simulate(close, data["entry"], data["exit"])

# Buy & Hold — buy at Day 0 close, hold to last day
bh_shares   = max(int((INIT_CASH * (1 - FEES_PCT) - FIXED_FEES) // close.iloc[0]), 0)
bh_cost     = bh_shares * close.iloc[0] * (1 + FEES_PCT) + FIXED_FEES
bh_cash     = INIT_CASH - bh_cost
bh_equity   = bh_cash + bh_shares * close
sell_proc   = bh_shares * close.iloc[-1] * (1 - FEES_PCT) - FIXED_FEES
bh_equity.iloc[-1] = bh_cash + sell_proc
bh_pnl      = sell_proc - (bh_shares * close.iloc[0] * (1 + FEES_PCT) + FIXED_FEES)
bh_trades   = pd.DataFrame([{
    "entry_date":  close.index[0], "exit_date":  close.index[-1],
    "entry_price": close.iloc[0],  "exit_price": close.iloc[-1],
    "shares":      bh_shares,      "pnl":        bh_pnl,
    "return_pct":  (close.iloc[-1] / close.iloc[0] - 1) * 100,
}])

# ── Stats Helper ──────────────────────────────────────────────────────────────
def calc_stats(equity, trades_df):
    daily_ret   = equity.pct_change().dropna()
    total_ret   = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    max_dd      = ((equity / equity.cummax()) - 1).min() * 100
    sharpe      = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
                   if daily_ret.std() > 0 else 0.0)
    sortino     = (daily_ret.mean() / daily_ret[daily_ret < 0].std() * np.sqrt(252)
                   if len(daily_ret[daily_ret < 0]) > 0 else 0.0)
    n_trades    = len(trades_df)
    win_rate    = (trades_df["pnl"] > 0).mean() * 100 if n_trades else 0.0
    profit_fac  = (trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum() /
                   abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
                   if n_trades and (trades_df["pnl"] < 0).any() else float("inf"))
    return dict(total_ret=total_ret, max_dd=max_dd, sharpe=sharpe,
                sortino=sortino, n_trades=n_trades, win_rate=win_rate,
                profit_fac=profit_fac,
                final_value=equity.iloc[-1])

ema_stats = calc_stats(ema_equity, ema_trades)
bh_stats  = calc_stats(bh_equity,  bh_trades)

start_price = close.iloc[0]
end_price   = close.iloc[-1]
raw_change  = (end_price / start_price - 1) * 100

# ── Print Report ──────────────────────────────────────────────────────────────
SEP = "=" * 62

print(f"\n{SEP}")
print(f"  INFY Backtest — Last {TRADING_DAYS} Trading Days  ({source_used})")
print(SEP)
print(f"\n  Period    : {data.index[0].date()}  →  {data.index[-1].date()}")
print(f"  Open price: Rs {start_price:,.2f}")
print(f"  Close price: Rs {end_price:,.2f}")
print(f"  Raw price change: {raw_change:+.2f}%\n")

print(f"  {'Metric':<22} {'EMA(5/13)':>14} {'Buy & Hold':>14}")
print(f"  {'-'*22} {'-'*14} {'-'*14}")
print(f"  {'Total Return':<22} {ema_stats['total_ret']:>+13.2f}% {bh_stats['total_ret']:>+13.2f}%")
print(f"  {'Final Value (Rs)':<22} {ema_stats['final_value']:>14,.0f} {bh_stats['final_value']:>14,.0f}")
print(f"  {'Max Drawdown':<22} {ema_stats['max_dd']:>13.2f}% {bh_stats['max_dd']:>13.2f}%")
print(f"  {'Sharpe Ratio':<22} {ema_stats['sharpe']:>14.2f} {bh_stats['sharpe']:>14.2f}")
print(f"  {'Sortino Ratio':<22} {ema_stats['sortino']:>14.2f} {bh_stats['sortino']:>14.2f}")
print(f"  {'Win Rate':<22} {ema_stats['win_rate']:>13.1f}% {'N/A':>14}")
print(f"  {'Total Trades':<22} {ema_stats['n_trades']:>14} {'1':>14}")
print(f"\n{SEP}\n")

# ── Trade Log ─────────────────────────────────────────────────────────────────
if not ema_trades.empty:
    print("  EMA Crossover Trade Log:")
    print(f"  {'#':<4} {'Entry':<12} {'Exit':<12} {'Shares':>7} "
          f"{'Entry Rs':>10} {'Exit Rs':>10} {'PnL Rs':>10} {'Ret%':>8}")
    print(f"  {'-'*85}")
    for i, row in ema_trades.iterrows():
        print(f"  {i+1:<4} {str(row['entry_date'].date()):<12} "
              f"{str(row['exit_date'].date()):<12} {int(row['shares']):>7} "
              f"{row['entry_price']:>10,.2f} {row['exit_price']:>10,.2f} "
              f"{row['pnl']:>+10,.0f} {row['return_pct']:>+7.2f}%")
    print()
else:
    print("  No completed trades in this period (no EMA crossover occurred).\n")

# ── Plain-language Explanation ────────────────────────────────────────────────
print(SEP)
print("  What This Report Means (Plain Language)")
print(SEP)
print(f"""
  INFY moved from Rs {start_price:,.2f} to Rs {end_price:,.2f} over the last
  {TRADING_DAYS} trading days — a raw price change of {raw_change:+.2f}%.

  Buy & Hold (you buy on Day 1, sell on Day {TRADING_DAYS}):
    Starting capital Rs {INIT_CASH:,.0f} → Rs {bh_stats['final_value']:,.0f}
    Return: {bh_stats['total_ret']:+.2f}%  |  Max Drawdown: {bh_stats['max_dd']:.2f}%

  EMA Crossover (5/13 — buy on golden cross, sell on death cross):
    Starting capital Rs {INIT_CASH:,.0f} → Rs {ema_stats['final_value']:,.0f}
    Return: {ema_stats['total_ret']:+.2f}%  |  Trades: {ema_stats['n_trades']}  |  Win Rate: {ema_stats['win_rate']:.1f}%
    Max Drawdown: {ema_stats['max_dd']:.2f}%

  Note: With only {TRADING_DAYS} trading days, the EMA crossover may not generate
  many signals — the buy-and-hold return is your key reference for INFY's
  actual % movement during this period.
""")

# ── CSV Export ────────────────────────────────────────────────────────────────
out_dir = os.path.dirname(os.path.abspath(__file__))
trades_file = os.path.join(out_dir, "INFY_trades.csv")
ema_trades.to_csv(trades_file, index=False)
print(f"  Trade log saved → {trades_file}")

# ── Plotly Chart ──────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.65, 0.35],
    vertical_spacing=0.06,
    subplot_titles=[
        f"INFY — Price + EMA(5/13)  [{data.index[0].date()} → {data.index[-1].date()}]",
        "Equity Curve  (Rs 1 Lakh Initial Capital)"
    ]
)

# Candlestick
fig.add_trace(go.Candlestick(
    x=data.index, open=data["open"], high=data["high"],
    low=data["low"], close=close,
    name="INFY", increasing_line_color="#26a69a", decreasing_line_color="#ef5350"
), row=1, col=1)

# EMAs
fig.add_trace(go.Scatter(x=data.index, y=data["ema_fast"], name=f"EMA {EMA_FAST}",
                          line=dict(color="#ffeb3b", width=1.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=data.index, y=data["ema_slow"], name=f"EMA {EMA_SLOW}",
                          line=dict(color="#ab47bc", width=1.5)), row=1, col=1)

# Entry / Exit markers
entry_dates = data.index[data["entry"]]
exit_dates  = data.index[data["exit"]]
if len(entry_dates):
    fig.add_trace(go.Scatter(
        x=entry_dates, y=close[entry_dates],
        mode="markers", marker=dict(symbol="triangle-up", color="#00e676", size=12),
        name="Entry"
    ), row=1, col=1)
if len(exit_dates):
    fig.add_trace(go.Scatter(
        x=exit_dates, y=close[exit_dates],
        mode="markers", marker=dict(symbol="triangle-down", color="#ff1744", size=12),
        name="Exit"
    ), row=1, col=1)

# Equity curves
fig.add_trace(go.Scatter(x=ema_equity.index, y=ema_equity,
                          name="EMA Strategy", line=dict(color="#29b6f6", width=2)),
              row=2, col=1)
fig.add_trace(go.Scatter(x=bh_equity.index, y=bh_equity,
                          name="Buy & Hold", line=dict(color="#ff8f00", width=2,
                                                       dash="dash")),
              row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    title=dict(text=(
        f"INFY | Last {TRADING_DAYS} Trading Days | "
        f"B&H: {bh_stats['total_ret']:+.2f}%  |  "
        f"EMA: {ema_stats['total_ret']:+.2f}%"
    ), font_size=14),
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=700,
)
fig.update_yaxes(tickprefix="Rs ", row=2, col=1)

chart_file = os.path.join(out_dir, "INFY_backtest_chart.html")
fig.write_html(chart_file)
print(f"  Chart saved      → {chart_file}\n")
fig.show()
