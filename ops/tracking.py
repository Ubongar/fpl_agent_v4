"""Logs recommendations + their outcomes."""
from datetime import datetime
import json
from db.connection import get_session
from sqlalchemy import text


def log_recommendation(gw, rec_type, payload, session=None):
    """If a session is passed, use it (avoids Neon cold-start on a fresh
    connection). Otherwise open a short-lived one."""
    own_session = session is None
    if own_session:
        session = get_session()
    try:
        session.execute(text(
            "INSERT INTO recommendations (gw, rec_type, payload, created_at) "
            "VALUES (:gw,:t,:p,:c)"
        ), dict(gw=gw, t=rec_type, p=json.dumps(payload), c=datetime.utcnow()))
        if own_session:
            session.commit()
    finally:
        if own_session:
            session.close()


def evaluate_pending_recommendations(gw, actual_outcomes, session=None):
    own_session = session is None
    if own_session:
        session = get_session()
    try:
        for rec_id, outcome in actual_outcomes.items():
            session.execute(text(
                "UPDATE recommendations SET actual_outcome=:o, evaluated_at=:t "
                "WHERE rec_id=:id"
            ), dict(o=json.dumps(outcome), t=datetime.utcnow(), id=rec_id))
        if own_session:
            session.commit()
    finally:
        if own_session:
            session.close()