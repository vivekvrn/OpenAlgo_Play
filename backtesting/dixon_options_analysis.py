"""
Dixon Technologies — Options Intelligence Analysis
Fetches live option chain via Dhan API, computes OI walls, GEX, PCR,
Max Pain, ATM IV, 10D/20D HV, vol skew/surface, and synthesises a thesis.
"""
import os
import sys
import math
import time
import warnings
warnings.filterwarnings("ignore")

# Ensure project root is on sys.path for imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=False)

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, date as _date
from scipy.stats import norm

# ── Auth & broker imports ──────────────────────────────────────────────────
from database.auth_db import get_auth_token
from broker.dhan.api.data import BrokerData
from database.token_db import get_token

# ── Configuration ──────────────────────────────────────────────────────────
SYMBOL       = "DIXON"
EXCHANGE     = "NFO"
LOT_SIZE     = 50
RISK_FREE    = 0.065          # 6.5% Indian G-sec
YF_TICKER    = "DIXON.NS"
FRONT_EXPIRY = "30-JUN-26"
NEXT_EXPIRY  = "28-JUL-26"
FAR_EXPIRY   = "25-AUG-26"

W   = "=" * 80
SEP = "-" * 80

# ── Step 1: Get auth token & initialise broker ─────────────────────────────
print(f"\n{W}")
print("  DIXON TECHNOLOGIES — OPTIONS INTELLIGENCE ANALYSIS")
print(f"  {datetime.now().strftime('%d %b %Y  %H:%M')}")
print(W)

auth_token = get_auth_token("Vivek")
if not auth_token:
    print("ERROR: No valid Dhan auth token. Please log in through OpenAlgo first.")
    sys.exit(1)

dh = BrokerData(auth_token)
print(f"\nDhan session: active  |  lot size: {LOT_SIZE}")

# ── Step 2: Fetch underlying spot from Dhan ────────────────────────────────
print("\nFetching DIXON spot price ...")
try:
    spot_q = dh.get_quotes("DIXON", "NSE")
    spot   = spot_q.get("ltp", 0.0)
    print(f"  Spot price: {spot:.2f}")
except Exception as e:
    print(f"  Spot fetch failed ({e}) — falling back to yfinance")
    _yf = yf.download(YF_TICKER, period="2d", progress=False, auto_adjust=True)
    if isinstance(_yf.columns, pd.MultiIndex):
        _yf = _yf.xs(YF_TICKER, axis=1, level=1)
    spot = float(_yf["close"].iloc[-1])
    print(f"  Spot (yfinance): {spot:.2f}")

# ── Step 3: Historical Volatility from yfinance ────────────────────────────
print("\nCalculating Historical Volatility ...")
hv_df = yf.download(YF_TICKER, period="90d", progress=False, auto_adjust=True)
if isinstance(hv_df.columns, pd.MultiIndex):
    hv_df = hv_df.xs(YF_TICKER, axis=1, level=1)
hv_close = hv_df["close"].dropna()
log_ret   = np.log(hv_close / hv_close.shift(1)).dropna()

def ann_hv(n):
    if len(log_ret) < n:
        return None
    return round(float(np.std(log_ret.iloc[-n:], ddof=1) * math.sqrt(252) * 100), 2)

hv_10 = ann_hv(10)
hv_20 = ann_hv(20)
hv_30 = ann_hv(30)
print(f"  HV-10 : {hv_10:.2f}%")
print(f"  HV-20 : {hv_20:.2f}%")
print(f"  HV-30 : {hv_30:.2f}%")

# ── Step 4: Load strikes from master contract DB ──────────────────────────
import sqlite3
DB_PATH = os.path.join(PROJ, "db", "openalgo.db")

def load_chain_symbols(expiry_db: str):
    """Return DataFrame of CE/PE symbols+tokens for given expiry."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
        SELECT symbol, token, strike, instrumenttype
        FROM symtoken
        WHERE symbol LIKE ? AND exchange=? AND expiry=?
          AND instrumenttype IN ('CE','PE')
        ORDER BY strike, instrumenttype
    """, (f"{SYMBOL}%", EXCHANGE, expiry_db))
    rows  = cur.fetchall()
    conn.close()
    cols  = ["symbol", "token", "strike", "type"]
    return pd.DataFrame(rows, columns=cols)

print("\nLoading master contract strikes ...")
df_front = load_chain_symbols(FRONT_EXPIRY)
df_next  = load_chain_symbols(NEXT_EXPIRY)
df_far   = load_chain_symbols(FAR_EXPIRY)
print(f"  Front ({FRONT_EXPIRY}): {len(df_front)//2} strikes")
print(f"  Next  ({NEXT_EXPIRY}): {len(df_next)//2} strikes")
print(f"  Far   ({FAR_EXPIRY}): {len(df_far)//2} strikes")

