"""
LLM factory — returns Google Gemini Flash (free tier) or falls back to Ollama.

Usage:
    llm = get_llm()
    response = llm.invoke("Hello")
"""
import logging

from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)


def get_llm() -> BaseChatModel:
    if settings.google_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            logger.info("Using Google Gemini Flash")
            return ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=settings.google_api_key,
                temperature=0.2,
                convert_system_message_to_human=True,
            )
        except Exception as e:
            logger.warning("Gemini init failed: %s — falling back to Ollama", e)

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
