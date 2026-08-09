"""
POST /process-github-issue

Accepts a GitHub repo URL + issue number, fetches the issue title/body/comments
from the GitHub API, then runs the full autonomous pipeline (clone → index →
fix → test → PR).
"""
import logging
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.indexing_agent import RepositoryIndexingAgent
from app.github.client import GitHubClient
from app.github.cloner import RepoCloner
from app.llm import get_llm
from app.models.issue import IssueInput
from app.models.pr import PRDraft
from app.workflow.graph import build_graph

router = APIRouter(prefix="/process-github-issue", tags=["github-issues"])
logger = logging.getLogger(__name__)


class ProcessGitHubIssueRequest(BaseModel):
    github_url: str
    issue_number: int
    llm_provider: str = "groq"          # "openai" or "groq"
    llm_api_key: str = ""               # user's own API key
    llm_model: str = ""                 # e.g. gpt-4o-mini or llama-3.3-70b-versatile
    github_token: str = ""              # user's GitHub PAT


class ProcessGitHubIssueResponse(BaseModel):
    issue_number: int
    issue_title: str
    pr_url: str | None = None
    pr_number: int | None = None
    pr_title: str | None = None
    root_cause: str | None = None
    files_changed: list[str] = []
    test_passed: bool = False
    cloned_to: str | None = None
    error: str | None = None


@router.post("", response_model=ProcessGitHubIssueResponse)
async def process_github_issue(request: ProcessGitHubIssueRequest) -> ProcessGitHubIssueResponse:
    """
    Full autonomous pipeline triggered by a GitHub issue number:
    1. Fetch issue title + body + comments from GitHub API
    2. Clone the repo (or pull if already cloned)
    3. Index the repo with Tree-sitter + FAISS
    4. Analyze → retrieve context → generate fix → apply patch
    5. Run tests in Docker → open PR if tests pass
    """
    repository_path: str | None = None
    try:
        # Resolve github token — request overrides .env
        from app.config import settings as app_settings
        github_token = request.github_token or app_settings.github_token

        # Step 1: fetch issue from GitHub
        gh = GitHubClient(github_token=github_token)
        fetched = gh.fetch_issue(request.github_url, request.issue_number)
        logger.info("Fetched issue #%d: %s", fetched.number, fetched.title)

        # Step 2: clone or pull repo
        repository_path = RepoCloner().clone_or_pull(request.github_url, github_token=github_token)
        logger.info("Repo ready at %s", repository_path)

        # Step 3: index repo
        RepositoryIndexingAgent().index_repository(repository_path)
        logger.info("Indexing complete")

        # Build per-request graph with user's LLM
        llm = get_llm(request.llm_provider, request.llm_api_key, request.llm_model)
        graph = build_graph(llm=llm, github_token=github_token)

        # Step 4: run workflow
        issue = IssueInput(
            title=fetched.title,
            description=fetched.description,
            repository_path=repository_path,
            issue_number=fetched.number,
            labels=fetched.labels,
            github_url=request.github_url,
        )
        initial_state = {
            "issue": issue,
            "analysis": None,
            "retrieval": None,
            "patch_set": None,
            "test_result": None,
            "pr_draft": None,
            "error": None,
            "retry_count": 0,
        }
        config = {"configurable": {"thread_id": f"gh-issue-{fetched.number}"}}
        logger.info("Starting workflow for issue #%d", fetched.number)
        final_state = await graph.ainvoke(initial_state, config=config)

        pr: PRDraft | None = final_state.get("pr_draft")
        test_result = final_state.get("test_result")
        analysis = final_state.get("analysis")

        response = ProcessGitHubIssueResponse(
            issue_number=fetched.number,
            issue_title=fetched.title,
            pr_url=pr.pr_url if pr else None,
            pr_number=pr.pr_number if pr else None,
            pr_title=pr.title if pr else None,
            root_cause=analysis.root_cause if analysis else None,
            files_changed=pr.files_changed if pr else [],
            test_passed=test_result.passed if test_result else False,
            cloned_to=repository_path,
            error=final_state.get("error"),
        )
        return response

    except Exception as e:
        logger.exception("Workflow failed for issue #%d", request.issue_number)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up cloned repo to keep disk free
        try:
            if repository_path:
                shutil.rmtree(repository_path, ignore_errors=True)
                logger.info("Cleaned up workspace: %s", repository_path)
        except Exception:
            pass
