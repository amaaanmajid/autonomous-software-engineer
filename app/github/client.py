import logging
from functools import lru_cache

from github import Github, GithubException
from github.Repository import Repository

from app.config import settings

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self) -> None:
        if not settings.github_token:
            logger.warning("GITHUB_TOKEN not set — GitHub operations will be skipped")
            self._gh: Github | None = None
        else:
            self._gh = Github(settings.github_token)

    def get_repo(self) -> Repository | None:
        if not self._gh:
            return None
        try:
            return self._gh.get_repo(
                f"{settings.github_repo_owner}/{settings.github_repo_name}"
            )
        except GithubException as e:
            logger.error("Failed to get GitHub repo: %s", e)
            return None

    @property
    def available(self) -> bool:
        return self._gh is not None


@lru_cache(maxsize=1)
def get_github_client() -> GitHubClient:
    return GitHubClient()
