"""
GEX History Database

Persists intraday GEX snapshots (net GEX, walls, gamma flip, spot) for
time-series charting in the Options Intelligence Dashboard.

Separate DB at db/gex_history.db following OpenAlgo's 6-DB isolation pattern.
Uses NullPool (same as every other SQLite DB in this project).
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

GEX_HISTORY_DB_URL = os.getenv("GEX_HISTORY_DATABASE_URL", "sqlite:///db/gex_history.db")

gex_engine = create_engine(
    GEX_HISTORY_DB_URL,
    poolclass=NullPool,
    connect_args={"check_same_thread": False},
)

gex_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=gex_engine)
)

GexBase = declarative_base()
GexBase.query = gex_session.query_property()

_IST = timezone(timedelta(hours=5, minutes=30))


class GEXSnapshot(GexBase):
    __tablename__ = "gex_snapshots"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    expiry = Column(String(10), nullable=False)
    spot = Column(Float, nullable=False)
    net_gex = Column(Float, nullable=False)
    call_wall = Column(Float, nullable=True)
    put_wall = Column(Float, nullable=True)
    gamma_flip = Column(Float, nullable=True)


def init_gex_history_db():
    db_path = GEX_HISTORY_DB_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    GexBase.metadata.create_all(gex_engine)
    logger.debug("GEX History DB initialized")


def insert_gex_snapshot(
    symbol: str,
    expiry: str,
    spot: float,
    net_gex: float,
    call_wall: float | None,
    put_wall: float | None,
    gamma_flip: float | None,
) -> bool:
    try:
        row = GEXSnapshot(
            ts=datetime.now(timezone.utc),
            symbol=symbol.upper(),
            expiry=expiry,
            spot=spot,
            net_gex=net_gex,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
        )
        gex_session.add(row)
        gex_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Failed to insert GEX snapshot for {symbol}: {e}")
        gex_session.rollback()
        return False
    finally:
        gex_session.remove()


def get_gex_history(symbol: str, days: int = 60) -> list[dict]:
    """Return GEX snapshots for `symbol` over the last `days` days.

    Converts stored UTC timestamps to IST for display.
    Computes rolling percentile: where does each row's net_gex rank
    within the full query window? 0 = lowest, 100 = highest.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            GEXSnapshot.query
            .filter(GEXSnapshot.symbol == symbol.upper())
            .filter(GEXSnapshot.ts >= cutoff)
            .order_by(GEXSnapshot.ts.asc())
            .all()
        )
        if not rows:
            return []

        all_net_gex = [r.net_gex for r in rows]
        n = len(all_net_gex)

        result = []
        for r in rows:
            rank = sum(1 for v in all_net_gex if v <= r.net_gex)
            percentile = round(rank / n * 100, 1)
            ts_ist = r.ts.astimezone(_IST)
            result.append({
                "ts": ts_ist.isoformat(),
                "expiry": r.expiry,
                "spot": r.spot,
                "net_gex": r.net_gex,
                "call_wall": r.call_wall,
                "put_wall": r.put_wall,
                "gamma_flip": r.gamma_flip,
                "percentile": percentile,
            })
        return result
    except Exception as e:
        logger.exception(f"Failed to get GEX history for {symbol}: {e}")
        return []
    finally:
        gex_session.remove()


def purge_old_gex_snapshots(days: int = 90) -> int:
    """Delete snapshots older than `days` days to keep DB size manageable."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = (
            gex_session.query(GEXSnapshot)
            .filter(GEXSnapshot.ts < cutoff)
            .delete(synchronize_session=False)
        )
        gex_session.commit()
        logger.debug(f"Purged {deleted} old GEX snapshots")
        return deleted
    except Exception as e:
        logger.exception(f"Failed to purge old GEX snapshots: {e}")
        gex_session.rollback()
        return 0
    finally:
        gex_session.remove()
