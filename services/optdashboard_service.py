"""
Options Intelligence Dashboard Service

Aggregates GEX, OI, IV Smile and Term Structure signals for NIFTY and SENSEX
into a single snapshot with regime classification.

Calls get_option_chain once for front expiry (avoids redundant broker calls),
then separately fetches vol surface for multi-expiry term structure.
"""

import math
from datetime import date as _date, datetime, timedelta
from typing import Any

from services.history_service import get_history
from services.option_chain_service import get_option_chain
from services.option_greeks_service import calculate_greeks
from services.option_symbol_service import construct_option_symbol, get_available_strikes
from services.vol_surface_service import get_vol_surface_data
from utils.logging import get_logger

logger = get_logger(__name__)

OTM_SKEW_PCT = 0.05         # 5% OTM for skew measurement
TERM_SLOPE_THRESHOLD = 2.0  # % IV difference to call backwardation

# Per-underlying parameters
# hv_symbol/hv_exchange: ETF proxy for HV because Dhan's historical API returns empty data
# for IDX_I/INDEX instruments (NSE_INDEX, BSE_INDEX). Log-returns of ETF ≈ log-returns of index.
_UNDERLYING_CONFIGS: dict[str, dict] = {
    "NIFTY":  {"strike_step": 50,  "wing_width": 200, "spread_width": 200, "vol_exchange": "NSE_INDEX", "hv_symbol": "NIFTYBEES", "hv_exchange": "NSE"},
    "SENSEX": {"strike_step": 100, "wing_width": 400, "spread_width": 400, "vol_exchange": "BSE_INDEX", "hv_symbol": "SENSEXETF", "hv_exchange": "BSE"},
}
_DEFAULT_CONFIG = {"strike_step": 50, "wing_width": 200, "spread_width": 200, "vol_exchange": None, "hv_symbol": None, "hv_exchange": None}


