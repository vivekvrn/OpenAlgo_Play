"""
Options Intelligence Dashboard Service

Aggregates GEX, OI, IV Smile and Term Structure signals for NIFTY
into a single snapshot with regime classification.

Calls get_option_chain once for front expiry (avoids redundant broker calls),
then separately fetches vol surface for multi-expiry term structure.
"""

from typing import Any

from services.option_chain_service import get_option_chain
from services.option_greeks_service import calculate_greeks
from services.option_symbol_service import construct_option_symbol, get_available_strikes
from services.vol_surface_service import get_vol_surface_data
from services.oi_tracker_service import _get_nearest_futures_price
from utils.logging import get_logger

logger = get_logger(__name__)

NIFTY_STRIKE_STEP = 50
WING_WIDTH = 200          # Iron Condor / Fly wing width (pts)
OTM_SKEW_PCT = 0.05       # 5% OTM for skew measurement
TERM_SLOPE_THRESHOLD = 2.0  # % IV difference to call backwardation


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
# Internal: derive wall / flip signals from GEX chain
# ---------------------------------------------------------------------------
def _gex_walls(gex_chain: list, spot_price: float) -> dict:
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
            # Linear interpolation
            if a["net_gex"] != b["net_gex"]:
                flip = a["strike"] + (b["strike"] - a["strike"]) * (-a["net_gex"]) / (b["net_gex"] - a["net_gex"])
                gamma_flip = round(flip / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
            else:
                gamma_flip = (a["strike"] + b["strike"]) // 2
            break  # Take the flip nearest to spot

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
) -> dict:
    between_walls = (
        put_wall is not None and call_wall is not None
        and put_wall < spot < call_wall
    )
    near_flip = gamma_flip is not None and abs(spot - gamma_flip) <= NIFTY_STRIKE_STEP * 2
    near_max_pain = max_pain is not None and abs(spot - max_pain) <= NIFTY_STRIKE_STEP * 3

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
        gex_walls = _gex_walls(gex_chain, spot_price)

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

        vol_quote_exchange = "NSE_INDEX" if underlying.upper() == "NIFTY" else exchange
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
        )

        # ---- Step 7: Strategy suggestions ----
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
