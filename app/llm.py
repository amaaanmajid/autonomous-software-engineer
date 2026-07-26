"""
LLM factory — returns Groq (free, fast) or falls back to Ollama.

Usage:
    llm = get_llm()
    response = llm.invoke("Hello")
"""
import logging

from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)


def get_llm() -> BaseChatModel:
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            logger.info("Using Groq model: %s", settings.groq_model)
            return ChatGroq(
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                temperature=0.2,
                max_tokens=4096,
            )
        except Exception as e:
            logger.warning("Groq init failed: %s — falling back to Ollama", e)

    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        from langchain_community.chat_models.ollama import (
            ChatOllama,  # type: ignore[no-redef]
        )
    logger.info("Using Ollama model: %s", settings.ollama_model)
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.2,
    )
