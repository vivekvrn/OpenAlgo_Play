"""
GEX Recorder Service

Takes intraday GEX snapshots at fixed cadences (09:20, 12:30, 15:25, 15:32 IST)
for NIFTY and SENSEX. Snapshots are persisted to db/gex_history.db and surfaced
via GET /optdashboard/api/gex-history.

Uses APScheduler BackgroundScheduler with in-memory job store (jobs are static,
not user-configurable, so persistence is not required).
"""

import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.logging import get_logger

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()

# Underlyings to snapshot with their exchanges
_TARGETS = [
    {"underlying": "NIFTY",  "exchange": "NFO"},
    {"underlying": "SENSEX", "exchange": "BFO"},
]

# IST times to fire snapshots (hour, minute)
_SNAPSHOT_TIMES = [(9, 20), (12, 30), (15, 25), (15, 32)]


def _get_first_user_api_key() -> str | None:
    """Fetch the API key of the first non-revoked user (single-user deployment)."""
    try:
        from database.auth_db import Auth, db_session, get_api_key_for_tradingview
        auth = db_session.query(Auth).filter_by(is_revoked=False).first()
        if not auth:
            return None
        return get_api_key_for_tradingview(auth.name)
    except Exception as e:
        logger.warning(f"GEX recorder: could not get API key — {e}")
        return None
    finally:
        try:
            from database.auth_db import db_session as _s
            _s.remove()
        except Exception:
            pass


def _get_front_expiry(exchange: str, underlying: str) -> str | None:
    """Get the nearest front expiry from the in-memory master contract cache.

    Returns expiry in DDMMMYY format (e.g. '08MAY25'), ready for option chain calls.
    """
    try:
        from database.token_db_enhanced import get_distinct_expiries_cached
        expiries = get_distinct_expiries_cached(exchange=exchange, underlying=underlying)
        if not expiries:
            return None
        # Cache returns DD-MMM-YY; strip hyphens for option chain API
        return expiries[0].replace("-", "").upper()
    except Exception as e:
        logger.warning(f"GEX recorder: could not get expiry for {underlying}/{exchange} — {e}")
        return None


def _take_gex_snapshot(underlying: str, exchange: str) -> None:
    """Compute GEX from a live option chain fetch and persist one row."""
    try:
        api_key = _get_first_user_api_key()
        if not api_key:
            logger.warning(f"GEX recorder: skipping {underlying} — no API key")
            return

        expiry = _get_front_expiry(exchange, underlying)
        if not expiry:
            logger.warning(f"GEX recorder: skipping {underlying} — no front expiry in cache")
            return

        from services.option_chain_service import get_option_chain
        from services.optdashboard_service import (
            _compute_gex_chain,
            _gex_walls,
            _get_underlying_config,
        )

        ok, chain_resp, _ = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry,
            strike_count=45,
            api_key=api_key,
        )
        if not ok:
            logger.warning(f"GEX recorder: option chain failed for {underlying}")
            return

        chain = chain_resp.get("chain", [])
        spot = chain_resp.get("underlying_ltp") or 0
        if not spot or not chain:
            logger.warning(f"GEX recorder: empty chain/spot for {underlying}")
            return

        cfg = _get_underlying_config(underlying)
        gex_chain = _compute_gex_chain(chain, spot, exchange)
        walls = _gex_walls(gex_chain, spot, cfg["strike_step"])

        from database.gex_history_db import insert_gex_snapshot
        insert_gex_snapshot(
            symbol=underlying,
            expiry=expiry,
            spot=spot,
            net_gex=walls["total_net_gex"],
            call_wall=walls["call_wall"],
            put_wall=walls["put_wall"],
            gamma_flip=walls["gamma_flip"],
        )
        logger.info(
            f"GEX snapshot recorded — {underlying} spot={spot:.0f} "
            f"net_gex={walls['total_net_gex']:.2f} expiry={expiry}"
        )
    except Exception as e:
        logger.exception(f"GEX recorder: error snapshotting {underlying}: {e}")


def _record_all() -> None:
    """Job function called by APScheduler — snapshots all configured underlyings."""
    for target in _TARGETS:
        try:
            _take_gex_snapshot(
                underlying=target["underlying"],
                exchange=target["exchange"],
            )
        except Exception as e:
            logger.exception(f"GEX recorder: unexpected error for {target['underlying']}: {e}")


def init_gex_recorder() -> None:
    """Initialize and start the GEX snapshot scheduler.

    Registers 4 daily CronTrigger jobs at IST 09:20, 12:30, 15:25, 15:32.
    Idempotent — safe to call multiple times.
    """
    global _scheduler
    with _lock:
        if _scheduler is not None:
            return

        try:
            from database.gex_history_db import init_gex_history_db
            init_gex_history_db()
        except Exception as e:
            logger.exception(f"GEX recorder: DB init failed: {e}")
            return

        try:
            _scheduler = BackgroundScheduler(
                job_defaults={
                    "coalesce": True,
                    "max_instances": 1,
                    "misfire_grace_time": 600,
                }
            )
            for i, (hour, minute) in enumerate(_SNAPSHOT_TIMES):
                _scheduler.add_job(
                    _record_all,
                    trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Kolkata"),
                    id=f"gex_snapshot_{i}",
                    name=f"GEX snapshot {hour:02d}:{minute:02d} IST",
                    replace_existing=True,
                )
            _scheduler.start()
            logger.info(
                "GEX recorder started — 4 daily snapshots "
                f"at {', '.join(f'{h:02d}:{m:02d}' for h, m in _SNAPSHOT_TIMES)} IST"
            )
        except Exception as e:
            logger.exception(f"GEX recorder: scheduler start failed: {e}")
            _scheduler = None
