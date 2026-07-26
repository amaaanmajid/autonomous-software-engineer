# Autonomous Software Engineer

An AI agent that accepts a GitHub issue, finds the relevant code, generates a fix, runs tests, and opens a pull request — automatically.

---

## Architecture

```
POST /process-github-issue
        ↓
  Clone Repo + Index with Tree-sitter + FAISS
        ↓
  LangGraph Workflow
        ↓
  analyze_issue → retrieve_context → generate_fix
       ↑                                    ↓
       └──── retry (max 3) ── run_tests ← apply_patch
                                  ↓ (pass)
                            generate_pr → PR URL
```

**Stack:** Python 3.11 · FastAPI · LangGraph · Tree-sitter · FAISS · Groq (llama-3.3-70b) · GitPython · Docker · GitHub API

---

## How It Works

1. You send a GitHub repo URL + issue number
2. The agent clones the repo and parses every `.py`/`.js`/`.ts` file with Tree-sitter → extracts functions and classes as `Symbol` objects
3. Each symbol's source code is embedded into a 384-dim vector using `all-MiniLM-L6-v2` and stored in FAISS
4. The issue text is embedded and matched against FAISS → top 5 most relevant symbols retrieved
5. LLM (Groq) analyzes the issue, generates a patch, applies it to a new git branch, and runs tests in Docker
6. If tests pass → PR is opened automatically

---

## Quick Start

### Prerequisites

- Python 3.11
- Docker Desktop (for running tests)
- [Groq API key](https://console.groq.com) (free)
- GitHub Personal Access Token (repo + pull_request scopes)

### Setup

```bash
# Create virtualenv
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env — fill in GROQ_API_KEY, GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME
```

### Run the API

```bash
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

---

## Usage

Send a GitHub issue URL + issue number:

```bash
curl -X POST http://localhost:8000/process-github-issue \
  -H "Content-Type: application/json" \
  -d '{
    "github_url": "https://github.com/your-username/your-repo",
    "issue_number": 1
  }'
```

Response:

```json
{
  "issue_number": 1,
  "issue_title": "App crashes with no useful error when database goes down",
  "pr_url": "https://github.com/your-username/your-repo/pull/2",
  "pr_title": "fix: add error handling for database connection failures",
  "root_cause": "Uncaught database exception in get_db function",
  "files_changed": ["app/backend/database.py"],
  "test_passed": true,
  "cloned_to": "/tmp/ase_workspace/your-username_your-repo"
}
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /process-github-issue` | Full pipeline: clone → index → analyze → fix → test → PR |
| `POST /index-repository` | Parse a local repo with Tree-sitter, build FAISS index |
| `POST /process-issue` | Run pipeline on an already-indexed local repo |
| `POST /run-tests` | Run pytest in Docker (standalone) |
| `POST /generate-pr` | Create a GitHub PR from an existing patch (standalone) |
| `GET /health` | Health check |

---

## Project Structure

```
app/
├── agents/          # Indexing, retrieval, analysis, fix generation, patch applicator, PR generation
├── api/             # FastAPI routes + dependency injection
├── hooks/           # Pre/post validation hooks (code gen, tests, PR)
├── models/          # Pydantic schemas (issue, symbol, patch, PR, state)
├── parsers/         # Tree-sitter code parser (Python, JS, TS)
├── retrieval/       # Exact name match + semantic FAISS retrieval
├── vectorstore/     # FAISS store with sentence-transformers embeddings
├── github/          # GitHub API client, repo cloner, PR builder
├── docker_runner/   # Docker-based pytest runner
├── workflow/        # LangGraph StateGraph (full pipeline)
├── config.py        # Pydantic Settings (reads .env)
├── llm.py           # LLM factory (Groq → Ollama fallback)
└── main.py          # FastAPI entry point
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key — get free at console.groq.com |
| `GROQ_MODEL` | Model to use (default: `llama-3.3-70b-versatile`) |
| `GITHUB_TOKEN` | GitHub PAT for cloning and creating PRs |
| `GITHUB_REPO_OWNER` | Your GitHub username (fallback if not derived from issue URL) |
| `GITHUB_REPO_NAME` | Repo name (fallback if not derived from issue URL) |
| `DOCKER_TIMEOUT` | Seconds before Docker test run times out |
| `FAISS_INDEX_PATH` | Where to save/load FAISS index (default: `data/faiss_index`) |
| `SYMBOL_INDEX_PATH` | Where to save/load symbol index JSON (default: `data/symbol_index.json`) |

---

## Known Limitations

- LLM sometimes generates `original_code` that doesn't exactly match the file → patch is skipped silently
- Only top 5 symbols are retrieved — on large repos the right function may not be in the top 5
- File imports are not included in LLM context — LLM may add calls to unimported modules
- Tests run inside Docker require the repo to have a working `pytest` setup

---

## Future Roadmap

- Unified diff format for patches (eliminates `original_code` hallucination)
- Include file import headers in LLM context
- Call graph traversal — retrieve callers/callees of matched functions
- Human approval node before PR is raised
- Web UI with diff preview
- Support for Go, Rust, Java
- Multi-agent parallel fix generation
