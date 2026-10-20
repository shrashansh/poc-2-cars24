"""Runtime settings, all from environment variables so the same code runs locally and on a host."""
import os

from dotenv import load_dotenv

# Local dev: read .env from the project root. Real environment variables win over .env values.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ccc.sqlite3"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# "simple" runs the agents on background threads inside the web process (one-command deploy).
# "celery" hands the same functions to Celery workers + beat (see ccc/celery_app.py).
RUN_MODE = os.getenv("RUN_MODE", "simple")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# LLM classifier (OpenAI API). Without a key the rules-based classifier runs instead.
# OPENAI_BASE_URL is optional: point it at any OpenAI-compatible endpoint (Azure, OpenRouter, Ollama, vLLM...).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None

# Demo clock: how many real seconds stand for one SLA hour. 30 => a 4 h critical SLA runs out in 2 minutes, 24 h in 12.
SLA_SECONDS_PER_HOUR = float(os.getenv("SLA_SECONDS_PER_HOUR", "30"))

# Scheduler intervals in seconds (simple mode and Celery beat both read these)
COLLECT_EVERY = int(os.getenv("COLLECT_EVERY", "15"))
SLA_EVERY = int(os.getenv("SLA_EVERY", "10"))

LINK_TTL_DAYS = int(os.getenv("LINK_TTL_DAYS", "30"))
PHONE_SALT = os.getenv("PHONE_SALT", "demo-salt-change-me")
DEMO_SHOW_OTP = os.getenv("DEMO_SHOW_OTP", "1") == "1"   # no SMS gateway in the POC: the OTP is shown on screen
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
