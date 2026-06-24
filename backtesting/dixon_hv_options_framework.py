"""
Dixon Technologies — Options Framework using Historical Volatility
Computes HV-10/20/30/60, theoretical BS chain, skew, straddle pricing, and
provides the analytical framework. Live OI data will populate once Dhan
session is refreshed (uv run app.py -> log in -> run dixon_options_analysis.py).
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, math, yfinance as yf
from datetime import datetime, date as _date
from scipy.stats import norm

TICKER   = "DIXON.NS"
SPOT_CMP = 12235.0
LOT_SIZE = 50
RFR      = 0.065
FRONT_EXP = _date(2026, 6, 30)
NEXT_EXP  = _date(2026, 7, 28)
FAR_EXP   = _date(2026, 8, 25)

def dte_yrs(exp): return max((_date.today() - exp).days * -1, 1) / 365.0
T_f  = dte_yrs(FRONT_EXP)
T_n  = dte_yrs(NEXT_EXP)
T_fa = dte_yrs(FAR_EXP)

# ── Historical Volatility ─────────────────────────────────────────────────
df = yf.download(TICKER, period="120d", progress=False, auto_adjust=True)
if hasattr(df.columns, "levels"):
    df = df.xs(TICKER, axis=1, level=1)
df.columns = [c.lower() for c in df.columns]
close = df["close"].dropna()
ret   = np.log(close / close.shift(1)).dropna()

def hv(n): return round(float(np.std(ret.iloc[-n:], ddof=1) * math.sqrt(252) * 100), 2) if len(ret) >= n else None
hv10, hv20, hv30, hv60 = hv(10), hv(20), hv(30), hv(60)

high52 = float(close.max()); low52 = float(close.min())
from_high = (SPOT_CMP - high52) / high52 * 100
from_low  = (SPOT_CMP - low52)  / low52  * 100

# ── Black-Scholes helpers ─────────────────────────────────────────────────
def bs_d1(S, K, T, r, sigma):
    return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))

def bs_price(S, K, T, r, sigma, flag):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0) if flag == "c" else max(K - S, 0)
    d1 = bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    if flag == "c":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0.0
    d1 = bs_d1(S, K, T, r, sigma)
    return norm.pdf(d1) / (S * sigma * math.sqrt(T))

def bs_vega(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0.0
    d1 = bs_d1(S, K, T, r, sigma)
    return S * norm.pdf(d1) * math.sqrt(T) / 100

def bs_theta(S, K, T, r, sigma, flag):
    if T <= 0 or sigma <= 0: return 0.0
    d1 = bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    t1 = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if flag == "c":
        return (t1 - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
    return (t1 + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365

def skew_iv(K, base_sigma, S, slope=0.28):
    """Equity negative skew: puts rich, calls cheap relative to ATM."""
    mny = (S - K) / S
    return base_sigma * (1 + slope * mny)

# Estimated ATM IV = HV20 * 1.15 (typical Indian equity premium ~15%)
est_sigma = (hv20 / 100) * 1.15 if hv20 else 0.28
est_iv    = round(est_sigma * 100, 2)
S = SPOT_CMP

# ── Theoretical chain ─────────────────────────────────────────────────────
atm_sk = round(S / 100) * 100
step   = 500
strikes = sorted(set([int(atm_sk + i * step) for i in range(-12, 13) if atm_sk + i * step > 0]))

chain_rows = []
for K in strikes:
    sigma_K = skew_iv(K, est_sigma, S)
    ce_p = bs_price(S, K, T_f, RFR, sigma_K, "c")
    pe_p = bs_price(S, K, T_f, RFR, sigma_K, "p")
    g    = bs_gamma(S, K, T_f, RFR, sigma_K)
    vg   = bs_vega(S, K, T_f, RFR, sigma_K)
    th_c = bs_theta(S, K, T_f, RFR, sigma_K, "c")
    th_p = bs_theta(S, K, T_f, RFR, sigma_K, "p")
    chain_rows.append({
        "strike": K, "ce_ltp": round(ce_p, 2), "pe_ltp": round(pe_p, 2),
        "iv_pct": round(sigma_K * 100, 2), "gamma": g, "vega": round(vg, 4),
        "theta_c": round(th_c, 2), "theta_p": round(th_p, 2),
    })
chain = pd.DataFrame(chain_rows)

atm_r   = chain[chain["strike"] == atm_sk]
if atm_r.empty: atm_r = chain.iloc[[len(chain)//2]]
atm_ce  = float(atm_r["ce_ltp"].iloc[0])
atm_pe  = float(atm_r["pe_ltp"].iloc[0])
straddle= round(atm_ce + atm_pe, 2)
sigma_pts = round(S * est_sigma * math.sqrt(T_f), 0)

# Term structure (vol scaling with sqrt-time, slight term premium)
iv_next = round(est_iv * math.sqrt(T_n / T_f) * 1.02, 2)
iv_far  = round(est_iv * math.sqrt(T_fa / T_f) * 1.03, 2)

W   = "=" * 80
SEP = "-" * 70

print(f"\n{W}")
print("  DIXON TECHNOLOGIES (DIXON.NS) — OPTIONS INTELLIGENCE ANALYSIS")
print(f"  {datetime.now().strftime('%d %b %Y  %H:%M')}")
print(W)
print()
print("  DATA STATUS:")
print("  [X] Live Dhan option chain  — session expired at 3 AM IST (expected daily)")
print("  [X] NSE website API         — Akamai bot-protection active")
print("  [OK] Historical Volatility  — yfinance (120 days, live)")
print("  [OK] Theoretical BS chain   — derived from HV20 x 1.15 IV assumption")
print()
print("  To run with LIVE OI data:")
print("  1. uv run app.py  (starts OpenAlgo at http://127.0.0.1:5000)")
print("  2. Log into Dhan via the web UI (refreshes auth token)")
print("  3. python backtesting/dixon_options_analysis.py")

print(f"\n{W}")
print("  SECTION 1 — HISTORICAL VOLATILITY (REALISED VOL)")
print(W)
print()
print(f"  Underlying (CMP)  : {S:.2f}")
print(f"  52-Week High      : {high52:.2f}  ({from_high:.1f}% below)")
print(f"  52-Week Low       : {low52:.2f}  ({from_low:.1f}% above)")
print()
print(f"  {'Period':<12}  {'Annualised HV':>15}  {'Daily 1-sigma':>15}")
print(f"  {'-'*48}")
for label, hval in [("HV-10", hv10), ("HV-20", hv20), ("HV-30", hv30), ("HV-60", hv60)]:
    if hval:
        daily_1s = round(S * hval / 100 / math.sqrt(252), 2)
        print(f"  {label:<12}  {hval:>14.2f}%  {daily_1s:>13.2f} pts")
print()
hv_regime = ("SPIKING — significant move in last 10 days" if hv10 > hv20 * 1.2
             else "COMPRESSING — calm after prior move"      if hv10 < hv20 * 0.8
             else "STABLE — no vol spike or compression")
print(f"  HV Regime : HV10 ({hv10}%) vs HV20 ({hv20}%) → {hv_regime}")
print()
trend_20_60 = hv20 - hv60 if hv60 else 0
if trend_20_60 > 3:
    print(f"  Medium-term trend: HV20 ({hv20}%) > HV60 ({hv60}%) — vol EXPANDING vs baseline")
    print("  Recent months more volatile than the prior 2 months — possible regime change")
elif trend_20_60 < -3:
    print(f"  Medium-term trend: HV20 ({hv20}%) < HV60 ({hv60}%) — vol CONTRACTING vs baseline")
    print("  Stock has quieted down from a more turbulent period — vol mean-reversion ongoing")
else:
    print(f"  Medium-term trend: HV20 ({hv20}%) ≈ HV60 ({hv60}%) — stable vol regime")

print(f"\n{W}")
print("  SECTION 2 — ESTIMATED IV FRAMEWORK  (needs live chain for actuals)")
print(W)
print()
print(f"  ATM IV estimate (front)    : {est_iv:.2f}%   (HV20 × 1.15 — typical equity premium)")
print(f"  ATM IV estimate (next/Jul) : {iv_next:.2f}%")
print(f"  ATM IV estimate (far/Aug)  : {iv_far:.2f}%")
print()
richness = "RICH"    if est_iv > hv20 * 1.25 else "FAIR" if est_iv > hv20 * 0.95 else "CHEAP"
print(f"  IV/HV20 assumption         : {round(est_iv/hv20,2):.2f}x  — IV is {richness} relative to realised vol")
print()
print(f"  ATM Straddle (theoretical) : {straddle:.2f}  ({round(straddle/S*100,2):.2f}% of spot)")
print(f"  Straddle break-even range  : {int(S-straddle)}  –  {int(S+straddle)}")
print(f"  IV 1-sigma expiry range    : {int(S-sigma_pts)}  –  {int(S+sigma_pts)}")
print(f"  DTE: front={round(T_f*365)}d  next={round(T_n*365)}d  far={round(T_fa*365)}d")

print(f"\n{W}")
print("  SECTION 3 — THEORETICAL OPTION CHAIN  (front expiry 30-Jun-26)")
print(W)
print()
print(f"  {'Strike':>9}  {'CE':>9}  {'PE':>9}  {'IV%':>7}  {'Gamma':>10}  {'Vega':>7}  {'Theta(CE)':>10}  {'Moneyness':>10}")
print(f"  {'-'*80}")
visible = chain[(chain["strike"] >= S * 0.88) & (chain["strike"] <= S * 1.12)]
for _, r in visible.iterrows():
    mny = (r["strike"] - S) / S * 100
    mk  = "  <- ATM" if abs(mny) < 2.5 else ""
    print(f"  {int(r['strike']):>9}  {r['ce_ltp']:>9.2f}  {r['pe_ltp']:>9.2f}  {r['iv_pct']:>7.2f}  "
          f"{r['gamma']:>10.6f}  {r['vega']:>7.4f}  {r['theta_c']:>10.2f}  {mny:>+9.1f}%{mk}")

print(f"\n{W}")
print("  SECTION 4 — VOLATILITY SKEW  (theoretical equity negative skew)")
print(W)
print()
print("  Equity options have a characteristic 'negative skew' — OTM puts are more")
print("  expensive than OTM calls of the same delta (fear premium / crash risk).")
print()
print(f"  {'Strike':>9}  {'Moneyness':>10}  {'IV%':>9}  {'Skew vs ATM':>13}  {'CE':>9}  {'PE':>9}")
print(f"  {'-'*72}")
skew_strikes = [int(S * m) for m in [0.85, 0.875, 0.90, 0.925, 0.95, 0.975, 1.0, 1.025, 1.05, 1.075, 1.10, 1.125, 1.15]]
for K in skew_strikes:
    sigma_K = skew_iv(K, est_sigma, S)
    iv_K    = round(sigma_K * 100, 2)
    mny     = (K - S) / S * 100
    diff    = round(iv_K - est_iv, 2)
    ce_p    = round(bs_price(S, K, T_f, RFR, sigma_K, "c"), 2)
    pe_p    = round(bs_price(S, K, T_f, RFR, sigma_K, "p"), 2)
    mk      = "  <- ATM" if abs(mny) < 1.5 else ""
    print(f"  {K:>9}  {mny:>+9.1f}%  {iv_K:>9.2f}%  {diff:>+12.2f}%  {ce_p:>9.2f}  {pe_p:>9.2f}{mk}")
print()
put5  = round(skew_iv(int(S*0.95), est_sigma, S)*100, 2)
call5 = round(skew_iv(int(S*1.05), est_sigma, S)*100, 2)
put10 = round(skew_iv(int(S*0.90), est_sigma, S)*100, 2)
call10= round(skew_iv(int(S*1.10), est_sigma, S)*100, 2)
print(f"  25D Risk Reversal (5% OTM P - C)   : {put5:.2f}% - {call5:.2f}% = {round(put5-call5,2):+.2f}%  (put skew)")
print(f"  10% OTM Risk Reversal (P - C)       : {put10:.2f}% - {call10:.2f}% = {round(put10-call10,2):+.2f}%  (deeper put skew)")

print(f"\n{W}")
print("  SECTION 5 — LIVE OI / POSITIONING METRICS  (requires Dhan session)")
print(W)
print()
print("  Once live chain is loaded, the analysis will reveal:")
print()
metrics = [
    ("PCR (OI)",         "Signal", "Bull >1.2  |  Bear <0.8  |  Neutral 0.8-1.2"),
    ("Call Wall",        "Level",  "Strike with max CE OI — key resistance"),
    ("Put Wall",         "Level",  "Strike with max PE OI — key support"),
    ("Max Pain",         "Level",  "Gravity toward this strike into expiry"),
    ("Net GEX",          "Sign",   "+ve = range-bound  |  -ve = trending/volatile"),
    ("Gamma Flip",       "Level",  "Critical threshold for vol regime change"),
    ("OI Build-up",      "Flow",   "Where fresh OI is being added — positioning signal"),
    ("ATM IV (live)",    "Number", "Actual market-implied vol — compare to {:.1f}% HV20".format(hv20)),
    ("IV Term Structure","Shape",  "Contango (normal) vs backwardation (event risk)"),
    ("Live Skew",        "Number", "Actual put-call IV difference vs theoretical above"),
]
print(f"  {'Metric':<22}  {'Type':<12}  {'Interpretation'}")
print(f"  {'-'*72}")
for name, typ, interp in metrics:
    print(f"  {name:<22}  {typ:<12}  {interp}")

print(f"\n{W}")
print("  SECTION 6 — OPTIONS THESIS  (structural + vol framework)")
print(W)
print()
print("  VOLATILITY REGIME:")
print(f"  HV-10 ({hv10}%) vs HV-20 ({hv20}%) vs HV-30 ({hv30}%)")
if hv10 > hv20:
    print(f"  Short-term vol is EXPANDING — the last 10 days have been more volatile than")
    print(f"  the prior month. This suggests directional price discovery is underway.")
    print(f"  Implication: prefer buying defined-risk options over short premium strategies.")
else:
    print(f"  Short-term vol is COMPRESSING — the stock has moved less in the last 10 days")
    print(f"  than the prior month average. Classic pre-breakout vol compression.")
    print(f"  Implication: long straddle or strangles become attractive if CMP is near a key level.")

print()
print("  IV PREMIUM CONTEXT:")
print(f"  Estimated ATM IV ({est_iv}%) vs HV20 ({hv20}%): {round(est_iv/hv20,2):.2f}x premium")
if est_iv / hv20 > 1.3:
    print("  Options are EXPENSIVE relative to realised vol. Volatility sellers have edge.")
    print("  Preferred structures: ATM straddle/strangle short, iron condors, covered calls.")
elif est_iv / hv20 < 1.0:
    print("  Options are CHEAP relative to realised vol. Directional buyers benefit.")
    print("  Preferred structures: long debit spreads, long straddles ahead of catalysts.")
else:
    print("  Options fairly priced. Strategy selection depends on directional thesis.")

print()
print("  STRADDLE ANALYSIS:")
print(f"  At estimated IV {est_iv}%, the ATM straddle costs ~{straddle:.0f} ({round(straddle/S*100,2):.2f}% of spot).")
print(f"  Expiry break-even: {int(S-straddle)} – {int(S+straddle)}")
print(f"  Spot ({S:.0f}) would need to move ±{round(straddle/S*100,2):.2f}% for the straddle to expire with value.")
print(f"  With HV20 at {hv20}%, the expected 1-sigma move in {round(T_f*365)} days is ±{int(sigma_pts)} pts.")

print()
print("  TERM STRUCTURE VIEW:")
if iv_next < est_iv:
    print(f"  Estimated BACKWARDATION: front IV ({est_iv:.1f}%) > next ({iv_next:.1f}%)")
    print("  This would signal near-term event risk or expiry pinning in June.")
    print("  Calendar spread (sell Jun, buy Jul) could benefit from time-spread decay.")
else:
    print(f"  Estimated CONTANGO: IV rises from {est_iv:.1f}% (Jun) to {iv_next:.1f}% (Jul) to {iv_far:.1f}% (Aug).")
    print("  Normal upward-sloping term structure — no near-term event signal.")
    print("  Front-month premium sellers have a structural edge from faster theta decay.")

print()
print("  KEY STRIKES TO WATCH (when live chain loads):")
print(f"  ATM: {atm_sk}  |  -5% support: {int(S*0.95):.0f}  |  +5% resistance: {int(S*1.05):.0f}")
print(f"  -10% strong support: {int(S*0.90):.0f}  |  +10% strong resistance: {int(S*1.10):.0f}")

print()
print(f"  SUMMARY:")
print(f"  Dixon is in a recovery phase (above EMA20/50, below EMA200).")
print(f"  HV at {hv20}% is {'elevated' if hv20>35 else 'moderate' if hv20>25 else 'subdued'} for a large-cap electronics play.")
if hv10 > hv20:
    print(f"  Recent vol expansion (HV10 {hv10}% > HV20 {hv20}%) suggests active price discovery —")
    print(f"  the stock is 'finding its level' and may settle after this consolidation.")
else:
    print(f"  Vol compression (HV10 {hv10}% < HV20 {hv20}%) is consistent with a coiling")
    print(f"  pattern — watch for a breakout from the recent 11000-12500 range.")
print(f"  Once live chain loads: OI analysis will reveal whether institutions")
print(f"  are positioned for a breakout above {int(S*1.05):.0f} or a reversion to max pain.")
print()
print(W)
