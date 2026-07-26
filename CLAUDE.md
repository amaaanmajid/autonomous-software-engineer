# Autonomous Software Engineer — CLAUDE.md

This file gives future Claude Code sessions full context to continue development without re-explaining the project.

---

## Project Overview

An MVP autonomous agent that:
1. Accepts a GitHub issue (title + description)
2. Indexes a local repository using Tree-sitter + FAISS
3. Retrieves relevant functions via hybrid search (exact + semantic)
4. Generates a code fix using an LLM (Gemini Flash / Ollama)
5. Applies the patch to a new git branch
6. Runs the repo's tests inside Docker
7. Opens a GitHub pull request if tests pass

---

## System Architecture

```
FastAPI (app/main.py)
  ├── POST /index-repository   → RepositoryIndexingAgent
  ├── POST /process-issue      → LangGraph workflow (full pipeline)
  ├── POST /run-tests          → DockerTestRunner (standalone)
  └── POST /generate-pr        → PRGenerationAgent (standalone)

LangGraph StateGraph (app/workflow/graph.py)
  analyze_issue → retrieve_context → generate_fix → apply_patch
       ↑                                                  ↓
       └──── retry (max 3) ──── run_tests ───────────────┘
                                     ↓ (pass)
                               generate_pr → END
```

---

## Directory Structure

```
app/
├── agents/
│   ├── indexing_agent.py       # Scans repo, builds symbol index + FAISS
│   ├── retrieval_agent.py      # Hybrid retrieval (exact + semantic)
│   ├── issue_analysis_agent.py # LLM: understand issue, find root cause
│   ├── code_fix_agent.py       # LLM: generate FilePatch objects
│   ├── patch_applicator.py     # Apply patches to disk, create git branch
│   └── pr_generation_agent.py  # LLM: write PR, call GitHub API
├── api/
│   ├── dependencies.py         # FastAPI dependency injection
│   └── routes/
│       ├── indexing.py, issues.py, testing.py, pr.py
├── hooks/                      # Pre/post validation hooks
│   ├── pre_code_generation.py  # Validate context exists
│   ├── post_code_generation.py # Lint + syntax check patches
│   ├── pre_test.py             # Verify Docker is running
│   ├── post_test.py            # Block PR if tests fail
│   └── pre_pr.py               # Verify patch applied + tests passed
├── models/                     # All Pydantic schemas
│   ├── state.py                # AgentState TypedDict (LangGraph shared state)
│   ├── issue.py, symbol.py, retrieval.py, patch.py, pr.py, test_result.py
├── parsers/
│   └── tree_sitter_parser.py   # Parse Python/JS/TS → Symbol list
├── retrieval/
│   ├── exact_matcher.py        # Name-based symbol lookup
│   └── semantic_retriever.py   # FAISS vector search
├── vectorstore/
│   └── faiss_store.py          # Embed + store + search symbols
├── github/
│   ├── client.py               # PyGithub wrapper
│   └── pr_builder.py           # Create GitHub PRs
├── docker_runner/
│   └── runner.py               # Run pytest inside Docker container
├── workflow/
│   └── graph.py                # LangGraph StateGraph definition
├── config.py                   # Pydantic Settings (reads .env)
├── llm.py                      # LLM factory (Gemini Flash → Ollama fallback)
└── main.py                     # FastAPI app + router registration
```

---

## Agent Workflow (LangGraph)

Each node reads from `AgentState` and returns an updated copy:

| Node | Input | Output |
|------|-------|--------|
| `analyze_issue` | issue | analysis |
| `retrieve_context` | issue | retrieval |
| `generate_fix` | issue + analysis + retrieval | patch_set |
| `apply_patch` | patch_set | patch_set (applied=True, branch_name set) |
| `run_tests` | repository_path | test_result |
| `generate_pr` | all of the above | pr_draft (pr_url populated) |

Retry logic: if `run_tests` fails, `retry_count` increments and the graph loops back to `analyze_issue`. After 3 retries it routes to `END` with an error.

---

## Key Data Models

- `Symbol` — one extracted function/class: name, file_path, start_line, end_line, source_code
- `SymbolIndex` — all symbols list (ORDER MATTERS — position == FAISS slot)
- `RetrievedContext` — a Symbol with a similarity score and match_type (exact|semantic)
- `FilePatch` — one code change: file_path, operation, original_code, new_code, description
- `PatchSet` — collection of FilePatch objects with applied status and branch_name
- `AgentState` — LangGraph shared state TypedDict holding all of the above

---

## FAISS ↔ Symbol Index Mapping

**Critical invariant:** `all_symbols[i]` always corresponds to FAISS slot `i`.

Both are built together in `RepositoryIndexingAgent.index_repository()`:
- Symbols appended to list → FAISS vector added at same position
- Saved to `data/symbol_index.json` and `data/faiss_index.faiss` + `.symbols.pkl`
- Never add to one without the other

---

## Retrieval Strategy

1. **Exact matching** (`ExactMatcher`): tokenize issue text (split camelCase + snake_case), look up in symbol name dict. Fast, zero cost. Score 1.0 for full name match, 0.7 for sub-token.
2. **Semantic search** (`SemanticRetriever` + `FAISSStore`): embed issue text with `all-MiniLM-L6-v2` (384-dim), search FAISS with `IndexFlatIP` (cosine similarity after L2 norm).
3. **Merge**: exact results first, semantic fills remaining slots, deduplicated by symbol name, capped at `RETRIEVAL_TOP_K`.

---

## LLM Configuration

- Primary: Grok (xAI) via OpenAI-compatible API — set `XAI_API_KEY` (get at console.x.ai)
- Model: `grok-3-mini` by default, configurable via `XAI_MODEL`
- Fallback: Ollama (local) — set `OLLAMA_BASE_URL` + `OLLAMA_MODEL`
- All LLM calls use `tenacity` retry with exponential backoff (handles 429 rate limits)
- Prompts always request structured JSON — responses are parsed into Pydantic models

---

## Coding Standards

- Python 3.11, Pydantic v2, async FastAPI
- All agent inputs/outputs are Pydantic models — no raw dicts between agents
- Logging: `logger = logging.getLogger(__name__)` in every module
- No global mutable state — dependency injection via FastAPI `Depends()`
- Hooks raise `HookValidationError` to block the workflow; caught in graph nodes

---

## Environment Variables (.env)

| Key | Purpose |
|-----|---------|
| `XAI_API_KEY` | Grok LLM (get at console.x.ai) |
| `GITHUB_TOKEN` | GitHub PAT for creating PRs |
| `GITHUB_REPO_OWNER` | Your GitHub username |
| `GITHUB_REPO_NAME` | Target repo name |
| `FAISS_INDEX_PATH` | Where to save/load FAISS index |
| `SYMBOL_INDEX_PATH` | Where to save/load symbol index JSON |
| `DOCKER_TIMEOUT` | Seconds before Docker test run times out |

---

## Future Roadmap

- [ ] Call graph traversal (Neo4j AST relationships)
- [ ] Multi-repository analysis
- [ ] Human approval node in LangGraph
- [ ] MCP integrations
- [ ] Multi-agent collaboration (parallel fixers)
- [ ] Autonomous PR review agent
- [ ] Support Go, Rust, Java in Tree-sitter parser
- [ ] Streaming API responses (SSE)
- [ ] Web UI dashboard
