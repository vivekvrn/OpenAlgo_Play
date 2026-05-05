"""
Strategy Suggester Service

Rule-based engine that maps market regime signals to option strategies.
Returns ranked strategy suggestions with leg details and approximate P&L metrics.

Strategies covered:
  Iron Condor     — sell at OI walls, buy wings
  Iron Fly        — sell ATM straddle, buy wings
  Long Straddle   — buy ATM CE + PE
  Bull Put Spread — sell OTM put, buy further OTM put
  Bear Call Spread— sell OTM call, buy further OTM call
  Calendar Spread — sell front weekly straddle, buy next weekly straddle
"""

from typing import Any

from services.option_symbol_service import construct_option_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def _round_to_step(strike: float, step: int) -> int:
    return int(round(strike / step) * step)


def _ltp(ltp_map: dict, strike: float, option_type: str) -> float:
    key = "ce_ltp" if option_type == "CE" else "pe_ltp"
    entry = ltp_map.get(strike) or ltp_map.get(float(strike)) or ltp_map.get(int(strike))
    return entry[key] if entry else 0.0


def _symbol(ltp_map: dict, underlying: str, expiry: str, strike: float, option_type: str) -> str:
    key = "ce_symbol" if option_type == "CE" else "pe_symbol"
    entry = ltp_map.get(strike) or ltp_map.get(float(strike)) or ltp_map.get(int(strike))
    if entry and entry.get(key):
        return entry[key]
    return construct_option_symbol(underlying, expiry, strike, option_type)


def _leg(ltp_map, underlying, expiry, strike, option_type, action, exchange):
    ltp = _ltp(ltp_map, strike, option_type)
    sym = _symbol(ltp_map, underlying, expiry, strike, option_type)
    return {
        "action": action,
        "strike": strike,
        "option_type": option_type,
        "expiry": expiry,
        "symbol": sym,
        "exchange": exchange,
        "ltp": round(ltp, 2),
    }


