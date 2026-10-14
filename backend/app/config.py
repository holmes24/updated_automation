"""
Central configuration — all tunable values live here.
Per our design decision: thresholds must be adjustable without touching
pipeline logic. Values below are starting defaults, meant to be tuned
after the pilot period against real submission data.
"""

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = os.getenv("ENVIRONMENT", "development")
    # --- Interakt credentials ---
    interakt_api_key: str = os.getenv("INTERAKT_API_KEY", "")
    interakt_webhook_secret: str = os.getenv("INTERAKT_WEBHOOK_SECRET", "")
    interakt_base_url: str = "https://api.interakt.ai/v1/public"

    # --- Admin (for anomaly alerts) ---
    admin_country_code: str = os.getenv("ADMIN_COUNTRY_CODE", "+91")
    admin_phone_number: str = os.getenv(
        "ADMIN_PHONE_NUMBER", ""
    )  # without country code
    admin_session_window_hours: float = (
        24.0  # matches WhatsApp's free-form session rule
    )

    # --- CMS authentication (JWT) ---
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")  # MUST be set in .env, no safe default
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    app_api_key: str = os.getenv("APP_API_KEY", "")  # gates /auth/login specifically
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")

    # --- Database (MongoDB) ---
    mongodb_url: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "attendance_agent")
    mongodb_tls: bool = os.getenv("MONGODB_TLS", "false").lower() == "true"
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")

    # --- Redis Streams ---
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_stream_maxlen: int = int(os.getenv("REDIS_STREAM_MAXLEN", "100000"))
    worker_consumer_name: str = os.getenv("WORKER_CONSUMER_NAME", "attendance-worker-1")
    notification_consumer_name: str = os.getenv("NOTIFICATION_CONSUMER_NAME", "notification-worker-1")
    worker_batch_size: int = int(os.getenv("WORKER_BATCH_SIZE", "5"))
    worker_block_ms: int = int(os.getenv("WORKER_BLOCK_MS", "5000"))
    worker_max_retries: int = int(os.getenv("WORKER_MAX_RETRIES", "5"))
    worker_retry_delay_seconds: float = float(os.getenv("WORKER_RETRY_DELAY_SECONDS", "2"))
    notification_max_retries: int = int(os.getenv("NOTIFICATION_MAX_RETRIES", "5"))
    notification_retry_delay_seconds: float = float(os.getenv("NOTIFICATION_RETRY_DELAY_SECONDS", "3"))

    # --- Tunable verification thresholds (Problem 2 from planning) ---
    face_match_pass_threshold: float = 0.70  # >= this => verified match
    face_match_uncertain_threshold: float = (
        0.50  # between this and pass => flag for review
    )
    geofence_radius_meters: float = (
        5000.0  # default per-person radius when no custom value is configured
    )
    shift_window_start: str = (
        "09:00"  # confirmed policy default (with per-employee override)
    )
    shift_window_end: str = "18:00"
    shift_grace_minutes: int = 15

    # --- Duplicate detection ---
    duplicate_hash_hamming_threshold: int = int(
        os.getenv("DUPLICATE_HASH_HAMMING_THRESHOLD", "6")
    )
    normalized_duplicate_hash_hamming_threshold: int = int(
        os.getenv("NORMALIZED_DUPLICATE_HASH_HAMMING_THRESHOLD", "8")
    )

    # --- Passive anti-spoofing / image-quality guard ---
    liveness_enabled: bool = os.getenv("LIVENESS_ENABLED", "true").lower() == "true"
    liveness_min_face_ratio: float = float(os.getenv("LIVENESS_MIN_FACE_RATIO", "0.08"))
    liveness_min_sharpness: float = float(os.getenv("LIVENESS_MIN_SHARPNESS", "35.0"))

    class Config:
        env_file = ".env"


settings = Settings()