def _get_underlying_config(underlying: str) -> dict:
    return _UNDERLYING_CONFIGS.get(underlying.upper(), _DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Internal: compute GEX per strike from raw chain
# ---------------------------------------------------------------------------
def _compute_gex_chain(chain: list, spot_price: float, options_exchange: str) -> list:
    gex_chain = []
    for item in chain:
        strike = item["strike"]
        ce = item.get("ce") or {}
        pe = item.get("pe") or {}

        ce_oi = ce.get("oi", 0) or 0
        pe_oi = pe.get("oi", 0) or 0
        ce_ltp = ce.get("ltp", 0) or 0
        pe_ltp = pe.get("ltp", 0) or 0
        lotsize = ce.get("lotsize") or pe.get("lotsize") or 1

        ce_gex = pe_gex = 0.0

        if ce.get("symbol") and ce_ltp > 0 and ce_oi > 0:
            try:
                ok, greeks_resp, _ = calculate_greeks(
                    option_symbol=ce["symbol"],
                    exchange=options_exchange,
                    spot_price=spot_price,
                    option_price=ce_ltp,
                )
                if ok and greeks_resp.get("status") == "success":
                    gamma = greeks_resp.get("greeks", {}).get("gamma", 0) or 0
                    ce_gex = gamma * ce_oi * lotsize
            except Exception:
                pass

        if pe.get("symbol") and pe_ltp > 0 and pe_oi > 0:
            try:
                ok, greeks_resp, _ = calculate_greeks(
                    option_symbol=pe["symbol"],
                    exchange=options_exchange,
                    spot_price=spot_price,
                    option_price=pe_ltp,
                )
                if ok and greeks_resp.get("status") == "success":
                    gamma = greeks_resp.get("greeks", {}).get("gamma", 0) or 0
                    pe_gex = gamma * pe_oi * lotsize
            except Exception:
                pass

        gex_chain.append(
            {
                "strike": strike,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_gex": round(ce_gex, 2),
                "pe_gex": round(pe_gex, 2),
                "net_gex": round(ce_gex - pe_gex, 2),
            }
        )
    return gex_chain


# ---------------------------------------------------------------------------
# Internal: compute OI chain and max pain
# ---------------------------------------------------------------------------
def _compute_oi_and_maxpain(chain: list) -> tuple[list, int | float | None]:
    oi_chain = [
        {
            "strike": item["strike"],
            "ce_oi": (item.get("ce") or {}).get("oi", 0) or 0,
            "pe_oi": (item.get("pe") or {}).get("oi", 0) or 0,
        }
        for item in chain
    ]

    # Max pain: strike where total seller pain is minimum
    max_pain_strike = None
    min_pain = float("inf")
    for candidate in oi_chain:
        cs = candidate["strike"]
        ce_pain = sum(
            (cs - r["strike"]) * r["ce_oi"]
            for r in oi_chain
            if cs > r["strike"] and r["ce_oi"] > 0
        )
        pe_pain = sum(
            (r["strike"] - cs) * r["pe_oi"]
            for r in oi_chain
            if cs < r["strike"] and r["pe_oi"] > 0
        )
        total = ce_pain + pe_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = cs

    return oi_chain, max_pain_strike


# ---------------------------------------------------------------------------
# Internal: compute IV smile from chain
# ---------------------------------------------------------------------------
def _compute_iv_smile(
    chain: list, atm_strike: float, spot_price: float, options_exchange: str
) -> tuple[list, float | None, float | None, float | None]:
    iv_chain = []
    atm_ce_iv = atm_pe_iv = None

    for item in chain:
        strike = item["strike"]
        ce = item.get("ce") or {}
        pe = item.get("pe") or {}
        ce_iv = pe_iv = None

        if ce.get("symbol") and (ce.get("ltp") or 0) > 0:
            try:
                ok, resp, _ = calculate_greeks(
                    option_symbol=ce["symbol"],
                    exchange=options_exchange,
                    spot_price=spot_price,
                    option_price=ce["ltp"],
                )
                if ok and resp.get("status") == "success":
                    v = resp.get("implied_volatility")
                    if v and v > 0:
                        ce_iv = round(v, 2)
            except Exception:
                pass

        if pe.get("symbol") and (pe.get("ltp") or 0) > 0:
            try:
                ok, resp, _ = calculate_greeks(
                    option_symbol=pe["symbol"],
                    exchange=options_exchange,
                    spot_price=spot_price,
                    option_price=pe["ltp"],
                )
                if ok and resp.get("status") == "success":
                    v = resp.get("implied_volatility")
                    if v and v > 0:
                        pe_iv = round(v, 2)
            except Exception:
                pass

        if strike == atm_strike:
            atm_ce_iv = ce_iv
            atm_pe_iv = pe_iv

        iv_chain.append({"strike": strike, "ce_iv": ce_iv, "pe_iv": pe_iv})

    # ATM IV = average of CE and PE at ATM
    atm_iv = None
    if atm_ce_iv is not None and atm_pe_iv is not None:
        atm_iv = round((atm_ce_iv + atm_pe_iv) / 2, 2)
    elif atm_ce_iv is not None:
        atm_iv = atm_ce_iv
    elif atm_pe_iv is not None:
        atm_iv = atm_pe_iv

    # Skew: 5% OTM put IV minus 5% OTM call IV (positive = put skew / fear)
    skew = None
    if atm_strike and iv_chain:
        otm = atm_strike * OTM_SKEW_PCT
        put_iv = next(
            (i["pe_iv"] for i in sorted(iv_chain, key=lambda x: abs(x["strike"] - (atm_strike - otm)))
             if i["strike"] < atm_strike and i["pe_iv"] is not None),
            None,
        )
        call_iv = next(
            (i["ce_iv"] for i in sorted(iv_chain, key=lambda x: abs(x["strike"] - (atm_strike + otm)))
             if i["strike"] > atm_strike and i["ce_iv"] is not None),
            None,
        )
        if put_iv is not None and call_iv is not None:
            skew = round(put_iv - call_iv, 2)

    return iv_chain, atm_iv, skew, atm_ce_iv


# ---------------------------------------------------------------------------
# Internal: extract ATM IV per expiry from vol surface for term structure
# ---------------------------------------------------------------------------
def _extract_term_structure(surface_data: dict, atm_strike: float) -> list:
    data = surface_data.get("data", {})
    strikes = data.get("strikes", [])
    expiries = data.get("expiries", [])
    surface = data.get("surface", [])

    if not strikes or not expiries or not surface:
        return []

    # Find index of ATM strike (closest)
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))

    term = []
    for i, exp_info in enumerate(expiries):
        if i >= len(surface):
            continue
        row = surface[i]
        iv_val = row[atm_idx] if atm_idx < len(row) else None
        term.append(
            {
                "date": exp_info.get("date", ""),
                "dte": exp_info.get("dte", 0),
                "atm_iv": iv_val,
            }
        )
    return term


