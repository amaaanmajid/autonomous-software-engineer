import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # GitHub
    github_token: str = ""
    github_repo_owner: str = ""
    github_repo_name: str = ""

    # Commit author for generated fixes. A container has no global git config,
    # and `git commit` refuses to run without an identity.
    git_author_name: str = "autonomous-software-engineer"
    git_author_email: str = "bot@users.noreply.github.com"

    # Paths
    workspace_dir: Path = Path("/tmp/ase_workspace")
    faiss_index_path: Path = Path("./data/faiss_index")
    symbol_index_path: Path = Path("./data/symbol_index.json")
    call_graph_path: Path = Path("./data/call_graph.json")

    # Docker
    docker_image_name: str = "ase-test-runner"
    docker_timeout: int = 120

    # App
    log_level: str = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Retrieval
    embedding_model: str = "all-MiniLM-L6-v2"
    retrieval_top_k: int = 5

    # LangGraph
    max_retries: int = 3


settings = Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
