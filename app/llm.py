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
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]


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
    resolved_model = model or settings.groq_model
    logger.info("Using Groq model: %s", resolved_model)
    return ChatGroq(
        model=resolved_model,
        api_key=resolved_key,
        temperature=0.2,
        max_tokens=4096,
    )