# ── Step 5: Batch fetch live quotes for all expiries ─────────────────────
def fetch_quotes_for_chain(df_symbols: pd.DataFrame, label: str) -> dict:
    """Returns {symbol: {ltp, oi, volume}} via Dhan multiquotes."""
    syms = [{"symbol": row["symbol"], "exchange": EXCHANGE}
            for _, row in df_symbols.iterrows()]
    print(f"  Fetching {len(syms)} quotes for {label} ...")
    time.sleep(1.5)          # respect Dhan 1 req/sec rate limit
    try:
        results = dh.get_multiquotes(syms)
        qmap = {}
        for r in results:
            sym = r.get("symbol")
            if sym and "data" in r:
                qmap[sym] = r["data"]
        print(f"    Got data for {len(qmap)} / {len(syms)} symbols")
        return qmap
    except Exception as e:
        print(f"    Multiquote error: {e}")
        return {}

print("\nFetching live option quotes ...")
qmap_front = fetch_quotes_for_chain(df_front, f"front {FRONT_EXPIRY}")
qmap_next  = fetch_quotes_for_chain(df_next,  f"next {NEXT_EXPIRY}")
qmap_far   = fetch_quotes_for_chain(df_far,   f"far {FAR_EXPIRY}")

# ── Step 6: Build structured chain DataFrame ─────────────────────────────
def build_chain(df_symbols: pd.DataFrame, qmap: dict, expiry_str: str) -> pd.DataFrame:
    """Pivot into one row per strike with CE/PE columns."""
    rows = []
    strikes = sorted(df_symbols["strike"].unique())
    for sk in strikes:
        ce_sym = df_symbols.loc[(df_symbols["strike"] == sk) & (df_symbols["type"] == "CE"), "symbol"]
        pe_sym = df_symbols.loc[(df_symbols["strike"] == sk) & (df_symbols["type"] == "PE"), "symbol"]
        if ce_sym.empty or pe_sym.empty:
            continue
        ce_sym = ce_sym.iloc[0];  pe_sym = pe_sym.iloc[0]
        ce_q   = qmap.get(ce_sym, {});  pe_q = qmap.get(pe_sym, {})
        rows.append({
            "strike"   : sk,
            "ce_ltp"   : ce_q.get("ltp", 0),
            "ce_oi"    : ce_q.get("oi",  0),
            "ce_vol"   : ce_q.get("volume", 0),
            "pe_ltp"   : pe_q.get("ltp", 0),
            "pe_oi"    : pe_q.get("oi",  0),
            "pe_vol"   : pe_q.get("volume", 0),
            "ce_sym"   : ce_sym,
            "pe_sym"   : pe_sym,
        })
    df = pd.DataFrame(rows)
    df["net_oi"] = df["pe_oi"] - df["ce_oi"]
    return df

chain_front = build_chain(df_front, qmap_front, FRONT_EXPIRY)
chain_next  = build_chain(df_next,  qmap_next,  NEXT_EXPIRY)
chain_far   = build_chain(df_far,   qmap_far,   FAR_EXPIRY)

# Remove strikes with zero OI on both sides (illiquid far OTM)
def trim_chain(df, min_oi=10):
    return df[(df["ce_oi"] > min_oi) | (df["pe_oi"] > min_oi)].reset_index(drop=True)

chain_front = trim_chain(chain_front)
chain_next  = trim_chain(chain_next)
chain_far   = trim_chain(chain_far)
print(f"\n  Active strikes — front:{len(chain_front)}  next:{len(chain_next)}  far:{len(chain_far)}")

# ── Step 7: ATM strike ─────────────────────────────────────────────────────
def find_atm(chain: pd.DataFrame, spot: float) -> float:
    return float(chain["strike"].iloc[(chain["strike"] - spot).abs().argsort().iloc[0]])

atm = find_atm(chain_front, spot)
print(f"\n  ATM strike (front): {atm}")

# ── Step 8: Black-Scholes IV & Greeks ─────────────────────────────────────
def dte_years(expiry_db: str) -> float:
    exp_date = datetime.strptime(expiry_db, "%d-%b-%y").date()
    delta    = (exp_date - _date.today()).days
    return max(delta, 1) / 365.0

def bs_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm.pdf(d1) / (S * sigma * math.sqrt(T))

def bs_iv(price, S, K, T, r, flag, tol=1e-6, max_iter=200):
    """Binary-search IV from BS price."""
    if price <= 0 or T <= 0:
        return None
    intrinsic = max(S - K, 0) if flag == "c" else max(K - S, 0)
    if price < intrinsic:
        return None
    lo, hi = 0.001, 20.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        d1  = (math.log(S / K) + (r + 0.5 * mid**2) * T) / (mid * math.sqrt(T))
        d2  = d1 - mid * math.sqrt(T)
        if flag == "c":
            theo = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        else:
            theo = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        if abs(theo - price) < tol:
            return mid
        if theo < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

# ── Step 9: Compute IV + GEX for front chain ──────────────────────────────
T_front = dte_years(FRONT_EXPIRY)
T_next  = dte_years(NEXT_EXPIRY)
T_far   = dte_years(FAR_EXPIRY)
print(f"\n  DTE — front: {round(T_front*365)}d  next: {round(T_next*365)}d  far: {round(T_far*365)}d")

