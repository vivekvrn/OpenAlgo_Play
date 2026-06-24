import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import talib as tl
import yfinance as yf
from datetime import datetime, timedelta

# ── Fetch Data ─────────────────────────────────────────────────────────────
ticker = "DIXON.NS"
end   = datetime.now()
start = end - timedelta(days=400)   # extra buffer so 200 EMA is warm

df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                 end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
# yfinance >=0.2.x returns MultiIndex columns when multi-ticker or auto_adjust
if isinstance(df.columns, pd.MultiIndex):
    df = df.xs(ticker, axis=1, level=1)
df.columns = [c.lower() for c in df.columns]
df = df[["open","high","low","close","volume"]].dropna()
df.index = pd.to_datetime(df.index).tz_localize(None)
df = df.sort_index()

print(f"Fetched {len(df)} rows from {df.index[0].date()} to {df.index[-1].date()}")

# Trim to last 1 year for display
df_display = df.last("365D").copy()

close  = df["close"].values.astype(float)
high   = df["high"].values.astype(float)
low    = df["low"].values.astype(float)
volume = df["volume"].values.astype(float)
idx    = df.index

# ── TA-Lib Indicators ──────────────────────────────────────────────────────
ema20  = tl.EMA(close, timeperiod=20)
ema50  = tl.EMA(close, timeperiod=50)
ema200 = tl.EMA(close, timeperiod=200)
rsi    = tl.RSI(close, timeperiod=14)
macd_line, macd_signal, macd_hist = tl.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
adx    = tl.ADX(high, low, close, timeperiod=14)
plus_di  = tl.PLUS_DI(high, low, close, timeperiod=14)
minus_di = tl.MINUS_DI(high, low, close, timeperiod=14)
atr    = tl.ATR(high, low, close, timeperiod=14)

def s(arr):
    return pd.Series(arr, index=idx)

ema20_s   = s(ema20);   ema50_s  = s(ema50);   ema200_s = s(ema200)
rsi_s     = s(rsi);     macd_s   = s(macd_line); msig_s  = s(macd_signal)
mhist_s   = s(macd_hist); adx_s  = s(adx); pdi_s = s(plus_di); mdi_s = s(minus_di)
atr_s     = s(atr); vol_s = s(volume)

# Trim to display window
def trim(x):
    return x.loc[df_display.index]

close_d  = trim(s(close));  high_d  = trim(s(high));  low_d   = trim(s(low))
ema20_d  = trim(ema20_s);   ema50_d = trim(ema50_s);  ema200_d= trim(ema200_s)
rsi_d    = trim(rsi_s);     macd_d  = trim(macd_s);   msig_d  = trim(msig_s)
mhist_d  = trim(mhist_s);   adx_d   = trim(adx_s);   pdi_d   = trim(pdi_s)
mdi_d    = trim(mdi_s);     atr_d   = trim(atr_s);    vol_d   = trim(vol_s)

# ── Volume trend ───────────────────────────────────────────────────────────
vol_ma20 = vol_d.rolling(20).mean()
vol_ma50 = vol_d.rolling(50).mean()

# ── Support / Resistance — swing highs/lows last 60 trading days ──────────
window = 60
recent = df_display.tail(window).copy()
SWING_N = 3

def find_swings(series, n, kind="high"):
    levels = []
    arr = series.values
    for i in range(n, len(arr) - n):
        if kind == "high":
            if arr[i] == max(arr[i-n:i+n+1]):
                levels.append((series.index[i], float(arr[i])))
        else:
            if arr[i] == min(arr[i-n:i+n+1]):
                levels.append((series.index[i], float(arr[i])))
    return levels

def cluster_levels(levels, pct=0.01):
    if not levels:
        return []
    sorted_l = sorted(levels, key=lambda x: x[1])
    clusters = [[sorted_l[0]]]
    for dt, val in sorted_l[1:]:
        if abs(val - clusters[-1][-1][1]) / clusters[-1][-1][1] < pct:
            clusters[-1].append((dt, val))
        else:
            clusters.append([(dt, val)])
    return [(max(c, key=lambda x: x[0])[0],
             round(sum(v for _, v in c) / len(c), 2)) for c in clusters]

