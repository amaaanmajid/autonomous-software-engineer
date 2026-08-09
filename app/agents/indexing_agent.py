"""
Repository Indexing Agent

Responsibilities:
- Scan the repository recursively
- Parse files using Tree-sitter
- Extract symbols (functions, classes)
- Build symbol index (JSON)
- Generate embeddings and store in FAISS
"""
import ast
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.models.symbol import Symbol, SymbolIndex
from app.parsers.tree_sitter_parser import TreeSitterParser
from app.vectorstore.faiss_store import FAISSStore

logger = logging.getLogger(__name__)


class RepositoryIndexingAgent:
    def __init__(
        self,
        parser: TreeSitterParser | None = None,
        faiss_store: FAISSStore | None = None,
    ) -> None:
        self._parser = parser or TreeSitterParser()
        self._faiss_store = faiss_store or FAISSStore(model_name=settings.embedding_model)

    def index_repository(self, repository_path: str) -> SymbolIndex:
        """
        Full indexing pipeline:
        1. Scan repo with Tree-sitter
        2. Build symbol list
        3. Embed all source codes into FAISS
        4. Save both indexes to disk
        """
        repo_path = Path(repository_path)
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        logger.info("Starting indexing for: %s", repository_path)

        # Step 1: Parse all files
        symbols: list[Symbol] = self._parser.scan_repository(repo_path)

        if not symbols:
            logger.warning("No symbols found in %s", repository_path)

        # Step 2: Embed and store in FAISS
        # Symbols are added in order — FAISS slot i == symbols[i]
        self._faiss_store.add_symbols(symbols)

        # Step 3: Build symbol index
        symbol_index = SymbolIndex(
            symbols=symbols,
            repository_path=str(repo_path.resolve()),
            indexed_at=datetime.now(UTC).isoformat(),
            total_files=len({s.file_path for s in symbols}),
            total_symbols=len(symbols),
        )

        # Step 4: Build call graph
        call_graph = self._build_call_graph(repo_path)
        self._save_call_graph(call_graph)

        # Step 5: Persist to disk
        self._save_symbol_index(symbol_index)
        self._faiss_store.save(settings.faiss_index_path)

        logger.info(
            "Indexing complete: %d files, %d symbols",
            symbol_index.total_files,
            symbol_index.total_symbols,
        )
        return symbol_index

    @staticmethod
    def _build_call_graph(repo_path: Path) -> dict:
        """
        Build callers_of and callees_of dicts using stdlib ast.
        callers_of["get_db"] = [{"caller": "analyze_issue", "file": "...", "line": 42}]
        callees_of["get_db"] = [{"callee": "SessionLocal", "file": "...", "line": 18}]
        """
        callers_of: dict[str, list[dict]] = defaultdict(list)
        callees_of: dict[str, list[dict]] = defaultdict(list)

        for py_file in repo_path.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue

            rel_path = str(py_file.relative_to(repo_path))

            for func_node in ast.walk(tree):
                if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                caller_name = func_node.name

                for node in ast.walk(func_node):
                    if not isinstance(node, ast.Call):
                        continue
                    if isinstance(node.func, ast.Name):
                        callee = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        callee = node.func.attr
                    else:
                        continue

                    callers_of[callee].append({
                        "caller": caller_name,
                        "file": rel_path,
                        "line": node.lineno,
                    })
                    callees_of[caller_name].append({
                        "callee": callee,
                        "file": rel_path,
                        "line": node.lineno,
                    })

        logger.info(
            "Call graph built: %d callee entries, %d caller entries",
            len(callees_of), len(callers_of),
        )
        return {"callers_of": dict(callers_of), "callees_of": dict(callees_of)}

    @staticmethod
    def _save_call_graph(call_graph: dict) -> None:
        path = Path(settings.call_graph_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(call_graph, indent=2))
        logger.info("Call graph saved to %s", path)

    @staticmethod
    def load_call_graph() -> dict:
        path = Path(settings.call_graph_path)
        if not path.exists():
            return {"callers_of": {}, "callees_of": {}}
        return json.loads(path.read_text())

    def _save_symbol_index(self, index: SymbolIndex) -> None:
        path = Path(settings.symbol_index_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(index.model_dump_json(indent=2))
        logger.info("Symbol index saved to %s", path)

    @staticmethod
    def load_symbol_index() -> SymbolIndex:
        path = Path(settings.symbol_index_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Symbol index not found at {path}. Run POST /index-repository first."
            )
        data = json.loads(path.read_text())
        return SymbolIndex(**data)
