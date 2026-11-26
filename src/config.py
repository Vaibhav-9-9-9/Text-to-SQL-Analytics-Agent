import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "sales.db"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
TRACES_LOG_PATH = PROJECT_ROOT / "langsmith_traces.jsonl"

# Benchmark Reference Date as specified in PDF
TODAY_DATE = "2026-11-18"

# Model and API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.0"))
MAX_RETRIES = 3

# Gemini 2.0 / 1.5 Flash Pricing (per 1,000,000 tokens)
# Input: $0.10 per 1M tokens ($0.00010 per 1k)
# Output: $0.40 per 1M tokens ($0.00040 per 1k)
PRICE_PER_M_INPUT = 0.10
PRICE_PER_M_OUTPUT = 0.40
PRICE_PER_M_BLENDED = 0.25 # Standard blended rate reference ($0.25 per 1M tokens)

# LangSmith Configuration
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "text-to-sql-analytics-agent")
