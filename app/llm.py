"""
LLM factory — supports OpenAI and Groq.

Usage:
    llm = get_llm()                                          # from .env settings
    llm = get_llm("openai", "sk-...", "gpt-4o-mini")        # user-provided key
    llm = get_llm("groq",   "gsk_...", "llama-3.3-70b-versatile")
"""
import logging

from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)

OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1"]

# Preference order, best-first. Model availability differs per Groq account tier
# and region, so the requested model is validated against /v1/models at runtime.
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]


def _resolve_groq_model(api_key: str, requested: str) -> str:
    """Pick a model the account can actually reach, preferring `requested`."""
    import httpx

    try:
        resp = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        available = {m["id"] for m in resp.json().get("data", [])}
    except Exception as e:
        logger.warning("Could not list Groq models (%s) — using %s as-is", e, requested)
        return requested

    if requested in available:
        return requested

    for candidate in GROQ_MODELS:
        if candidate in available:
            logger.warning("Groq model %s unavailable — falling back to %s", requested, candidate)
            return candidate

    raise RuntimeError(
        f"Groq model '{requested}' is not available on this account. "
        f"Available models: {', '.join(sorted(available)) or 'none'}"
    )


def get_llm(
    provider: str = "",
    api_key: str = "",
    model: str = "",
) -> BaseChatModel:
    """
    Return an LLM instance.
    If provider/api_key are given, use them directly.
    Otherwise fall back to .env settings.
    """
    resolved_provider = provider or ("openai" if settings.openai_api_key else "groq")
    resolved_key = api_key or (
        settings.openai_api_key if resolved_provider == "openai" else settings.groq_api_key
    )

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI
        resolved_model = model or settings.openai_model
        logger.info("Using OpenAI model: %s", resolved_model)
        return ChatOpenAI(
            model=resolved_model,
            api_key=resolved_key,
            temperature=0.2,
            max_tokens=4096,
        )

    # Default: Groq
    from langchain_groq import ChatGroq
    if not resolved_key:
        raise RuntimeError("No Groq API key provided. Paste one in the form or set GROQ_API_KEY.")
    resolved_model = _resolve_groq_model(resolved_key, model or settings.groq_model)
    logger.info("Using Groq model: %s", resolved_model)
    return ChatGroq(
        model=resolved_model,
        api_key=resolved_key,
        temperature=0.2,
        max_tokens=4096,
    )
