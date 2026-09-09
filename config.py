import os
from dotenv import load_dotenv

load_dotenv()  # reads .env if present; falls back to real environment variables

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/fpl_agent")
FPL_BASE = "https://fantasy.premierleague.com/api"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "olori-image")

SEASON_START_GW = 1
CURRENT_GW = int(os.getenv("FPL_CURRENT_GW", "4"))