def enrich_chain(chain: pd.DataFrame, T: float) -> pd.DataFrame:
    """Add iv_ce, iv_pe, gamma_ce, gamma_pe, ce_gex, pe_gex, net_gex columns."""
    iv_ce_list = []; iv_pe_list = []
    gc_list    = []; gp_list    = []
    for _, row in chain.iterrows():
        K   = float(row["strike"])
        # CE IV
        iv_c = bs_iv(float(row["ce_ltp"]), spot, K, T, RISK_FREE, "c") if row["ce_ltp"] > 0.5 else None
        # PE IV
        iv_p = bs_iv(float(row["pe_ltp"]), spot, K, T, RISK_FREE, "p") if row["pe_ltp"] > 0.5 else None
        # Gamma
        sigma_c = iv_c if iv_c else 0.0
        sigma_p = iv_p if iv_p else 0.0
        gc = bs_gamma(spot, K, T, RISK_FREE, sigma_c) if sigma_c > 0 else 0.0
        gp = bs_gamma(spot, K, T, RISK_FREE, sigma_p) if sigma_p > 0 else 0.0
        iv_ce_list.append(round(iv_c * 100, 2) if iv_c else None)
        iv_pe_list.append(round(iv_p * 100, 2) if iv_p else None)
        gc_list.append(gc);  gp_list.append(gp)

    chain = chain.copy()
    chain["iv_ce"]   = iv_ce_list
    chain["iv_pe"]   = iv_pe_list
    chain["gamma_c"] = gc_list
    chain["gamma_p"] = gp_list
    # GEX = gamma × OI × lot_size  (CE positive, PE negative for market-maker)
    chain["ce_gex"]  = chain["gamma_c"] * chain["ce_oi"] * LOT_SIZE
    chain["pe_gex"]  = chain["gamma_p"] * chain["pe_oi"] * LOT_SIZE
    chain["net_gex"] = chain["ce_gex"] - chain["pe_gex"]
    return chain

print("\nComputing IV and GEX (front expiry) ...")
chain_front = enrich_chain(chain_front, T_front)
print("  Front chain enriched.")
print("Computing IV for next/far expiries ...")
chain_next  = enrich_chain(chain_next,  T_next)
chain_far   = enrich_chain(chain_far,   T_far)
print("  Multi-expiry chains enriched.")

# ── Step 10: PCR ──────────────────────────────────────────────────────────
total_ce_oi = chain_front["ce_oi"].sum()
total_pe_oi = chain_front["pe_oi"].sum()
pcr_oi      = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0
total_ce_vol= chain_front["ce_vol"].sum()
total_pe_vol= chain_front["pe_vol"].sum()
pcr_vol     = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 0

# ── Step 11: Max Pain ─────────────────────────────────────────────────────
def calc_max_pain(chain: pd.DataFrame) -> float:
    strikes = chain["strike"].values
    ce_ois  = chain["ce_oi"].values
    pe_ois  = chain["pe_oi"].values
    min_pain = float("inf"); max_pain_strike = 0
    for cs in strikes:
        ce_pain = sum((cs - sk) * oi for sk, oi in zip(strikes, ce_ois) if cs > sk and oi > 0)
        pe_pain = sum((sk - cs) * oi for sk, oi in zip(strikes, pe_ois) if cs < sk and oi > 0)
        total   = ce_pain + pe_pain
        if total < min_pain:
            min_pain = total; max_pain_strike = cs
    return max_pain_strike

max_pain = calc_max_pain(chain_front)

# ── Step 12: OI Walls ─────────────────────────────────────────────────────
call_wall_strike = int(chain_front.loc[chain_front["ce_oi"].idxmax(), "strike"])
put_wall_strike  = int(chain_front.loc[chain_front["pe_oi"].idxmax(), "strike"])

# Top-3 OI strikes for CE and PE
top3_ce = chain_front.nlargest(3, "ce_oi")[["strike","ce_oi"]].values
top3_pe = chain_front.nlargest(3, "pe_oi")[["strike","pe_oi"]].values

# ── Step 13: GEX signals ──────────────────────────────────────────────────
total_net_gex = chain_front["net_gex"].sum()
gex_call_wall = int(chain_front.loc[chain_front["ce_gex"].idxmax(), "strike"])
gex_put_wall  = int(chain_front.loc[chain_front["pe_gex"].idxmax(), "strike"])

# Gamma flip: closest strike to spot where net_gex changes sign
sorted_chain  = chain_front.sort_values("strike")
gamma_flip    = None
for i in range(len(sorted_chain) - 1):
    a = sorted_chain.iloc[i]; b = sorted_chain.iloc[i+1]
    if (a["net_gex"] >= 0) != (b["net_gex"] >= 0):
        if a["net_gex"] != b["net_gex"]:
            flip = a["strike"] + (b["strike"] - a["strike"]) * (-a["net_gex"]) / (b["net_gex"] - a["net_gex"])
            gamma_flip = round(flip / 100) * 100
        else:
            gamma_flip = (a["strike"] + b["strike"]) // 2
        break

