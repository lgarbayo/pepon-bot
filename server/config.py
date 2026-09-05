"""Runtime configuration, read from the environment with defaults sane
for local development. Deliberately just os.environ — no config
framework, nothing to install, no file to keep in sync with .env.
"""
import os

GEMMA_ENABLED = os.environ.get("GEMMA_ENABLED", "true").lower() not in ("false", "0", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
GEMMA_TIMEOUT_SECONDS = float(os.environ.get("GEMMA_TIMEOUT_SECONDS", "8"))
GEMMA_DEBUG = os.environ.get("GEMMA_DEBUG", "false").lower() not in ("false", "0", "")
