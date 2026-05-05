"""
Options Intelligence Dashboard Blueprint

Endpoints:
    POST /optdashboard/api/snapshot  — full market snapshot (GEX + OI + Vol + Strategies)
"""

import re

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.optdashboard_service import get_dashboard_snapshot
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

optdashboard_bp = Blueprint("optdashboard_bp", __name__, url_prefix="/")

EXPIRY_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9]+$")
EXCHANGE_RE = re.compile(r"^[A-Z0-9_]+$")


@optdashboard_bp.route("/optdashboard/api/snapshot", methods=["POST"])
@cross_origin()
@check_session_validity
def dashboard_snapshot():
    """Build a full options intelligence snapshot for NIFTY."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify({
                "status": "error",
                "message": "API key not configured. Please generate an API key in /apikey",
            }), 401

        data = request.get_json(silent=True) or {}
        underlying = data.get("underlying", "NIFTY").strip()[:20].upper()
        exchange = data.get("exchange", "NFO").strip()[:20].upper()
        expiry_date = data.get("expiry_date", "").strip()[:10].upper()
        next_expiry_date = (data.get("next_expiry_date") or "").strip()[:10].upper() or None

        if not expiry_date:
            return jsonify({"status": "error", "message": "expiry_date is required"}), 400
        if not SYMBOL_RE.match(underlying) or not EXCHANGE_RE.match(exchange):
            return jsonify({"status": "error", "message": "Invalid input format"}), 400
        if not EXPIRY_RE.match(expiry_date):
            return jsonify({"status": "error", "message": "Invalid expiry_date format. Expected DDMMMYY"}), 400
        if next_expiry_date and not EXPIRY_RE.match(next_expiry_date):
            return jsonify({"status": "error", "message": "Invalid next_expiry_date format. Expected DDMMMYY"}), 400

        success, response, status_code = get_dashboard_snapshot(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            next_expiry_date=next_expiry_date,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in dashboard snapshot API: {e}")
        return jsonify({"status": "error", "message": "An error occurred processing your request"}), 500
