from typing import Optional
from typing_extensions import TypedDict

from app.models.issue import IssueInput, IssueAnalysis
from app.models.retrieval import RetrievalResult
from app.models.patch import PatchSet
from app.models.test_result import TestResult
from app.models.pr import PRDraft


class AgentState(TypedDict):
    """Shared state passed between every node in the LangGraph workflow."""
    issue: IssueInput
    analysis: Optional[IssueAnalysis]
    retrieval: Optional[RetrievalResult]
    patch_set: Optional[PatchSet]
    test_result: Optional[TestResult]
    pr_draft: Optional[PRDraft]
    error: Optional[str]
    retry_count: int