swing_highs  = find_swings(recent["high"], SWING_N, "high")
swing_lows   = find_swings(recent["low"],  SWING_N, "low")
resistances  = cluster_levels(swing_highs)
supports     = cluster_levels(swing_lows)

# ── Current values ─────────────────────────────────────────────────────────
last_close  = float(close_d.iloc[-1])
last_ema20  = float(ema20_d.iloc[-1])
last_ema50  = float(ema50_d.iloc[-1])
last_ema200 = float(ema200_d.iloc[-1])
last_rsi    = float(rsi_d.iloc[-1])
last_macd   = float(macd_d.iloc[-1])
last_msig   = float(msig_d.iloc[-1])
last_mhist  = float(mhist_d.iloc[-1])
last_adx    = float(adx_d.iloc[-1])
last_pdi    = float(pdi_d.iloc[-1])
last_mdi    = float(mdi_d.iloc[-1])
last_atr    = float(atr_d.iloc[-1])
last_vol    = float(vol_d.iloc[-1])
v20         = float(vol_ma20.iloc[-1])
v50         = float(vol_ma50.iloc[-1])
atr_pct     = last_atr / last_close * 100

# ── Print ──────────────────────────────────────────────────────────────────
SEP = "-" * 130
W   = "=" * 80

print()
print(W)
print(f"  DIXON TECHNOLOGIES (DIXON.NS)  |  Regime Analysis  |  {datetime.now().strftime('%d %b %Y')}")
print(W)

# Last 5 sessions
print()
print("LAST 5 SESSIONS — INDICATOR SNAPSHOT")
print(SEP)
print(f"{'Date':<12}{'Close':>10}{'EMA20':>10}{'EMA50':>10}{'EMA200':>11}  "
      f"{'RSI':>6}  {'MACD':>9}{'Signal':>9}{'Hist':>8}  {'ADX':>6}{'+DI':>7}{'-DI':>7}  {'ATR':>8}")
print(SEP)
for dt in close_d.index[-5:]:
    print(f"{dt.strftime('%d-%b-%y'):<12}"
          f"{close_d[dt]:>10.2f}"
          f"{ema20_d[dt]:>10.2f}"
          f"{ema50_d[dt]:>10.2f}"
          f"{ema200_d[dt]:>11.2f}  "
          f"{rsi_d[dt]:>6.1f}  "
          f"{macd_d[dt]:>9.2f}"
          f"{msig_d[dt]:>9.2f}"
          f"{mhist_d[dt]:>8.2f}  "
          f"{adx_d[dt]:>6.1f}"
          f"{pdi_d[dt]:>7.1f}"
          f"{mdi_d[dt]:>7.1f}  "
          f"{atr_d[dt]:>8.2f}")
print(SEP)

# ── Trend ─────────────────────────────────────────────────────────────────
print()
print("TREND — EMA ALIGNMENT")
print("-" * 50)
alignment = ("BULLISH  (20 > 50 > 200)" if last_ema20 > last_ema50 > last_ema200 else
             "BEARISH  (20 < 50 < 200)" if last_ema20 < last_ema50 < last_ema200 else
             "MIXED — EMAs partially aligned")
print(f"  EMA 20   : {last_ema20:>10.2f}   ({'above' if last_ema20 > last_close else 'BELOW'} price)")
print(f"  EMA 50   : {last_ema50:>10.2f}   ({'above' if last_ema50 > last_close else 'BELOW'} price)")
print(f"  EMA 200  : {last_ema200:>10.2f}   ({'above' if last_ema200 > last_close else 'BELOW'} price)")
print(f"  Stack    : {alignment}")
print(f"  20-50 spread  : {last_ema20 - last_ema50:+.2f}   |   50-200 spread: {last_ema50 - last_ema200:+.2f}")

# ── RSI ───────────────────────────────────────────────────────────────────
print()
print("MOMENTUM — RSI (14)")
print("-" * 50)
rsi_zone = ("OVERBOUGHT (>70)"       if last_rsi > 70 else
            "BULLISH ZONE (55-70)"   if last_rsi > 55 else
            "NEUTRAL (45-55)"        if last_rsi > 45 else
            "BEARISH ZONE (30-45)"   if last_rsi > 30 else
            "OVERSOLD (<30)")
