"""Logs every recommendation the system makes and, once the GW completes,
its actual outcome -- so real (not backtested) performance can be measured."""
from datetime import datetime
import json
from db.connection import get_session
from sqlalchemy import text


def log_recommendation(gw: int, rec_type: str, payload: dict):
    session = get_session()
    try:
        session.execute(text(
            "INSERT INTO recommendations (gw, rec_type, payload, created_at) "
            "VALUES (:gw,:t,:p,:c)"
        ), dict(gw=gw, t=rec_type, p=json.dumps(payload), c=datetime.utcnow()))
        session.commit()
    finally:
        session.close()


def evaluate_pending_recommendations(gw: int, actual_outcomes: dict):
    """actual_outcomes keyed by rec_id -> outcome dict, computed after the GW plays out."""
    session = get_session()
    try:
        for rec_id, outcome in actual_outcomes.items():
            session.execute(text(
                "UPDATE recommendations SET actual_outcome=:o, evaluated_at=:t WHERE rec_id=:id"
            ), dict(o=json.dumps(outcome), t=datetime.utcnow(), id=rec_id))
        session.commit()
    finally:
        session.close()