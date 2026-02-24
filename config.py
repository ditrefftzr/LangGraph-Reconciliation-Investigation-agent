"""
Centralised configuration.

All model strings, API settings, and environment-dependent paths
are defined here. Never hardcode these values elsewhere.
"""

import os
from pathlib import Path

# ── LLM ──────────────────────────────────────────────────────────────────────

LLM_MODEL = "gemma-3-27b-it"   # Gemma 3 27B via Gemini API (free tier)

# ── Database ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "reconciliation.db"))

# ── Output ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = PROJECT_ROOT / "output"