# ---------------------------------------------------------------------------
# Internal: compute 10-day and 30-day annualised historical volatility
# ---------------------------------------------------------------------------
def _compute_hv(
    underlying: str,
    vol_exchange: str,
    api_key: str,
    hv_symbol: str | None = None,
    hv_exchange: str | None = None,
) -> tuple[float | None, float | None]:
    """Return (hv_10, hv_30) in percent, annualised from daily log-returns.

    Fetches ~65 calendar days of daily closes. If the primary symbol returns
    insufficient data, falls back to hv_symbol/hv_exchange (e.g. NIFTYBEES on NSE)
    whose log-returns are identical to the index since it's a tracking ETF.
    Returns (None, None) on any failure so the caller degrades gracefully.
    """
    import numpy as np

    def _fetch_closes(symbol: str, exchange: str) -> list[float]:
        today = _date.today()
        start = (today - timedelta(days=65)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        ok, resp, _ = get_history(
            symbol=symbol,
            exchange=exchange,
            interval="D",
            start_date=start,
            end_date=end,
            api_key=api_key,
        )
        if not ok:
            logger.warning(f"HV fetch failed for {symbol}/{exchange}: {resp.get('message', 'unknown')}")
            return []
        return [float(r["close"]) for r in resp.get("data", []) if r.get("close")]

    try:
        closes = _fetch_closes(underlying, vol_exchange)

        if len(closes) < 12 and hv_symbol and hv_exchange:
            logger.info(f"HV: {underlying}/{vol_exchange} returned {len(closes)} closes — trying ETF proxy {hv_symbol}/{hv_exchange}")
            closes = _fetch_closes(hv_symbol, hv_exchange)

        if len(closes) < 12:
            logger.warning(f"HV: insufficient data ({len(closes)} closes) for {underlying}, skipping")
            return None, None

        log_returns = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
        hv_10 = round(float(np.std(log_returns[-10:], ddof=1) * math.sqrt(252) * 100), 2) if len(log_returns) >= 10 else None
        hv_30 = round(float(np.std(log_returns[-30:], ddof=1) * math.sqrt(252) * 100), 2) if len(log_returns) >= 30 else None
        return hv_10, hv_30
    except Exception as e:
        logger.warning(f"HV computation failed for {underlying}: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Internal: compute probable index ranges
# ---------------------------------------------------------------------------
def _compute_ranges(
    spot: float,
    atm_strike: float,
    atm_iv: float | None,
    expiry_date: str,
    call_wall: float | None,
    put_wall: float | None,
    ltp_map: dict,
) -> dict:
    """Return range_gex, range_iv_1sd, range_straddle dicts."""
    # DTE from DDMMMYY (e.g. "08MAY25")
    try:
        expiry_dt = datetime.strptime(expiry_date, "%d%b%y").date()
        dte = max((expiry_dt - _date.today()).days, 1)
    except Exception:
        dte = 1

    # ATM straddle premium from ltp_map
    atm_entry = ltp_map.get(atm_strike) or ltp_map.get(float(atm_strike)) or ltp_map.get(int(atm_strike))
    atm_ce_ltp = (atm_entry or {}).get("ce_ltp", 0) or 0
    atm_pe_ltp = (atm_entry or {}).get("pe_ltp", 0) or 0
    straddle_premium = round(atm_ce_ltp + atm_pe_ltp, 2)

    # IV 1-sigma range: spot × (IV/100) × √(DTE/365)
    range_iv_1sd = None
    if atm_iv and spot > 0:
        sigma_pts = round(spot * (atm_iv / 100) * math.sqrt(dte / 365), 0)
        range_iv_1sd = {
            "lower": round(spot - sigma_pts, 0),
            "upper": round(spot + sigma_pts, 0),
            "dte": dte,
            "sigma_pts": int(sigma_pts),
        }

    # ATM straddle range
    range_straddle = None
    if straddle_premium > 0 and spot > 0:
        range_straddle = {
            "lower": round(spot - straddle_premium, 0),
            "upper": round(spot + straddle_premium, 0),
            "straddle_premium": straddle_premium,
        }

    # GEX wall range
    range_gex = {"lower": put_wall, "upper": call_wall} if call_wall and put_wall else None

    return {
        "range_gex": range_gex,
        "range_iv_1sd": range_iv_1sd,
        "range_straddle": range_straddle,
    }


# ---------------------------------------------------------------------------
# Internal: derive wall / flip signals from GEX chain
# ---------------------------------------------------------------------------
def _gex_walls(gex_chain: list, spot_price: float, strike_step: int = 50) -> dict:
    if not gex_chain:
        return {"call_wall": None, "put_wall": None, "gamma_flip": None, "total_net_gex": 0}

    call_wall = max(gex_chain, key=lambda x: x["ce_gex"])["strike"]
    put_wall = max(gex_chain, key=lambda x: x["pe_gex"])["strike"]
    total_net_gex = round(sum(x["net_gex"] for x in gex_chain), 2)

    # Gamma flip: strike where net_gex changes sign closest to spot
    gamma_flip = None
    sorted_chain = sorted(gex_chain, key=lambda x: x["strike"])
    for i in range(len(sorted_chain) - 1):
        a, b = sorted_chain[i], sorted_chain[i + 1]
        if (a["net_gex"] >= 0) != (b["net_gex"] >= 0):
            if a["net_gex"] != b["net_gex"]:
                flip = a["strike"] + (b["strike"] - a["strike"]) * (-a["net_gex"]) / (b["net_gex"] - a["net_gex"])
                gamma_flip = round(flip / strike_step) * strike_step
            else:
                gamma_flip = (a["strike"] + b["strike"]) // 2
            break

    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": gamma_flip,
        "total_net_gex": total_net_gex,
    }


# ---------------------------------------------------------------------------
# Internal: classify market regime
# ---------------------------------------------------------------------------
def _classify_regime(
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    gamma_flip: float | None,
    total_net_gex: float,
    pcr_oi: float,
    atm_iv: float | None,
    iv_skew: float | None,
    max_pain: float | None,
    term_slope: float | None,
    strike_step: int = 50,
) -> dict:
    between_walls = (
        put_wall is not None and call_wall is not None
        and put_wall < spot < call_wall
    )
    near_flip = gamma_flip is not None and abs(spot - gamma_flip) <= strike_step * 2
    near_max_pain = max_pain is not None and abs(spot - max_pain) <= strike_step * 3

    if total_net_gex > 0 and between_walls and near_max_pain:
        return {
            "regime": "GAMMA PINNED",
            "description": f"Spot pinned between call wall ({call_wall}) and put wall ({put_wall}). Dealers long gamma — expect mean reversion.",
            "color": "green",
        }

    if total_net_gex < 0 or near_flip:
        return {
            "regime": "GAMMA SQUEEZE RISK",
            "description": "Negative GEX or spot near gamma flip level — dealer hedging amplifies directional moves.",
            "color": "red",
        }

    if atm_iv is not None and atm_iv > 20 and iv_skew is not None and iv_skew > 3:
        return {
            "regime": "FEAR MODE",
            "description": "Elevated put skew and high IV — hedging demand dominates. Consider selling put premium.",
            "color": "orange",
        }

    if term_slope is not None and term_slope < -TERM_SLOPE_THRESHOLD:
        return {
            "regime": "EVENT RISK / BACKWARDATION",
            "description": f"Near-term IV elevated vs far-term by {abs(term_slope):.1f}%. Possible event or expiry effect.",
            "color": "yellow",
        }

    if pcr_oi > 1.3 and total_net_gex > 0 and near_max_pain:
        return {
            "regime": "PINNING ENVIRONMENT",
            "description": f"High PCR ({pcr_oi:.2f}) + spot near max pain ({max_pain}) — premium selling favoured.",
            "color": "blue",
        }

    return {
        "regime": "NEUTRAL",
        "description": "No dominant regime. Monitor for regime shift before trading.",
        "color": "gray",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def get_dashboard_snapshot(
    underlying: str,
    exchange: str,
    expiry_date: str,
    next_expiry_date: str | None,
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Build a full options intelligence snapshot for the given underlying/expiry.

    Args:
        underlying: e.g. "NIFTY"
        exchange: Options exchange e.g. "NFO"
        expiry_date: Front expiry in DDMMMYY format
        next_expiry_date: Next weekly expiry for calendar spreads (optional)
        api_key: OpenAlgo API key

    Returns:
        (success, snapshot_dict, http_status)
    """
    try:
        cfg = _get_underlying_config(underlying)
        strike_step: int = cfg["strike_step"]
        wing_width: int = cfg["wing_width"]
        spread_width: int = cfg["spread_width"]
        vol_quote_exchange: str = cfg["vol_exchange"] or exchange

        options_exchange = exchange.upper()
        if options_exchange in ("NSE_INDEX", "NSE"):
            options_exchange = "NFO"
        elif options_exchange in ("BSE_INDEX", "BSE"):
            options_exchange = "BFO"

        # ---- Step 1: Single option chain fetch (45 strikes) ----
        success, chain_resp, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=45,
            api_key=api_key,
        )
        if not success:
            return False, chain_resp, status_code

        chain = chain_resp.get("chain", [])
        spot_price = chain_resp.get("underlying_ltp") or 0
        atm_strike = chain_resp.get("atm_strike") or 0

        if not spot_price:
            return False, {"status": "error", "message": "Could not determine spot price"}, 500

        lot_size = 1
        for item in chain:
            if item.get("ce", {}).get("lotsize"):
                lot_size = item["ce"]["lotsize"]
                break
            if item.get("pe", {}).get("lotsize"):
                lot_size = item["pe"]["lotsize"]
                break

        # Build LTP lookup: strike → {ce_ltp, pe_ltp, ce_symbol, pe_symbol}
        ltp_map: dict[float, dict] = {}
        for item in chain:
            s = item["strike"]
            ltp_map[s] = {
                "ce_ltp": (item.get("ce") or {}).get("ltp") or 0,
                "pe_ltp": (item.get("pe") or {}).get("ltp") or 0,
                "ce_symbol": (item.get("ce") or {}).get("symbol") or construct_option_symbol(underlying, expiry_date, s, "CE"),
                "pe_symbol": (item.get("pe") or {}).get("symbol") or construct_option_symbol(underlying, expiry_date, s, "PE"),
            }

        # ---- Step 2: Compute GEX from chain ----
        gex_chain = _compute_gex_chain(chain, spot_price, options_exchange)
        total_ce_oi = sum(x["ce_oi"] for x in gex_chain)
        total_pe_oi = sum(x["pe_oi"] for x in gex_chain)
        pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        gex_walls = _gex_walls(gex_chain, spot_price, strike_step)

        # ---- Step 3: OI and max pain ----
        oi_chain, max_pain_strike = _compute_oi_and_maxpain(chain)

        # ---- Step 4: IV smile ----
        iv_smile_chain, atm_iv, iv_skew, atm_ce_iv = _compute_iv_smile(
            chain, atm_strike, spot_price, options_exchange
        )

        # ---- Step 5: Vol surface for term structure ----
        expiries_for_surface = [expiry_date]
        if next_expiry_date:
            expiries_for_surface.append(next_expiry_date)
        # Try up to 4 expiries (surface service handles what's available)
        try:
            available = get_available_strikes(underlying, expiry_date, "CE", options_exchange)
        except Exception:
            available = []

        term_structure: list = []
        front_atm_iv = atm_iv
        next_atm_iv = None
        term_slope = None

        surf_ok, surf_resp, _ = get_vol_surface_data(
            underlying=underlying,
            exchange=vol_quote_exchange,
            expiry_dates=expiries_for_surface,
            strike_count=10,
            api_key=api_key,
        )
        if surf_ok:
            term_structure = _extract_term_structure(surf_resp, atm_strike)
            if len(term_structure) >= 1 and term_structure[0]["atm_iv"]:
                front_atm_iv = term_structure[0]["atm_iv"]
            if len(term_structure) >= 2 and term_structure[1]["atm_iv"]:
                next_atm_iv = term_structure[1]["atm_iv"]
                if front_atm_iv:
                    term_slope = round(next_atm_iv - front_atm_iv, 2)

        # ---- Step 6: Regime classification ----
        regime_info = _classify_regime(
            spot=spot_price,
            call_wall=gex_walls["call_wall"],
            put_wall=gex_walls["put_wall"],
            gamma_flip=gex_walls["gamma_flip"],
            total_net_gex=gex_walls["total_net_gex"],
            pcr_oi=pcr_oi,
            atm_iv=atm_iv,
            iv_skew=iv_skew,
            max_pain=max_pain_strike,
            term_slope=term_slope,
            strike_step=strike_step,
        )

        # ---- Step 7: Historical volatility (best-effort, non-blocking) ----
        hv_10, hv_30 = _compute_hv(
            underlying, vol_quote_exchange, api_key,
            hv_symbol=cfg.get("hv_symbol"),
            hv_exchange=cfg.get("hv_exchange"),
        )
        iv_rv_spread = round(atm_iv - hv_30, 2) if atm_iv is not None and hv_30 is not None else None

        # ---- Step 7b: Probable ranges ----
        ranges = _compute_ranges(
            spot=spot_price,
            atm_strike=atm_strike,
            atm_iv=atm_iv,
            expiry_date=expiry_date,
            call_wall=gex_walls["call_wall"],
            put_wall=gex_walls["put_wall"],
            ltp_map=ltp_map,
        )

        # ---- Step 8: Strategy suggestions ----
        from services.strategy_suggester import suggest_strategies
        strategies = suggest_strategies(
            underlying=underlying,
            exchange=options_exchange,
            expiry_date=expiry_date,
            next_expiry_date=next_expiry_date,
            spot_price=spot_price,
            atm_strike=atm_strike,
            lot_size=lot_size,
            call_wall=gex_walls["call_wall"],
            put_wall=gex_walls["put_wall"],
            gamma_flip=gex_walls["gamma_flip"],
            total_net_gex=gex_walls["total_net_gex"],
            pcr_oi=pcr_oi,
            atm_iv=atm_iv,
            iv_skew=iv_skew,
            max_pain=max_pain_strike,
            term_slope=term_slope,
            regime=regime_info["regime"],
            ltp_map=ltp_map,
            strike_step=strike_step,
            wing_width=wing_width,
            spread_width=spread_width,
        )

        snapshot = {
            "status": "success",
            "underlying": underlying.upper(),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "lot_size": lot_size,
            "expiry_date": expiry_date,
            "next_expiry_date": next_expiry_date,
            # GEX signals
            "call_wall": gex_walls["call_wall"],
            "put_wall": gex_walls["put_wall"],
            "gamma_flip": gex_walls["gamma_flip"],
            "total_net_gex": gex_walls["total_net_gex"],
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "pcr_oi": pcr_oi,
            # OI signals
            "max_pain": max_pain_strike,
            # Vol signals
            "atm_iv": atm_iv,
            "iv_skew": iv_skew,
            "front_atm_iv": front_atm_iv,
            "next_atm_iv": next_atm_iv,
            "term_structure_slope": term_slope,
            # Regime
            "regime": regime_info["regime"],
            "regime_description": regime_info["description"],
            "regime_color": regime_info["color"],
            # Historical volatility
            "hv_10": hv_10,
            "hv_30": hv_30,
            "iv_rv_spread": iv_rv_spread,
            # Probable ranges
            "range_gex": ranges["range_gex"],
            "range_iv_1sd": ranges["range_iv_1sd"],
            "range_straddle": ranges["range_straddle"],
            # Chart data
            "gex_chain": gex_chain,
            "oi_chain": oi_chain,
            "iv_smile_chain": iv_smile_chain,
            "term_structure": term_structure,
            # Strategies
            "strategies": strategies,
        }

        return True, snapshot, 200

    except Exception as e:
        logger.exception(f"Error building dashboard snapshot: {e}")
        return False, {"status": "error", "message": "Error building dashboard snapshot"}, 500