rsi_5 = rsi_d.iloc[-5:]
rsi_dir = "Rising" if float(rsi_5.iloc[-1]) > float(rsi_5.iloc[0]) else "Falling"
print(f"  RSI(14)          : {last_rsi:.1f}  [{rsi_zone}]")
print(f"  5-day direction  : {rsi_dir}  ({float(rsi_5.iloc[0]):.1f} -> {float(rsi_5.iloc[-1]):.1f})")

# ── MACD ──────────────────────────────────────────────────────────────────
print()
print("MOMENTUM — MACD (12, 26, 9)")
print("-" * 50)
macd_stance = "BULLISH" if last_macd > last_msig else "BEARISH"
prev_hist   = float(mhist_d.iloc[-2])
hist_state  = ("Positive & expanding"   if last_mhist > 0 and last_mhist > prev_hist else
               "Positive & contracting" if last_mhist > 0 else
               "Negative & expanding"   if last_mhist < 0 and last_mhist < prev_hist else
               "Negative & contracting")
print(f"  MACD line        : {last_macd:>9.2f}")
print(f"  Signal line      : {last_msig:>9.2f}")
print(f"  Histogram        : {last_mhist:>9.2f}  [{hist_state}]")
print(f"  Stance           : {macd_stance}  (gap: {abs(last_macd - last_msig):.2f})")

# ── ADX ───────────────────────────────────────────────────────────────────
print()
print("TREND STRENGTH — ADX (14)")
print("-" * 50)
adx_strength = ("VERY STRONG (>40)" if last_adx > 40 else
                "STRONG (25-40)"    if last_adx > 25 else
                "MODERATE (20-25)"  if last_adx > 20 else
                "WEAK / RANGING (<20)")
di_bias = "+DI dominant (Bullish)" if last_pdi > last_mdi else "-DI dominant (Bearish)"
print(f"  ADX              : {last_adx:.1f}  [{adx_strength}]")
print(f"  +DI / -DI        : {last_pdi:.1f}  /  {last_mdi:.1f}   [{di_bias}]")
print(f"  DI spread        : {abs(last_pdi - last_mdi):.1f}")

# ── ATR ───────────────────────────────────────────────────────────────────
print()
print("VOLATILITY — ATR (14)")
print("-" * 50)
vol_regime = ("HIGH"     if atr_pct > 3 else
              "ELEVATED" if atr_pct > 2 else
              "MODERATE" if atr_pct > 1 else "LOW")
print(f"  ATR(14)          : {last_atr:.2f}  ({atr_pct:.2f}% of price)  [{vol_regime} VOLATILITY]")
print(f"  Daily range band : {last_close - last_atr:.2f}  to  {last_close + last_atr:.2f}")
print(f"  2x ATR stop (long): {last_close - 2 * last_atr:.2f}")

# ── Volume ────────────────────────────────────────────────────────────────
print()
print("VOLUME TREND")
print("-" * 50)
vol_vs_20 = (last_vol - v20) / v20 * 100
vol_20_vs_50 = (v20 - v50) / v50 * 100
vol_label = ("ACCUMULATION"  if vol_vs_20 > 10 and last_close > last_ema20 else
             "DISTRIBUTION"  if vol_vs_20 > 10 and last_close < last_ema20 else
             "DRYING UP"     if vol_vs_20 < -20 else
             "ABOVE AVERAGE" if vol_vs_20 > 0 else "BELOW AVERAGE")
print(f"  Last session     : {last_vol:>15,.0f}")
print(f"  20-day avg       : {v20:>15,.0f}   (last day {vol_vs_20:+.1f}% vs 20d avg)")
print(f"  50-day avg       : {v50:>15,.0f}   (20d avg  {vol_20_vs_50:+.1f}% vs 50d avg)")
print(f"  Volume regime    : {vol_label}")

