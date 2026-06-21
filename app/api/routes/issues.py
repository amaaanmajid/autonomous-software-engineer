import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.models.issue import IssueInput
from app.models.pr import PRDraft
from app.workflow.graph import compiled_graph
from app.github.cloner import RepoCloner
from app.agents.indexing_agent import RepositoryIndexingAgent

router = APIRouter(prefix="/process-issue", tags=["issues"])
logger = logging.getLogger(__name__)


class ProcessIssueRequest(BaseModel):
    title: str
    description: str
    github_url: str                     # e.g. https://github.com/owner/repo
    issue_number: Optional[int] = None
    labels: list[str] = []


class ProcessIssueResponse(BaseModel):
    pr_url: Optional[str]
    pr_number: Optional[int]
    pr_title: Optional[str]
    root_cause: Optional[str]
    files_changed: list[str]
    test_passed: bool
    cloned_to: Optional[str] = None
    error: Optional[str] = None


@router.post("", response_model=ProcessIssueResponse)
async def process_issue(request: ProcessIssueRequest) -> ProcessIssueResponse:
    """
    Run the full autonomous pipeline:
    1. Clone the GitHub repo (or pull if already cloned)
    2. Index the repo with Tree-sitter + FAISS
    3. Analyze issue → retrieve context → generate fix
    4. Apply patch → run tests → open PR

    Returns the PR URL on success.
    """
    try:
        # Step 1: clone or pull repo
        cloner = RepoCloner()
        repository_path = cloner.clone_or_pull(request.github_url)
        logger.info("Repo ready at %s", repository_path)

        # Step 2: auto-index the cloned repo
        logger.info("Indexing repo at %s", repository_path)
        RepositoryIndexingAgent().index_repository(repository_path)
        logger.info("Indexing complete")

        issue = IssueInput(
            title=request.title,
            description=request.description,
            repository_path=repository_path,
            issue_number=request.issue_number,
            labels=request.labels,
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

        config = {"configurable": {"thread_id": f"issue-{request.issue_number or 'manual'}"}}

        logger.info("Starting workflow for: %s", request.title)
        final_state = await compiled_graph.ainvoke(initial_state, config=config)

        pr: Optional[PRDraft] = final_state.get("pr_draft")
        test_result = final_state.get("test_result")
        analysis = final_state.get("analysis")

        return ProcessIssueResponse(
            pr_url=pr.pr_url if pr else None,
            pr_number=pr.pr_number if pr else None,
            pr_title=pr.title if pr else None,
            root_cause=analysis.root_cause if analysis else None,
            files_changed=pr.files_changed if pr else [],
            test_passed=test_result.passed if test_result else False,
            cloned_to=repository_path,
            error=final_state.get("error"),
        )

    except Exception as e:
        logger.exception("Workflow failed for issue: %s", request.title)
        raise HTTPException(status_code=500, detail=str(e))