# ── Step 14: ATM IV ───────────────────────────────────────────────────────
atm_row     = chain_front[chain_front["strike"] == atm]
atm_ce_iv   = float(atm_row["iv_ce"].iloc[0]) if not atm_row.empty and atm_row["iv_ce"].iloc[0] else None
atm_pe_iv   = float(atm_row["iv_pe"].iloc[0]) if not atm_row.empty and atm_row["iv_pe"].iloc[0] else None
atm_iv      = None
if atm_ce_iv and atm_pe_iv:
    atm_iv = round((atm_ce_iv + atm_pe_iv) / 2, 2)
elif atm_ce_iv:
    atm_iv = atm_ce_iv
elif atm_pe_iv:
    atm_iv = atm_pe_iv

# ── Step 15: Vol Skew ─────────────────────────────────────────────────────
# Collect IV at each strike where both CE and PE IV are available
skew_data = chain_front[chain_front["iv_ce"].notna() & chain_front["iv_pe"].notna()].copy()
skew_data["moneyness_pct"] = ((skew_data["strike"] - spot) / spot * 100).round(1)
skew_data["avg_iv"]        = (skew_data["iv_ce"] + skew_data["iv_pe"]) / 2

# 5% OTM levels
otm5_put_strike  = float(chain_front["strike"].iloc[(chain_front["strike"] - spot * 0.95).abs().argsort().iloc[0]])
otm5_call_strike = float(chain_front["strike"].iloc[(chain_front["strike"] - spot * 1.05).abs().argsort().iloc[0]])
otm10_put_strike = float(chain_front["strike"].iloc[(chain_front["strike"] - spot * 0.90).abs().argsort().iloc[0]])
otm10_call_strike= float(chain_front["strike"].iloc[(chain_front["strike"] - spot * 1.10).abs().argsort().iloc[0]])

def get_iv(chain, strike, side):
    row = chain[chain["strike"] == strike]
    if row.empty: return None
    col = "iv_pe" if side == "put" else "iv_ce"
    val = row[col].iloc[0]
    return float(val) if val else None

iv_5p  = get_iv(chain_front, otm5_put_strike,  "put")
iv_5c  = get_iv(chain_front, otm5_call_strike, "call")
iv_10p = get_iv(chain_front, otm10_put_strike, "put")
iv_10c = get_iv(chain_front, otm10_call_strike,"call")

skew_5  = round(iv_5p  - iv_5c,  2) if iv_5p  and iv_5c  else None
skew_10 = round(iv_10p - iv_10c, 2) if iv_10p and iv_10c else None
risk_rev_25 = skew_5   # simplified risk reversal using 5% OTM

# ── Step 16: Vol Term Structure (ATM IV across expiries) ─────────────────
def get_atm_iv_for_chain(chain, spot):
    atm_sk = float(chain["strike"].iloc[(chain["strike"] - spot).abs().argsort().iloc[0]])
    r = chain[chain["strike"] == atm_sk]
    if r.empty: return None, atm_sk
    civ = r["iv_ce"].iloc[0]; piv = r["iv_pe"].iloc[0]
    if civ and piv:
        return round((float(civ)+float(piv))/2, 2), atm_sk
    return float(civ or piv or 0) or None, atm_sk

atm_iv_front, _ = get_atm_iv_for_chain(chain_front, spot)
atm_iv_next,  _ = get_atm_iv_for_chain(chain_next,  spot)
atm_iv_far,   _ = get_atm_iv_for_chain(chain_far,   spot)

term_slope_fn = round(atm_iv_next - atm_iv_front, 2) if atm_iv_next and atm_iv_front else None
backwardation  = term_slope_fn is not None and term_slope_fn < -2.0

# ── Step 17: Straddle premium & range ────────────────────────────────────
atm_ce_ltp = float(atm_row["ce_ltp"].iloc[0]) if not atm_row.empty else 0
atm_pe_ltp = float(atm_row["pe_ltp"].iloc[0]) if not atm_row.empty else 0
straddle   = round(atm_ce_ltp + atm_pe_ltp, 2)
straddle_range_lo = round(spot - straddle, 0)
straddle_range_hi = round(spot + straddle, 0)

# IV-based 1-sigma range
if atm_iv and T_front:
    sigma_pts = round(spot * (atm_iv/100) * math.sqrt(T_front), 0)
    iv_range_lo = round(spot - sigma_pts, 0)
    iv_range_hi = round(spot + sigma_pts, 0)
else:
    sigma_pts = iv_range_lo = iv_range_hi = None

# ── Step 18: IV / HV spread ───────────────────────────────────────────────
iv_hv20_spread = round(atm_iv - hv_20, 2) if atm_iv and hv_20 else None
iv_hv10_spread = round(atm_iv - hv_10, 2) if atm_iv and hv_10 else None
iv_premium_pct = round((atm_iv / hv_20 - 1) * 100, 1) if atm_iv and hv_20 else None

# ── Step 19: OI Build-up / Change momentum ────────────────────────────────
# Identify strikes with high OI concentration (top-5 CE and PE)
top5_ce_oi = chain_front.nlargest(5, "ce_oi")[["strike","ce_oi","ce_vol"]].copy()
top5_pe_oi = chain_front.nlargest(5, "pe_oi")[["strike","pe_oi","pe_vol"]].copy()

