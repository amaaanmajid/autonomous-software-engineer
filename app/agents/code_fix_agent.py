"""
Code Fix Agent

Responsibilities:
- Analyze retrieved code in context of the issue
- Generate concrete code fixes
- Return structured PatchSet with FilePatch objects
"""
import ast
import json
import logging
import re
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.issue import IssueAnalysis, IssueInput
from app.models.patch import FilePatch, PatchSet
from app.models.retrieval import RetrievalResult
from app.utils.retry import llm_retry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert software engineer generating code fixes.
Given a GitHub issue, its analysis, and relevant source code, generate precise code changes.

Rules:
- Only modify code directly related to the bug
- Keep changes minimal and focused
- CRITICAL: The original_code field must be copied CHARACTER-FOR-CHARACTER from the source code shown above. Do not paraphrase, reformat, or change whitespace. If it does not appear verbatim in the file it will be skipped.
- CRITICAL: Check the ## Imports section for each file before writing new_code. If you use a module not listed there (e.g. logging, os, sys), add an import patch first.
- The new_code must be valid, complete replacement code

Respond ONLY with a JSON array of patch objects:
[
  {
    "file_path": "relative/path/to/file.py",
    "operation": "replace",
    "original_code": "exact verbatim code to replace",
    "new_code": "the fixed replacement code",
    "start_line": 12,
    "end_line": 15,
    "description": "short description of what this change fixes"
  }
]

operation must be one of: "replace", "insert", "delete"
For "insert": set original_code to null, start_line is where to insert after.
For "delete": set new_code to "", original_code is the exact block to remove.
To add a missing import, use "insert" with start_line: 1."""


class CodeFixAgent:
    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    @llm_retry
    def generate_fix(
        self,
        issue: IssueInput,
        analysis: IssueAnalysis,
        context: RetrievalResult,
    ) -> PatchSet:
        """Generate code patches for the issue based on analysis and retrieved code."""
        from app.agents.indexing_agent import RepositoryIndexingAgent
        call_graph = RepositoryIndexingAgent.load_call_graph()
        context_block = self._format_context(context, issue.repository_path, call_graph)
        stack_trace = self._extract_stack_trace(issue.description)
        stack_section = f"\n## Error / Stack Trace\n{stack_trace}" if stack_trace else ""

        user_prompt = f"""## Issue
Title: {issue.title}
Description: {issue.description}{stack_section}

## Root Cause Analysis
{analysis.root_cause}

## Suggested Approach
{analysis.suggested_approach}

## Relevant Source Code
{context_block}

Generate the minimal code changes to fix this bug. Respond with JSON array only."""

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        logger.info("Generating code fix for: %s", issue.title)
        response = self._llm.invoke(messages)
        raw = response.content.strip()

        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]

        try:
            patches_data = json.loads(raw)
            if not isinstance(patches_data, list):
                patches_data = [patches_data]

            patches = [FilePatch(**p) for p in patches_data]
            unique_files = len({p.file_path for p in patches})

            patch_set = PatchSet(
                patches=patches,
                total_files=unique_files,
                description=f"Fix for: {issue.title}",
            )
            logger.info("Generated %d patches across %d files", len(patches), unique_files)
            return patch_set

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("Failed to parse LLM patch response: %s\nRaw: %s", e, raw)
            raise ValueError(f"LLM returned invalid patch JSON: {e}") from e

    @staticmethod
    def _format_context(
        context: RetrievalResult,
        repository_path: str,
        call_graph: dict | None = None,
    ) -> str:
        if not context.results:
            return "No relevant code found."

        repo_path = Path(repository_path)
        call_graph = call_graph or {}
        callers_of = call_graph.get("callers_of", {})
        callees_of = call_graph.get("callees_of", {})
        parts = []
        seen_files: set[str] = set()

        for ctx in context.results:
            s = ctx.symbol
            file_path = repo_path / s.file_path
            block = f"File: {s.file_path} (lines {s.start_line}-{s.end_line})\n"

            # Include imports once per file
            if s.file_path not in seen_files and file_path.exists():
                imports = CodeFixAgent._get_file_imports(file_path)
                if imports:
                    block += f"## Imports in {s.file_path}:\n{imports}\n\n"
                seen_files.add(s.file_path)

            block += f"## Function/Class:\n```{s.language}\n{s.source_code}\n```"

            # 1-hop call graph context
            callers = callers_of.get(s.name, [])[:5]
            callees = callees_of.get(s.name, [])[:5]

            if callers:
                caller_lines = [f"  - {c['caller']}() in {c['file']}:{c['line']}" for c in callers]
                block += f"\n## Functions that call {s.name}():\n" + "\n".join(caller_lines)

            if callees:
                callee_names = list(dict.fromkeys(c["callee"] for c in callees))
                block += f"\n## {s.name}() calls: {', '.join(callee_names)}"

            parts.append(block)

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _get_file_imports(file_path: Path) -> str:
        """Extract all import lines from a Python file."""
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            lines = source.splitlines()
            import_lines = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for lineno in range(node.lineno, node.end_lineno + 1):
                        import_lines.append(lines[lineno - 1])
            return "\n".join(dict.fromkeys(import_lines))  # deduplicate, preserve order
        except Exception:
            return ""

    @staticmethod
    def _extract_stack_trace(description: str) -> str:
        """Extract Python traceback from issue description if present."""
        match = re.search(
            r"(Traceback \(most recent call last\):.*?)(?:\n\n|\Z)",
            description,
            re.DOTALL,
        )
        return match.group(1).strip() if match else ""
