import logging

from app.github.client import GitHubClient, get_github_client
from app.models.pr import PRDraft

logger = logging.getLogger(__name__)


class PRBuilder:
    def __init__(self, github_token: str = "") -> None:
        self._github_token = github_token

    def create_pr(self, draft: PRDraft) -> PRDraft:
        """Create a GitHub pull request. Returns draft unchanged if GitHub is unavailable."""
        client = GitHubClient(github_token=self._github_token) if self._github_token else get_github_client()
        if not client.available:
            logger.warning("GitHub not configured — skipping PR creation. Draft returned as-is.")
            return draft

        repo = client.get_repo(draft.repo_slug)
        if not repo:
            logger.warning("Could not fetch GitHub repo — skipping PR creation.")
            return draft

        try:
            pr = repo.create_pull(
                title=draft.title,
                body=draft.description,
                base=draft.base_branch,
                head=draft.head_branch,
            )
            logger.info("PR created: %s", pr.html_url)
            return PRDraft(
                **draft.model_dump(exclude={"pr_url", "pr_number"}),
                pr_url=pr.html_url,
                pr_number=pr.number,
            )
        except Exception as e:
            logger.error("Failed to create PR: %s", e)
            return draft
