"""
Options Intelligence Dashboard API Endpoint

POST /api/v1/optdashboard/snapshot  — full GEX + OI + Vol + Strategies snapshot
GET  /api/v1/optdashboard/gexhistory — historical GEX time-series

These endpoints expose the pre-computed options intelligence dashboard data
via API-key authentication so it can be consumed by MCP and external tools.
"""

import os

from flask import request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from database.gex_history_db import get_gex_history
from limiter import limiter
from services.optdashboard_service import get_dashboard_snapshot
from utils.logging import get_logger

logger = get_logger(__name__)
api = Namespace("optdashboard", description="Options Intelligence Dashboard API")

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

EXPIRY_RE = r"^\d{2}[A-Z]{3}\d{2}$"


class SnapshotSchema(Schema):
    apikey = fields.Str(required=True)
    underlying = fields.Str(load_default="NIFTY", validate=validate.Length(max=20))
    exchange = fields.Str(load_default="NSE_INDEX", validate=validate.Length(max=20))
    expiry_date = fields.Str(required=True, validate=validate.Regexp(EXPIRY_RE))
    next_expiry_date = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(EXPIRY_RE),
    )


class GexHistorySchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(load_default="NIFTY", validate=validate.Length(max=20))
    days = fields.Int(load_default=60, validate=validate.Range(min=1, max=365))


@api.route("/snapshot", strict_slashes=False)
class OptDashboardSnapshot(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get full options intelligence snapshot (GEX, OI, Vol, Probable Ranges, Strategies)"""
        try:
            data = SnapshotSchema().load(request.json or {})
        except ValidationError as err:
            return {"status": "error", "message": err.messages}, 400

        try:
            underlying = data["underlying"].strip().upper()
            exchange = data["exchange"].strip().upper()
            expiry_date = data["expiry_date"].strip().upper()
            next_expiry_date = (data.get("next_expiry_date") or "").strip().upper() or None

            success, response, status_code = get_dashboard_snapshot(
                underlying=underlying,
                exchange=exchange,
                expiry_date=expiry_date,
                next_expiry_date=next_expiry_date,
                api_key=data["apikey"],
            )
            return response, status_code

        except Exception as e:
            logger.exception(f"Unexpected error in optdashboard snapshot endpoint: {e}")
            return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/gexhistory", strict_slashes=False)
class GexHistory(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get historical GEX time-series snapshots for a symbol"""
        try:
            data = GexHistorySchema().load(request.json or {})
        except ValidationError as err:
            return {"status": "error", "message": err.messages}, 400

        try:
            symbol = data["symbol"].strip().upper()
            days = data["days"]
            rows = get_gex_history(symbol=symbol, days=days)
            return {"status": "success", "symbol": symbol, "days": days, "data": rows}, 200

        except Exception as e:
            logger.exception(f"Unexpected error in GEX history endpoint: {e}")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
