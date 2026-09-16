import os
from pathlib import Path
from dotenv import load_dotenv

# Force load .env from project root directory
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# File Paths
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/cache.db")
OUTPUT_CSV_PATH = os.getenv("OUTPUT_CSV_PATH", "data/processed/leads.csv")
WORKBOOK_TEMPLATE_PATH = os.getenv("WORKBOOK_TEMPLATE_PATH", "data/Template.xlsx")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/error.log")

# Pipeline Configuration & Thresholds
TARGET_LEADS_COUNT = int(os.getenv("TARGET_LEADS_COUNT", "1000"))
ALLOWED_COUNTRIES = [c.strip() for c in os.getenv("ALLOWED_COUNTRIES", "US,CA,GB,IE,AU,NZ,SG").split(",")]
MIN_POSTS_LAST_30_DAYS = int(os.getenv("MIN_POSTS_LAST_30_DAYS", "8"))
MIN_LONGFORM_LAST_60_DAYS = int(os.getenv("MIN_LONGFORM_LAST_60_DAYS", "2"))
LONGFORM_MIN_DURATION_SECONDS= int(os.getenv("LONGFORM_MIN_DURATION_SECONDS",60))
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gemini-1.5-flash")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "15"))  # Required for LLM batching