"""Central configuration. Reads .env at import time via python-dotenv."""
import os
from dotenv import load_dotenv

load_dotenv()

# FPL API
FPL_BASE = "https://fantasy.premierleague.com/api"
CURRENT_GW = int(os.getenv("FPL_CURRENT_GW", "4"))

# Database
DATABASE_URL = os.getenv(
    "FPL_DATABASE_URL",
    "postgresql://fpl_user:changeme@localhost:5433/fpl_agent",
)

# LLM (OpenAI-compatible endpoint)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://94.175.201.194:7777/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "olori-image")

# Model constants (shared between dixon_coles and team_strength)
LEAGUE_AVG_GOALS = 1.4
HOME_ADVANTAGE = 1.15
DIXON_COLES_RHO = -0.05
GOAL_SHARE_WINDOW = 6
MINUTES_HISTORY_WINDOW = 10
RECENCY_HALF_LIFE_GWS = 3.0