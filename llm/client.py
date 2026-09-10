"""Thin wrapper around an OpenAI-compatible endpoint. Fails silently if
OPENAI_API_KEY is unset, so the UI degrades gracefully."""
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        return _client
    except Exception as e:
        print(f"[llm] Init failed: {e!r}")
        return None


def is_enabled() -> bool:
    return bool(OPENAI_API_KEY)


def explain_pick(pick_type, context):
    client = _get_client()
    if client is None:
        return None
    prompt = (
        f"You are an FPL analyst. Explain in 2-4 short sentences why the model "
        f"recommended this {pick_type}. Be concrete: reference the numbers. "
        f"Do not hedge. Do not use bullet points.\n\nData: {context}"
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a concise FPL analyst."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200, temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[llm] explain_pick failed: {e!r}")
        return None