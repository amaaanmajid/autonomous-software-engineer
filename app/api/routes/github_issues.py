"""
POST /process-github-issue/stream  — SSE streaming (primary)
POST /process-github-issue         — JSON fallback
"""
import json
import logging
import shutil

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
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

# LangGraph node name → stepper index (0-based, matching frontend STEPS array)
NODE_STEP = {
    "analyze_issue":   3,
    "retrieve_context": 4,
    "generate_fix":    5,
    "apply_patch":     6,
    "run_tests":       7,
    "generate_pr":     8,
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


class ProcessGitHubIssueRequest(BaseModel):
    github_url: str
    issue_number: int
    llm_provider: str = "groq"
    llm_api_key: str = ""
    llm_model: str = ""
    github_token: str = ""


# ── Streaming endpoint ────────────────────────────────────────────────────────

@router.post("/stream")
async def process_github_issue_stream(request: ProcessGitHubIssueRequest):
    """SSE stream — emits a progress event after each real step completes."""

    async def generate():
        repository_path: str | None = None
        try:
            from app.config import settings as app_settings
            github_token = request.github_token or app_settings.github_token

            # Step 0 — fetch issue
            yield _sse({"step": 0, "status": "active"})
            gh = GitHubClient(github_token=github_token)
            fetched = gh.fetch_issue(request.github_url, request.issue_number)
            yield _sse({"step": 0, "status": "done"})

            # Step 1 — clone
            yield _sse({"step": 1, "status": "active"})
            repository_path = RepoCloner().clone_or_pull(
                request.github_url, github_token=github_token
            )
            yield _sse({"step": 1, "status": "done"})

            # Step 2 — index
            yield _sse({"step": 2, "status": "active"})
            RepositoryIndexingAgent().index_repository(repository_path)
            yield _sse({"step": 2, "status": "done"})

            # Steps 3-8 — LangGraph (stream node completions)
            llm = get_llm(request.llm_provider, request.llm_api_key, request.llm_model)
            graph = build_graph(llm=llm, github_token=github_token)

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
            config = {"configurable": {"thread_id": f"stream-{fetched.number}"}}

            active_step: int | None = None
            async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
                for node_name in chunk:
                    step_idx = NODE_STEP.get(node_name)
                    if step_idx is None:
                        continue
                    # complete the previous step, activate the new one
                    if active_step is not None:
                        yield _sse({"step": active_step, "status": "done"})
                    yield _sse({"step": step_idx, "status": "active"})
                    active_step = step_idx

            # complete the last node
            if active_step is not None:
                yield _sse({"step": active_step, "status": "done"})

            # pull final state from checkpointer
            snapshot = await graph.aget_state(config)
            final = snapshot.values

            pr: PRDraft | None = final.get("pr_draft")
            test_result = final.get("test_result")
            analysis = final.get("analysis")

            yield _sse({
                "done": True,
                "issue_number": fetched.number,
                "issue_title": fetched.title,
                "pr_url": pr.pr_url if pr else None,
                "pr_number": pr.pr_number if pr else None,
                "pr_title": pr.title if pr else None,
                "root_cause": analysis.root_cause if analysis else None,
                "files_changed": pr.files_changed if pr else [],
                "test_passed": test_result.passed if test_result else False,
                "error": final.get("error"),
            })

        except Exception as e:
            logger.exception("Stream pipeline failed for issue #%d", request.issue_number)
            yield _sse({"error": str(e)})
        finally:
            if repository_path:
                shutil.rmtree(repository_path, ignore_errors=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── JSON fallback (kept for API users) ───────────────────────────────────────

@router.post("")
async def process_github_issue(request: ProcessGitHubIssueRequest):
    repository_path: str | None = None
    try:
        from app.config import settings as app_settings
        github_token = request.github_token or app_settings.github_token

        gh = GitHubClient(github_token=github_token)
        fetched = gh.fetch_issue(request.github_url, request.issue_number)
        repository_path = RepoCloner().clone_or_pull(request.github_url, github_token=github_token)
        RepositoryIndexingAgent().index_repository(repository_path)

        llm = get_llm(request.llm_provider, request.llm_api_key, request.llm_model)
        graph = build_graph(llm=llm, github_token=github_token)

        issue = IssueInput(
            title=fetched.title,
            description=fetched.description,
            repository_path=repository_path,
            issue_number=fetched.number,
            labels=fetched.labels,
            github_url=request.github_url,
        )
        initial_state = {
            "issue": issue, "analysis": None, "retrieval": None,
            "patch_set": None, "test_result": None, "pr_draft": None,
            "error": None, "retry_count": 0,
        }
        config = {"configurable": {"thread_id": f"gh-issue-{fetched.number}"}}
        final_state = await graph.ainvoke(initial_state, config=config)

        pr: PRDraft | None = final_state.get("pr_draft")
        test_result = final_state.get("test_result")
        analysis = final_state.get("analysis")

        return {
            "issue_number": fetched.number,
            "issue_title": fetched.title,
            "pr_url": pr.pr_url if pr else None,
            "pr_number": pr.pr_number if pr else None,
            "pr_title": pr.title if pr else None,
            "root_cause": analysis.root_cause if analysis else None,
            "files_changed": pr.files_changed if pr else [],
            "test_passed": test_result.passed if test_result else False,
            "error": final_state.get("error"),
        }

    except Exception as e:
        logger.exception("Workflow failed for issue #%d", request.issue_number)
        return {"error": str(e), "issue_number": request.issue_number}
    finally:
        if repository_path:
            shutil.rmtree(repository_path, ignore_errors=True)
