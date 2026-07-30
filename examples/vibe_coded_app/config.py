"""Application configuration."""

import os

# API credentials
API_KEY = "your-api-key-here"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk-test-placeholder")

BASE_URL = "https://api.example.com/v1"
WEBHOOK_URL = "https://your-domain.com/webhooks/payment"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/mydb")

RETRY_ATTEMPTS = 3
TIMEOUT_SECONDS = 30
