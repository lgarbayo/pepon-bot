"""Runtime configuration, read from the environment with defaults sane
for local development. Deliberately just os.environ — no config
framework, nothing to install, no file to keep in sync with .env.
"""
import os

GEMMA_ENABLED = os.environ.get("GEMMA_ENABLED", "true").lower() not in ("false", "0", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
# "gemma3:4b" (Ollama's own registry) is the intended tag, but its blob
# host (Cloudflare R2) is unreachable from this network — pulled instead
# via Ollama's HuggingFace passthrough, which is the same weights under
# a different tag. Switch back to "gemma3:4b" once that host is reachable.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M")
# The first multimodal turn also loads/encodes the image; eight seconds
# proved too short locally. Bound both attempts below the phone's timeout.
GEMMA_TIMEOUT_SECONDS = float(os.environ.get("GEMMA_TIMEOUT_SECONDS", "20"))
GEMMA_TOTAL_TIMEOUT_SECONDS = float(os.environ.get("GEMMA_TOTAL_TIMEOUT_SECONDS", "35"))
GEMMA_DEBUG = os.environ.get("GEMMA_DEBUG", "false").lower() not in ("false", "0", "")

# "small" is the sweet spot for short Spanish utterances: noticeably
# more accurate than "base" for Spanish, still fast on a dedicated GPU.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "es")