# PCR by moneyness bucket (ITM / ATM ±5% / OTM)
atm_band = chain_front[(chain_front["strike"] >= spot * 0.975) & (chain_front["strike"] <= spot * 1.025)]
otm_calls = chain_front[chain_front["strike"] > spot * 1.025]
otm_puts  = chain_front[chain_front["strike"] < spot * 0.975]
pcr_atm   = atm_band["pe_oi"].sum() / atm_band["ce_oi"].sum()   if atm_band["ce_oi"].sum() > 0 else 0
pcr_otm   = otm_puts["pe_oi"].sum() / otm_calls["ce_oi"].sum()  if otm_calls["ce_oi"].sum() > 0 else 0

# ══════════════════════════════════════════════════════════════════════════
# PRINT REPORT
# ══════════════════════════════════════════════════════════════════════════

print(f"\n{W}")
print("  OPTION CHAIN — FRONT EXPIRY SNAPSHOT  (30 JUN 2026)")
print(W)

# Print top-20 strikes centred around ATM
atm_idx   = chain_front[chain_front["strike"] == atm].index[0] if atm in chain_front["strike"].values else 0
lo_idx    = max(0, atm_idx - 8)
hi_idx    = min(len(chain_front)-1, atm_idx + 8)
display   = chain_front.iloc[lo_idx:hi_idx+1]

print(f"\n{'Strike':>9} | {'CE OI':>9} {'CE Vol':>8} {'CE LTP':>8} {'CE IV%':>7} | {'ATM':^5} | {'PE IV%':>7} {'PE LTP':>8} {'PE Vol':>8} {'PE OI':>9}")
print("-"*92)
for _, r in display.iterrows():
    marker = "<ATM>" if r["strike"] == atm else "     "
    civ = f"{r['iv_ce']:.1f}" if r["iv_ce"] else "  ---"
    piv = f"{r['iv_pe']:.1f}" if r["iv_pe"] else "  ---"
    print(f"{int(r['strike']):>9} | {int(r['ce_oi']):>9,} {int(r['ce_vol']):>8,} {r['ce_ltp']:>8.2f} {civ:>7} | {marker} | {piv:>7} {r['pe_ltp']:>8.2f} {int(r['pe_vol']):>8,} {int(r['pe_oi']):>9,}")
print("-"*92)

# ── PCR ──────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("PUT-CALL RATIO")
print(SEP)
print(f"  PCR (OI)         : {pcr_oi:.3f}   ({total_pe_oi:,} PE OI  /  {total_ce_oi:,} CE OI)")
print(f"  PCR (Volume)     : {pcr_vol:.3f}   ({total_pe_vol:,} PE vol / {total_ce_vol:,} CE vol)")
print(f"  PCR ATM band     : {pcr_atm:.3f}   (±2.5% of spot)")
print(f"  PCR OTM only     : {pcr_otm:.3f}   (>2.5% OTM each side)")
pcr_signal = ("BULLISH (put hedging dominant, PCR >1.2)" if pcr_oi > 1.2 else
              "BEARISH (call selling dominant, PCR <0.8)" if pcr_oi < 0.8 else
              "NEUTRAL (balanced positioning)")
print(f"  Interpretation   : {pcr_signal}")

# ── Max Pain ──────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("MAX PAIN")
print(SEP)
print(f"  Max Pain Strike  : {max_pain:.0f}")
print(f"  Current Spot     : {spot:.2f}")
mp_dist = round((spot - max_pain) / spot * 100, 2)
print(f"  Spot vs Max Pain : {mp_dist:+.2f}%  ({'above' if spot > max_pain else 'below'} max pain)")
mp_signal = ("Expiry magnetic pull likely DOWN" if spot > max_pain else
             "Expiry magnetic pull likely UP"   if spot < max_pain else "At max pain")
print(f"  Signal           : {mp_signal}")

# ── OI Walls ──────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("OI WALLS")
print(SEP)
print(f"  Call Wall (highest CE OI) : {call_wall_strike}   ({chain_front.loc[chain_front['ce_oi'].idxmax(), 'ce_oi']:,} lots)")
print(f"  Put Wall  (highest PE OI) : {put_wall_strike}   ({chain_front.loc[chain_front['pe_oi'].idxmax(), 'pe_oi']:,} lots)")
print()
print("  Top-3 CE OI strikes (resistance):")
for sk, oi in top3_ce:
    pct = (sk - spot) / spot * 100
    print(f"    {int(sk):>9}  ({pct:+.1f}%)   OI: {int(oi):,}")
print()
print("  Top-3 PE OI strikes (support):")
for sk, oi in top3_pe:
    pct = (sk - spot) / spot * 100
    print(f"    {int(sk):>9}  ({pct:+.1f}%)   OI: {int(oi):,}")

