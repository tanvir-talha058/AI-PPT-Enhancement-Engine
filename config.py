import logging
import logging.handlers
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
ALLOWED_EXTENSIONS = {".pptx"}

# File size and validation constants
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
FILE_CLEANUP_AGE_HOURS = int(os.getenv("FILE_CLEANUP_AGE_HOURS", "24"))

# Preview and UI constants
PREVIEW_LIMIT = int(os.getenv("PREVIEW_LIMIT", "3"))
PREVIEW_LENGTH_LIMIT = int(os.getenv("PREVIEW_LENGTH_LIMIT", "200"))

# Job tracking constants
MAX_JOB_POLL_HOURS = int(os.getenv("MAX_JOB_POLL_HOURS", "24"))
LOCAL_JOB_CLEANUP_INTERVAL_SECONDS = int(os.getenv("LOCAL_JOB_CLEANUP_INTERVAL_SECONDS", "3600"))

# Rate limiting
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "100"))

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = BASE_DIR / "logs" / "app.log"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


load_dotenv(BASE_DIR / ".env")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("RQ_QUEUE_NAME", "ppt_tasks")
USE_REDIS = os.getenv("USE_REDIS", "auto").lower()

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = os.getenv("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
GEMINI_RETRY_DELAY_SECONDS = float(os.getenv("GEMINI_RETRY_DELAY_SECONDS", "2"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

HF_API_KEY = os.getenv("HF_API_KEY", "")
HF_URL = os.getenv("HF_URL", "https://api-inference.huggingface.co/models")
HF_MODEL = os.getenv("HF_MODEL", "google/flan-t5-large")


def ensure_directories() -> None:
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def setup_logging(name: str) -> logging.Logger:
    """Configure and return a logger instance with file and console handlers."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    
    if logger.handlers:
        return logger
    
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(LOG_LEVEL)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_ai_provider_label() -> str:
    if GEMINI_API_KEY:
        return f"Gemini API ({GEMINI_MODEL})"
    if OPENROUTER_API_KEY:
        return f"OpenRouter API ({OPENROUTER_MODEL})"
    if HF_API_KEY:
        return f"Hugging Face API ({HF_MODEL})"
    return "No API configured"
