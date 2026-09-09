"""Thin NL layer over the optimizers/models -- explains outputs, doesn't
compute them. Uses OpenAI (model configured via OPENAI_MODEL, default
'olori-image'). Requires OPENAI_API_KEY in the environment (see .env.example)."""
import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

_client = None

def _get_client():
    """Lazy init -- importing this module must not crash before OPENAI_API_KEY
    is actually set (e.g. during tests, or before .env is configured)."""
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client

SYSTEM_PROMPT = (
    "You are an FPL decision-support agent. You are given structured JSON output "
    "from deterministic models and optimizers (expected points, transfer suggestions, "
    "captaincy rankings, chip timing). Explain the recommendation in plain language, "
    "cite the specific numbers you were given, and flag genuine uncertainty (e.g. low "
    "start_prob, small backtest sample size). Never invent stats not present in the input."
)

def explain_recommendation(rec_type: str, payload: dict, user_question: str = "") -> str:
    resp = _get_client().chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Recommendation type: {rec_type}\nData: {json.dumps(payload)}\n"
                f"User question: {user_question or '(none, just explain it)'}"
            )},
        ],
    )
    return resp.choices[0].message.content