# ── GEX ──────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("GAMMA EXPOSURE (GEX)")
print(SEP)
print(f"  Total Net GEX    : {total_net_gex:>12.2f}")
gex_sign = "POSITIVE (dealers long gamma — expect mean-reversion, range-bound)" if total_net_gex > 0 else "NEGATIVE (dealers short gamma — expect amplified moves, trending)"
print(f"  GEX Regime       : {gex_sign}")
print(f"  GEX Call Wall    : {gex_call_wall}  (peak dealer long gamma — strong resistance)")
print(f"  GEX Put Wall     : {gex_put_wall}  (peak dealer long gamma — strong support)")
if gamma_flip:
    flip_dist = round((spot - gamma_flip) / spot * 100, 2)
    print(f"  Gamma Flip Level : {gamma_flip}  (spot is {flip_dist:+.2f}% {'above' if spot > gamma_flip else 'below'} flip)")
    print(f"  {'ABOVE gamma flip — positive GEX regime active' if spot > gamma_flip else 'BELOW gamma flip — negative GEX, directional volatility expected'}")
else:
    print("  Gamma Flip Level : could not compute (OI thin at boundaries)")

# ── ATM IV ────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("IMPLIED VOLATILITY — ATM")
print(SEP)
print(f"  ATM Strike       : {atm:.0f}")
print(f"  ATM CE IV        : {atm_ce_iv:.2f}%" if atm_ce_iv else "  ATM CE IV        : ---")
print(f"  ATM PE IV        : {atm_pe_iv:.2f}%" if atm_pe_iv else "  ATM PE IV        : ---")
print(f"  ATM IV (avg)     : {atm_iv:.2f}%" if atm_iv else "  ATM IV           : unavailable")

# ── HV vs IV ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("IV vs HISTORICAL VOLATILITY")
print(SEP)
print(f"  {'Metric':<25} {'Value':>8}")
print(f"  {'-'*35}")
print(f"  {'HV-10 (annualised)':<25} {hv_10:>7.2f}%")
print(f"  {'HV-20 (annualised)':<25} {hv_20:>7.2f}%")
print(f"  {'HV-30 (annualised)':<25} {hv_30:>7.2f}%")
print(f"  {'ATM IV (front expiry)':<25} {atm_iv if atm_iv else 'N/A':>7}" + ("%" if atm_iv else ""))
if iv_hv20_spread is not None:
    print(f"  {'IV - HV20 spread':<25} {iv_hv20_spread:>+7.2f}%")
if iv_premium_pct is not None:
    richness = "RICH" if iv_premium_pct > 20 else "FAIR" if iv_premium_pct > -10 else "CHEAP"
    print(f"  {'IV/HV20 premium':<25} {iv_premium_pct:>+7.1f}%  [{richness}]")

# ── Vol Skew ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("VOL SKEW / SMILE")
print(SEP)
print(f"  ATM IV           : {atm_iv:.2f}%" if atm_iv else "  ATM IV: N/A")
print()
print(f"  {'Level':<28} {'Put IV':>8} {'Call IV':>9} {'Skew (P-C)':>12}")
print(f"  {'-'*60}")
if iv_10p and iv_10c:
    print(f"  {'10% OTM (90% / 110%)':<28} {iv_10p:>8.2f}%  {iv_10c:>8.2f}%  {skew_10:>+10.2f}")
if iv_5p and iv_5c:
    print(f"  {'5% OTM  (95% / 105%)':<28} {iv_5p:>8.2f}%  {iv_5c:>8.2f}%  {skew_5:>+10.2f}")
if atm_iv:
    print(f"  {'ATM (100%)':<28} {atm_iv:>8.2f}%  {atm_iv:>8.2f}%  {'0.00':>10}")
print()
if skew_5 is not None:
    if skew_5 > 5:
        skew_desc = "STEEP PUT SKEW — high demand for downside protection (fear/hedging dominant)"
    elif skew_5 > 2:
        skew_desc = "MODERATE PUT SKEW — normal protective positioning"
    elif skew_5 > 0:
        skew_desc = "MILD PUT SKEW — balanced with slight downside bias"
    elif skew_5 < -3:
        skew_desc = "CALL SKEW — unusual, suggests strong upside demand / short squeeze risk"
    else:
        skew_desc = "NEAR-FLAT SKEW — market makers see balanced risk both ways"
    print(f"  Skew Signal: {skew_desc}")

# Smile shape
if len(skew_data) >= 4:
    print()
    print("  IV Smile (selected strikes):")
    print(f"  {'Strike':>9}  {'Moneyness':>10}  {'CE IV':>8}  {'PE IV':>8}  {'Avg IV':>8}")
    nearby = skew_data[(skew_data["strike"] >= spot*0.85) & (skew_data["strike"] <= spot*1.15)]
    for _, r in nearby.iterrows():
        mk = f"{r['moneyness_pct']:+.1f}%"
        civ = f"{r['iv_ce']:.1f}%" if r["iv_ce"] else "  ---"
        piv = f"{r['iv_pe']:.1f}%" if r["iv_pe"] else "  ---"
        aiv = f"{r['avg_iv']:.1f}%"
        mrk = " <-- ATM" if r["strike"] == atm else ""
        print(f"  {int(r['strike']):>9}  {mk:>10}  {civ:>8}  {piv:>8}  {aiv:>8}{mrk}")

