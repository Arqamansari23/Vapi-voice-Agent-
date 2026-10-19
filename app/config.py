"""Runtime configuration, read from environment variables (never hardcoded)."""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Railway injects DATABASE_URL when the Postgres plugin is attached.
    # Locally we fall back to a SQLite file so the app runs with zero setup.
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./patients.db")

    # Shared secret Vapi sends in the X-Vapi-Secret header on tool/webhook calls.
    # If empty, the check is skipped (handy for local testing only).
    vapi_secret: str = os.getenv("VAPI_SECRET", "")

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Insert two demo patients on first start when the table is empty.
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"


settings = Settings()
