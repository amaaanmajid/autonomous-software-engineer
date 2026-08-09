import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from github import Github, GithubException
from github.Repository import Repository

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FetchedIssue:
    number: int
    title: str
    description: str  # body + top comments combined
    labels: list[str]


class GitHubClient:
    def __init__(self, github_token: str = "") -> None:
        token = github_token or settings.github_token
        if not token:
            logger.warning("GITHUB_TOKEN not set — GitHub operations will be skipped")
            self._gh: Github | None = None
        else:
            self._gh = Github(token)

    def get_repo(self, repo_slug: str = "") -> Repository | None:
        if not self._gh:
            return None
        slug = repo_slug or f"{settings.github_repo_owner}/{settings.github_repo_name}"
        try:
            return self._gh.get_repo(slug)
        except GithubException as e:
            logger.error("Failed to get GitHub repo: %s", e)
            return None

    def fetch_issue(self, github_url: str, issue_number: int) -> FetchedIssue:
        """
        Fetch a specific issue from any GitHub repo URL.
        Combines the issue body with up to 5 comments for richer context.
        """
        if not self._gh:
            raise RuntimeError("GITHUB_TOKEN is not set — cannot fetch issues")

        repo_slug = _slug_from_url(github_url)
        repo = self._gh.get_repo(repo_slug)
        issue = repo.get_issue(issue_number)

        parts = [issue.body or ""]
        for comment in list(issue.get_comments())[:5]:
            if comment.body:
                parts.append(f"--- Comment by {comment.user.login} ---\n{comment.body}")

        return FetchedIssue(
            number=issue.number,
            title=issue.title,
            description="\n\n".join(p for p in parts if p),
            labels=[lbl.name for lbl in issue.labels],
        )

    @property
    def available(self) -> bool:
        return self._gh is not None


def _slug_from_url(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL."""
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise ValueError(f"Cannot parse GitHub URL: {url}")
    return match.group(1)


@lru_cache(maxsize=1)
def get_github_client() -> GitHubClient:
    return GitHubClient()