# ── Vol Term Structure ────────────────────────────────────────────────────
print(f"\n{SEP}")
print("VOL TERM STRUCTURE")
print(SEP)
print(f"  {'Expiry':<15} {'DTE':>5}  {'ATM IV':>9}")
print(f"  {'-'*35}")
entries = [(FRONT_EXPIRY, round(T_front*365), atm_iv_front),
           (NEXT_EXPIRY,  round(T_next*365),  atm_iv_next),
           (FAR_EXPIRY,   round(T_far*365),   atm_iv_far)]
for exp, dte, iv in entries:
    iv_str = f"{iv:.2f}%" if iv else "  N/A "
    print(f"  {exp:<15} {dte:>5}  {iv_str:>9}")

if term_slope_fn is not None:
    print()
    if backwardation:
        print(f"  BACKWARDATION detected: near-term IV {abs(term_slope_fn):.1f}% above next expiry")
        print("  Possible event risk (results, news) or expiry pinning effect in front month")
    elif term_slope_fn > 0:
        print(f"  Normal contango: IV rises {term_slope_fn:.1f}% from front to next expiry")
    else:
        print(f"  Flat term structure: term slope = {term_slope_fn:+.1f}%")

# ── Straddle / Range ──────────────────────────────────────────────────────
print(f"\n{SEP}")
print("STRADDLE PRICING & PROBABLE RANGE (front expiry)")
print(SEP)
print(f"  ATM Strike         : {atm:.0f}")
print(f"  ATM CE LTP         : {atm_ce_ltp:.2f}")
print(f"  ATM PE LTP         : {atm_pe_ltp:.2f}")
print(f"  Straddle Premium   : {straddle:.2f}  ({round(straddle/spot*100,2):.2f}% of spot)")
print(f"  Straddle Range     : {straddle_range_lo:.0f}  –  {straddle_range_hi:.0f}")
if sigma_pts:
    print(f"  IV 1-sigma Range   : {iv_range_lo:.0f}  –  {iv_range_hi:.0f}  ({int(sigma_pts)} pts each side)")

# ── Top-5 OI build-up ─────────────────────────────────────────────────────
print(f"\n{SEP}")
print("OI BUILD-UP — KEY STRIKE CONCENTRATION")
print(SEP)
print(f"\n  Top-5 CE (Call) OI  [{FRONT_EXPIRY}]:")
print(f"  {'Strike':>9}  {'OI (lots)':>12}  {'OI Vol':>12}  {'vs Spot':>8}  {'CE LTP':>8}")
for _, r in top5_ce_oi.iterrows():
    sk = r["strike"]; oi = r["ce_oi"]; vol = r["ce_vol"]
    pct = (sk - spot) / spot * 100
    ltp = float(chain_front.loc[chain_front["strike"] == sk, "ce_ltp"].iloc[0])
    print(f"  {int(sk):>9}  {int(oi):>12,}  {int(vol):>12,}  {pct:>+7.1f}%  {ltp:>8.2f}")
print(f"\n  Top-5 PE (Put) OI  [{FRONT_EXPIRY}]:")
print(f"  {'Strike':>9}  {'OI (lots)':>12}  {'OI Vol':>12}  {'vs Spot':>8}  {'PE LTP':>8}")
for _, r in top5_pe_oi.iterrows():
    sk = r["strike"]; oi = r["pe_oi"]; vol = r["pe_vol"]
    pct = (sk - spot) / spot * 100
    ltp = float(chain_front.loc[chain_front["strike"] == sk, "pe_ltp"].iloc[0])
    print(f"  {int(sk):>9}  {int(oi):>12,}  {int(vol):>12,}  {pct:>+7.1f}%  {ltp:>8.2f}")

# ══════════════════════════════════════════════════════════════════════════
# THESIS
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{W}")
print("  ANALYTICAL THESIS")
print(W)

print()
print("  MARKET STRUCTURE")
print("  " + "-"*60)
print(f"  Spot: {spot:.2f}  |  ATM: {atm:.0f}  |  Max Pain: {max_pain:.0f}  |  PCR: {pcr_oi:.3f}")
print(f"  OI Range: Put Wall {put_wall_strike}  ←  Spot  →  Call Wall {call_wall_strike}")

print()
print("  GEX / DEALER POSITIONING")
print("  " + "-"*60)
if total_net_gex > 0:
    print(f"  Net GEX is POSITIVE ({total_net_gex:.2f}). Market makers are net long gamma.")
    print("  This suppresses volatility — dealers buy dips and sell rallies to stay delta-neutral.")
    print(f"  Expect the stock to 'pin' between GEX walls: {gex_put_wall} – {gex_call_wall}")
else:
    print(f"  Net GEX is NEGATIVE ({total_net_gex:.2f}). Dealers are net short gamma.")
    print("  Dealers must chase price — buying on up-moves, selling on down-moves.")
    print("  This AMPLIFIES directional moves. Breakouts here tend to extend.")
if gamma_flip:
    print(f"  Gamma flip at {gamma_flip}. A sustained close {'above' if spot > gamma_flip else 'below'} this level")
    print(f"  {'keeps' if spot > gamma_flip else 'triggers'} the positive GEX environment.")