def _iron_condor(underlying, exchange, expiry, atm_strike, lot_size, ltp_map,
                 call_wall, put_wall, strike_step: int, wing_width: int) -> dict | None:
    sell_ce = _round_to_step(call_wall if call_wall else atm_strike + wing_width, strike_step)
    sell_pe = _round_to_step(put_wall if put_wall else atm_strike - wing_width, strike_step)
    buy_ce = sell_ce + wing_width
    buy_pe = sell_pe - wing_width

    if sell_ce <= atm_strike or sell_pe >= atm_strike:
        return None

    legs = [
        _leg(ltp_map, underlying, expiry, sell_ce, "CE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, buy_ce, "CE", "BUY", exchange),
        _leg(ltp_map, underlying, expiry, sell_pe, "PE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, buy_pe, "PE", "BUY", exchange),
    ]

    net_credit = (legs[0]["ltp"] - legs[1]["ltp"]) + (legs[2]["ltp"] - legs[3]["ltp"])
    net_credit = max(net_credit, 0)
    max_profit = round(net_credit * lot_size, 0)
    max_loss = round((wing_width - net_credit) * lot_size, 0)

    return {
        "name": "Iron Condor",
        "legs": legs,
        "net_premium": round(net_credit, 2),
        "max_profit_per_lot": int(max_profit),
        "max_loss_per_lot": int(max_loss),
        "upper_breakeven": round(sell_ce + net_credit, 0),
        "lower_breakeven": round(sell_pe - net_credit, 0),
    }


def _iron_fly(underlying, exchange, expiry, atm_strike, lot_size, ltp_map,
              wing_width: int) -> dict | None:
    buy_ce = atm_strike + wing_width
    buy_pe = atm_strike - wing_width

    legs = [
        _leg(ltp_map, underlying, expiry, atm_strike, "CE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, atm_strike, "PE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, buy_ce, "CE", "BUY", exchange),
        _leg(ltp_map, underlying, expiry, buy_pe, "PE", "BUY", exchange),
    ]

    straddle_credit = legs[0]["ltp"] + legs[1]["ltp"]
    wing_cost = legs[2]["ltp"] + legs[3]["ltp"]
    net_credit = max(straddle_credit - wing_cost, 0)
    max_profit = round(net_credit * lot_size, 0)
    max_loss = round((wing_width - net_credit) * lot_size, 0)

    return {
        "name": "Iron Fly",
        "legs": legs,
        "net_premium": round(net_credit, 2),
        "max_profit_per_lot": int(max_profit),
        "max_loss_per_lot": int(max_loss),
        "upper_breakeven": round(atm_strike + net_credit, 0),
        "lower_breakeven": round(atm_strike - net_credit, 0),
    }


def _long_straddle(underlying, exchange, expiry, atm_strike, lot_size, ltp_map) -> dict:
    legs = [
        _leg(ltp_map, underlying, expiry, atm_strike, "CE", "BUY", exchange),
        _leg(ltp_map, underlying, expiry, atm_strike, "PE", "BUY", exchange),
    ]

    total_cost = legs[0]["ltp"] + legs[1]["ltp"]
    max_loss = round(total_cost * lot_size, 0)

    return {
        "name": "Long Straddle",
        "legs": legs,
        "net_premium": round(-total_cost, 2),
        "max_profit_per_lot": None,
        "max_loss_per_lot": int(max_loss),
        "upper_breakeven": round(atm_strike + total_cost, 0),
        "lower_breakeven": round(atm_strike - total_cost, 0),
    }


def _bull_put_spread(underlying, exchange, expiry, atm_strike, lot_size, ltp_map,
                     strike_step: int, spread_width: int) -> dict:
    sell_strike = atm_strike - strike_step * 2   # 2 steps OTM
    buy_strike = sell_strike - spread_width

    legs = [
        _leg(ltp_map, underlying, expiry, sell_strike, "PE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, buy_strike, "PE", "BUY", exchange),
    ]

    net_credit = max(legs[0]["ltp"] - legs[1]["ltp"], 0)
    max_profit = round(net_credit * lot_size, 0)
    max_loss = round((spread_width - net_credit) * lot_size, 0)

    return {
        "name": "Bull Put Spread",
        "legs": legs,
        "net_premium": round(net_credit, 2),
        "max_profit_per_lot": int(max_profit),
        "max_loss_per_lot": int(max_loss),
        "upper_breakeven": None,
        "lower_breakeven": round(sell_strike - net_credit, 0),
    }


def _bear_call_spread(underlying, exchange, expiry, atm_strike, lot_size, ltp_map,
                      strike_step: int, spread_width: int) -> dict:
    sell_strike = atm_strike + strike_step * 2   # 2 steps OTM
    buy_strike = sell_strike + spread_width

    legs = [
        _leg(ltp_map, underlying, expiry, sell_strike, "CE", "SELL", exchange),
        _leg(ltp_map, underlying, expiry, buy_strike, "CE", "BUY", exchange),
    ]

    net_credit = max(legs[0]["ltp"] - legs[1]["ltp"], 0)
    max_profit = round(net_credit * lot_size, 0)
    max_loss = round((spread_width - net_credit) * lot_size, 0)

    return {
        "name": "Bear Call Spread",
        "legs": legs,
        "net_premium": round(net_credit, 2),
        "max_profit_per_lot": int(max_profit),
        "max_loss_per_lot": int(max_loss),
        "upper_breakeven": round(sell_strike + net_credit, 0),
        "lower_breakeven": None,
    }


def _calendar_spread(
    underlying, exchange, front_expiry, next_expiry, atm_strike, lot_size, ltp_map
) -> dict | None:
    if not next_expiry:
        return None

    legs = [
        _leg(ltp_map, underlying, front_expiry, atm_strike, "CE", "SELL", exchange),
        _leg(ltp_map, underlying, front_expiry, atm_strike, "PE", "SELL", exchange),
        _leg({}, underlying, next_expiry, atm_strike, "CE", "BUY", exchange),
        _leg({}, underlying, next_expiry, atm_strike, "PE", "BUY", exchange),
    ]

    front_premium = legs[0]["ltp"] + legs[1]["ltp"]
    # Far leg LTPs unknown without extra fetch — set to 0, note in rationale
    net_premium_approx = round(-front_premium, 2)  # debit (far leg cost unknown)

    return {
        "name": "Calendar Spread (Double)",
        "legs": legs,
        "net_premium": net_premium_approx,
        "max_profit_per_lot": None,
        "max_loss_per_lot": None,
        "upper_breakeven": None,
        "lower_breakeven": None,
        "note": "Far-leg LTPs shown as 0 — confirm premium at order entry in sandbox.",
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def _score_iron_condor(regime, between_walls, pcr_oi, atm_iv, near_max_pain) -> float:
    score = 0.0
    if regime == "GAMMA PINNED":
        score += 0.5
    if between_walls:
        score += 0.2
    if 1.0 < pcr_oi < 1.6:
        score += 0.1
    if atm_iv and 13 <= atm_iv <= 20:
        score += 0.1
    if near_max_pain:
        score += 0.1
    return min(score, 1.0)


def _score_iron_fly(regime, atm_iv, near_max_pain, pcr_oi) -> float:
    score = 0.0
    if regime == "GAMMA PINNED":
        score += 0.4
    if near_max_pain:
        score += 0.3
    if atm_iv and atm_iv < 15:
        score += 0.2
    if 0.8 < pcr_oi < 1.3:
        score += 0.1
    return min(score, 1.0)


def _score_straddle(regime, atm_iv, term_slope) -> float:
    score = 0.0
    if regime == "GAMMA SQUEEZE RISK":
        score += 0.5
    if atm_iv and atm_iv < 14:
        score += 0.3
    if term_slope is not None and abs(term_slope) > 2:
        score += 0.2
    return min(score, 1.0)


def _score_bull_put(regime, pcr_oi, iv_skew, total_net_gex) -> float:
    score = 0.0
    if regime in ("FEAR MODE", "PINNING ENVIRONMENT"):
        score += 0.3
    if pcr_oi and pcr_oi > 1.2:
        score += 0.3
    if iv_skew and iv_skew > 2:
        score += 0.3
    if total_net_gex > 0:
        score += 0.1
    return min(score, 1.0)


def _score_bear_call(regime, pcr_oi, iv_skew, total_net_gex) -> float:
    score = 0.0
    if regime == "GAMMA SQUEEZE RISK":
        score += 0.3
    if pcr_oi and pcr_oi < 0.8:
        score += 0.3
    if iv_skew and iv_skew < -2:
        score += 0.3
    if total_net_gex < 0:
        score += 0.1
    return min(score, 1.0)


def _score_calendar(regime, term_slope) -> float:
    score = 0.0
    if regime == "EVENT RISK / BACKWARDATION":
        score += 0.6
    if term_slope is not None and term_slope < -2:
        score += 0.4
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------
_RATIONALES = {
    "Iron Condor": (
        "Sell at OI walls (call wall {call_wall}, put wall {put_wall}) and collect theta. "
        "Gamma pinned regime favours range-bound price action."
    ),
    "Iron Fly": (
        "ATM straddle sell near max pain ({max_pain}). Low IV ({atm_iv}%) makes premium "
        "selling efficient; expect expiry near ATM."
    ),
    "Long Straddle": (
        "Negative GEX / gamma squeeze risk detected. Low IV ({atm_iv}%) makes buying "
        "the straddle cheap — positioned for a large directional move."
    ),
    "Bull Put Spread": (
        "High put skew ({iv_skew}%) + strong put wall ({put_wall}) — fade bearish sentiment "
        "with defined risk. PCR {pcr_oi} supports put-side premium selling."
    ),
    "Bear Call Spread": (
        "Negative GEX + call wall overhead ({call_wall}). Sell call premium with cap. "
        "PCR {pcr_oi} confirms weak bullish sentiment."
    ),
    "Calendar Spread (Double)": (
        "Near-term IV ({front_atm_iv}%) exceeds far-term ({next_atm_iv}%) — "
        "sell the rich near weekly, buy the cheaper far weekly at ATM."
    ),
}


def _build_rationale(name: str, **ctx) -> str:
    template = _RATIONALES.get(name, "")
    try:
        return template.format(**{k: (v if v is not None else "N/A") for k, v in ctx.items()})
    except Exception:
        return template


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------
def suggest_strategies(
    underlying: str,
    exchange: str,
    expiry_date: str,
    next_expiry_date: str | None,
    spot_price: float,
    atm_strike: float,
    lot_size: int,
    call_wall: float | None,
    put_wall: float | None,
    gamma_flip: float | None,
    total_net_gex: float,
    pcr_oi: float,
    atm_iv: float | None,
    iv_skew: float | None,
    max_pain: float | None,
    term_slope: float | None,
    regime: str,
    ltp_map: dict,
    strike_step: int = 50,
    wing_width: int = 200,
    spread_width: int = 200,
) -> list[dict[str, Any]]:
    """
    Generate up to 3 ranked strategy suggestions based on market signals.
    """
    between_walls = (
        put_wall is not None and call_wall is not None
        and put_wall < spot_price < call_wall
    )
    near_max_pain = max_pain is not None and abs(spot_price - max_pain) <= strike_step * 3

    ctx = dict(
        call_wall=call_wall,
        put_wall=put_wall,
        atm_iv=atm_iv,
        iv_skew=iv_skew,
        pcr_oi=pcr_oi,
        max_pain=max_pain,
        front_atm_iv=atm_iv,
        next_atm_iv=None,
        gamma_flip=gamma_flip,
    )
    if term_slope is not None and atm_iv is not None:
        ctx["front_atm_iv"] = atm_iv
        ctx["next_atm_iv"] = round(atm_iv + term_slope, 2)

    candidates: list[dict] = []

    # --- Iron Condor ---
    score_ic = _score_iron_condor(regime, between_walls, pcr_oi, atm_iv, near_max_pain)
    if score_ic > 0.1:
        structure = _iron_condor(underlying, exchange, expiry_date, atm_strike, lot_size, ltp_map,
                                 call_wall, put_wall, strike_step, wing_width)
        if structure:
            structure["rationale"] = _build_rationale("Iron Condor", **ctx)
            candidates.append({"score": score_ic, **structure})

    # --- Iron Fly ---
    score_if = _score_iron_fly(regime, atm_iv, near_max_pain, pcr_oi)
    if score_if > 0.1:
        structure = _iron_fly(underlying, exchange, expiry_date, atm_strike, lot_size, ltp_map,
                              wing_width)
        if structure:
            structure["rationale"] = _build_rationale("Iron Fly", **ctx)
            candidates.append({"score": score_if, **structure})

    # --- Long Straddle ---
    score_st = _score_straddle(regime, atm_iv, term_slope)
    if score_st > 0.1:
        structure = _long_straddle(underlying, exchange, expiry_date, atm_strike, lot_size, ltp_map)
        structure["rationale"] = _build_rationale("Long Straddle", **ctx)
        candidates.append({"score": score_st, **structure})

    # --- Bull Put Spread ---
    score_bp = _score_bull_put(regime, pcr_oi, iv_skew, total_net_gex)
    if score_bp > 0.1:
        structure = _bull_put_spread(underlying, exchange, expiry_date, atm_strike, lot_size, ltp_map,
                                     strike_step, spread_width)
        structure["rationale"] = _build_rationale("Bull Put Spread", **ctx)
        candidates.append({"score": score_bp, **structure})

    # --- Bear Call Spread ---
    score_bc = _score_bear_call(regime, pcr_oi, iv_skew, total_net_gex)
    if score_bc > 0.1:
        structure = _bear_call_spread(underlying, exchange, expiry_date, atm_strike, lot_size, ltp_map,
                                      strike_step, spread_width)
        structure["rationale"] = _build_rationale("Bear Call Spread", **ctx)
        candidates.append({"score": score_bc, **structure})

    # --- Calendar Spread ---
    score_cal = _score_calendar(regime, term_slope)
    if score_cal > 0.1:
        structure = _calendar_spread(underlying, exchange, expiry_date, next_expiry_date, atm_strike, lot_size, ltp_map)
        if structure:
            structure["rationale"] = _build_rationale("Calendar Spread (Double)", **ctx)
            candidates.append({"score": score_cal, **structure})

    # Sort by score descending, return top 3
    candidates.sort(key=lambda x: x["score"], reverse=True)
    ranked = []
    for i, c in enumerate(candidates[:3]):
        ranked.append({"rank": i + 1, "fit_score": round(c["score"], 2), **{k: v for k, v in c.items() if k != "score"}})

    return ranked