# ── Support / Resistance ──────────────────────────────────────────────────
print()
print("SUPPORT & RESISTANCE  (last 60 trading days, 3-bar swing)")
print("-" * 50)
print(f"  Current Price  : {last_close:.2f}")
print()

res_above = sorted([(d, v) for d, v in resistances if v > last_close], key=lambda x: x[1])
res_below = sorted([(d, v) for d, v in resistances if v <= last_close], key=lambda x: x[1], reverse=True)
sup_below = sorted([(d, v) for d, v in supports if v < last_close], key=lambda x: x[1], reverse=True)
sup_above = sorted([(d, v) for d, v in supports if v >= last_close], key=lambda x: x[1])

print("  Resistance:")
if res_above:
    for d, v in res_above[:4]:
        pct = (v - last_close) / last_close * 100
        print(f"    {v:>9.2f}   (+{pct:.1f}%)   last touched {d.strftime('%d-%b')}")
else:
    print("    None above CMP — price near recent highs")

print()
print("  Support:")
if sup_below:
    for d, v in sup_below[:4]:
        pct = (last_close - v) / last_close * 100
        print(f"    {v:>9.2f}   (-{pct:.1f}%)   last touched {d.strftime('%d-%b')}")
else:
    print("    None below CMP")

# nearest levels
imm_res = res_above[0][1] if res_above else None
imm_sup = sup_below[0][1] if sup_below else None

print()
print("  Key levels summary:")
if imm_res:
    print(f"    Immediate Resistance : {imm_res:.2f}  (+{(imm_res - last_close)/last_close*100:.1f}%)")
if imm_sup:
    print(f"    Immediate Support    : {imm_sup:.2f}  (-{(last_close - imm_sup)/last_close*100:.1f}%)")
if imm_res and imm_sup:
    rr = (imm_res - last_close) / (last_close - imm_sup)
    print(f"    R:R (nearest levels) : {rr:.2f}x")

# ── Regime Scorecard ──────────────────────────────────────────────────────
bull = 0; bear = 0; flags = []

if last_close > last_ema20:  bull += 1
else: bear += 1; flags.append("Price below EMA20")
if last_close > last_ema50:  bull += 1
else: bear += 1; flags.append("Price below EMA50")
if last_close > last_ema200: bull += 1
else: bear += 1; flags.append("Price below EMA200")
if last_ema20 > last_ema50:  bull += 1
else: bear += 1; flags.append("EMA20 below EMA50")
if last_ema50 > last_ema200: bull += 1
else: bear += 1; flags.append("EMA50 below EMA200")
if last_rsi > 55:   bull += 1
elif last_rsi < 45: bear += 1; flags.append(f"RSI weak ({last_rsi:.1f})")
if last_macd > last_msig:  bull += 1
else: bear += 1; flags.append("MACD below signal")
if last_mhist > 0 and last_mhist > prev_hist: bull += 1
elif last_mhist < 0 and last_mhist < prev_hist: bear += 1
if last_pdi > last_mdi:  bull += 1
else: bear += 1; flags.append("+DI < -DI (bearish DI)")

total    = bull + bear
bull_pct = bull / total * 100

regime = ("STRONG UPTREND"                 if bull_pct >= 80 else
          "UPTREND"                         if bull_pct >= 65 else
          "MILD UPTREND / CONSOLIDATION"    if bull_pct >= 50 else
          "MILD DOWNTREND / CONSOLIDATION"  if bull_pct >= 35 else
          "DOWNTREND"                        if bull_pct >= 20 else
          "STRONG DOWNTREND")