print()
print("  VOLATILITY REGIME")
print("  " + "-"*60)
if atm_iv and hv_20:
    if iv_premium_pct > 20:
        print(f"  IV ({atm_iv:.1f}%) is significantly RICH vs 20D HV ({hv_20:.1f}%) by {iv_premium_pct:.1f}%.")
        print("  Options are expensive. Selling premium (strangles/iron condors) is statistically favoured.")
        print("  But elevated IV often means the market senses an imminent move — size carefully.")
    elif iv_premium_pct < -15:
        print(f"  IV ({atm_iv:.1f}%) is CHEAP vs 20D HV ({hv_20:.1f}%) by {abs(iv_premium_pct):.1f}%.")
        print("  Options are underpriced relative to recent realised vol. Buying premium or long vega plays are attractive.")
    else:
        print(f"  IV ({atm_iv:.1f}%) is FAIRLY PRICED vs 20D HV ({hv_20:.1f}%) — spread: {iv_hv20_spread:+.1f}%.")
        print("  No strong directional edge from the vol surface alone.")
else:
    print("  Insufficient data for IV/HV comparison.")

print()
print("  SKEW SIGNAL")
print("  " + "-"*60)
if skew_5 is not None:
    if skew_5 > 4:
        print(f"  5% OTM put-call skew: {skew_5:.1f}% (steep). Smart money is paying up for puts.")
        print("  Elevated downside protection buying — cautious positioning despite the rally.")
    elif skew_5 > 1:
        print(f"  5% OTM put-call skew: {skew_5:.1f}% (moderate, normal for equities).")
        print("  Standard protective put demand — no extreme fear or greed signal.")
    elif skew_5 < -1:
        print(f"  5% OTM skew: {skew_5:.1f}% — CALL SKEW. Unusual.")
        print("  Market is paying more for OTM calls than OTM puts — strong bullish positioning / short-squeeze risk.")
    else:
        print(f"  Skew near flat ({skew_5:.1f}%). Market sees balanced risk both ways.")
else:
    print("  Skew data unavailable.")

if backwardation:
    print()
    print("  TERM STRUCTURE ANOMALY")
    print("  " + "-"*60)
    print(f"  Front-month IV ({atm_iv_front:.1f}%) > Next-month IV ({atm_iv_next:.1f}%) — BACKWARDATION.")
    print("  Near-term uncertainty is elevated. Watch for event risk (Q4 results, sector catalyst).")
    print("  Calendar spreads (sell front, buy back) benefit from this term structure.")

print()
print("  OVERALL THESIS")
print("  " + "-"*60)

# Synthesise
signals = []
if spot > atm: signals.append("price above ATM")
if pcr_oi > 1.0: signals.append(f"PCR {pcr_oi:.2f} — put-heavy (mild bullish OI structure)")
elif pcr_oi < 0.8: signals.append(f"PCR {pcr_oi:.2f} — call-heavy (short-term bearish bias)")
if spot > max_pain: signals.append(f"spot {abs(mp_dist):.1f}% above max pain (expiry gravity DOWN to {max_pain:.0f})")
elif spot < max_pain: signals.append(f"spot {abs(mp_dist):.1f}% below max pain (expiry gravity UP to {max_pain:.0f})")
if call_wall_strike > put_wall_strike: signals.append(f"OI tunnel: {put_wall_strike}–{call_wall_strike} defines near-term range")
if total_net_gex > 0: signals.append("positive GEX — range-bound tendencies until a wall breaks")
else: signals.append("negative GEX — trending/volatile conditions expected")

for s_note in signals:
    print(f"  + {s_note}")

print()
if spot > max_pain and total_net_gex > 0 and pcr_oi > 0.9:
    print("  POSITIONING LEAN: Pinning thesis. Stock likely gravitates toward max pain")
    print(f"  ({max_pain:.0f}) into the {FRONT_EXPIRY} expiry. Range: {straddle_range_lo:.0f}–{straddle_range_hi:.0f}")
    print("  Strategy: Short ATM straddle / iron condor if IV is rich vs HV.")
    print(f"  Key risk: Break above {call_wall_strike} or below {put_wall_strike} on institutional flow.")
elif total_net_gex < 0:
    print("  POSITIONING LEAN: Trend-following thesis. Negative GEX means dealer hedging")
    print("  amplifies moves in both directions. Momentum strategies outperform here.")
    print(f"  Watch the {gamma_flip} gamma flip — a break there turns into a rapid directional move.")
else:
    print("  POSITIONING LEAN: Wait-and-watch. Mixed signals. Key triggers: volume surge at")
    print(f"  {call_wall_strike} (breakout) or reversal at {put_wall_strike} (breakdown).")

print()
print(f"  Straddle break-even: {straddle_range_lo:.0f} – {straddle_range_hi:.0f}  ({round(straddle/spot*100,2):.2f}% move needed)")
if sigma_pts:
    print(f"  IV 1-sigma expiry range: {iv_range_lo:.0f} – {iv_range_hi:.0f}")
print()
print(W)