print()
print(W)
print("  REGIME SCORECARD")
print(W)
print()
print(f"  Overall Regime   : {regime}")
print(f"  Bull signals     : {bull}/{total}  ({bull_pct:.0f}%  bullish)")
print()
print(f"  {'Indicator':<25}  {'Reading':<30}  Signal")
print(f"  {'-'*65}")
print(f"  {'Price vs EMA20':<25}  {last_close:.2f} vs {last_ema20:.2f}   {' ':<8}  {'BULL' if last_close > last_ema20 else 'BEAR'}")
print(f"  {'Price vs EMA50':<25}  {last_close:.2f} vs {last_ema50:.2f}   {' ':<8}  {'BULL' if last_close > last_ema50 else 'BEAR'}")
print(f"  {'Price vs EMA200':<25}  {last_close:.2f} vs {last_ema200:.2f}   {' ':<8}  {'BULL' if last_close > last_ema200 else 'BEAR'}")
print(f"  {'EMA20 vs EMA50':<25}  {last_ema20:.2f} vs {last_ema50:.2f}   {' ':<8}  {'BULL' if last_ema20 > last_ema50 else 'BEAR'}")
print(f"  {'EMA50 vs EMA200':<25}  {last_ema50:.2f} vs {last_ema200:.2f}  {' ':<8}  {'BULL' if last_ema50 > last_ema200 else 'BEAR'}")
print(f"  {'RSI(14)':<25}  {last_rsi:.1f}  [{rsi_zone}]   {'BULL' if last_rsi > 55 else 'BEAR' if last_rsi < 45 else 'NEUT'}")
print(f"  {'MACD vs Signal':<25}  {last_macd:.2f} vs {last_msig:.2f}   {' ':<8}  {'BULL' if last_macd > last_msig else 'BEAR'}")
print(f"  {'MACD Histogram':<25}  {last_mhist:.2f}  [{hist_state}]  {'BULL' if last_mhist > 0 and last_mhist > prev_hist else 'BEAR' if last_mhist < 0 and last_mhist < prev_hist else 'NEUT'}")
print(f"  {'+DI vs -DI (ADX)':<25}  {last_pdi:.1f} vs {last_mdi:.1f}   {' ':<8}  {'BULL' if last_pdi > last_mdi else 'BEAR'}")
print()
if flags:
    print("  Caution flags:")
    for f in flags:
        print(f"    - {f}")
    print()

# Narrative
trend_d = ("in a strong uptrend with price comfortably above all key EMAs (20/50/200)"
           if last_close > last_ema20 > last_ema50 > last_ema200 else
           "above EMA20/50 but with EMA200 still above — recovering from a deeper correction"
           if last_close > last_ema20 and last_close > last_ema50 and last_close < last_ema200 else
           "below key moving averages" if last_close < last_ema20 and last_close < last_ema50 else
           "in a mixed/transition phase")
mom_d  = (f"RSI at {last_rsi:.1f} is {'elevated — watch for overbought reversal' if last_rsi > 70 else 'healthy and trending bullish' if last_rsi > 55 else 'neutral with no strong bias' if last_rsi > 45 else 'weak — momentum deteriorating'}")
macd_d_str = ("MACD is above its signal line with a positive histogram — momentum is with the bulls"
              if last_macd > last_msig and last_mhist > 0 else
              "MACD is below signal with a negative histogram — short-term momentum is bearish"
              if last_macd < last_msig and last_mhist < 0 else
              "MACD and signal are closely aligned — watch for a decisive cross")
adx_d_str  = (f"ADX at {last_adx:.1f} {'confirms a trending environment' if last_adx > 25 else 'suggests the market is range-bound — breakout not yet confirmed'}")
vol_d_str  = (f"Volume is {vol_label.lower()}, "
              f"{'supporting the price move' if vol_label in ('ACCUMULATION','ABOVE AVERAGE') else 'raising caution about the conviction behind the move'}")

print(W)
print("  INTERPRETATION")
print(W)
print()
print(f"  Dixon Technologies is {trend_d}.")
print(f"  {mom_d}.")
print(f"  {macd_d_str}.")
print(f"  {adx_d_str}.")
print(f"  ATR({atr_pct:.2f}%) implies a typical daily swing of {last_atr:.0f} points.")
print(f"  {vol_d_str}.")
print()
if imm_res and imm_sup:
    print(f"  Nearest resistance is at {imm_res:.2f} (+{(imm_res-last_close)/last_close*100:.1f}%),")
    print(f"  nearest support at {imm_sup:.2f} (-{(last_close-imm_sup)/last_close*100:.1f}%).")
    print(f"  That gives a {rr:.2f}x reward-to-risk ratio to the nearest swing levels.")
print()
print(W)
