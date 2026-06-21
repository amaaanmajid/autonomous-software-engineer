"""
Tree-sitter based source code parser.

Walks a repository, parses Python/JS/TS files, and extracts functions
and classes as Symbol objects. Each Symbol contains the full source code
of the function/class — this source code is later embedded into FAISS.
"""
import logging
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

from app.models.symbol import Symbol, SymbolType

logger = logging.getLogger(__name__)

# Languages supported for parsing
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Files/dirs to skip during repo walk
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", "dist", "build", ".mypy_cache", ".pytest_cache",
}
SKIP_FILES = {"*.min.js", "*.lock"}


def _build_languages() -> dict[str, Language]:
    return {
        "python": Language(tspython.language()),
        "javascript": Language(tsjavascript.language()),
        "typescript": Language(tstypescript.language_typescript()),
    }


# Queries to extract functions and classes per language
_PY_QUERY = """
(function_definition name: (identifier) @name) @definition
(async_function_def name: (identifier) @name) @definition
(class_definition name: (identifier) @name) @definition
"""

_JS_QUERY = """
(function_declaration name: (identifier) @name) @definition
(class_declaration name: (identifier) @name) @definition
(arrow_function) @definition
(method_definition name: (property_identifier) @name) @definition
"""

_TS_QUERY = _JS_QUERY  # TypeScript grammar is a superset of JS for our purposes

_QUERIES: dict[str, str] = {
    "python": _PY_QUERY,
    "javascript": _JS_QUERY,
    "typescript": _TS_QUERY,
}


class TreeSitterParser:
    def __init__(self) -> None:
        self._languages = _build_languages()
        self._parsers: dict[str, Parser] = {}
        for lang_name, language in self._languages.items():
            p = Parser()
            p.set_language(language)
            self._parsers[lang_name] = p

    def parse_file(self, file_path: Path) -> list[Symbol]:
        """Parse one source file and return all extracted symbols."""
        ext = file_path.suffix.lower()
        lang = SUPPORTED_EXTENSIONS.get(ext)
        if lang is None:
            return []

        try:
            source = file_path.read_bytes()
        except (OSError, PermissionError) as e:
            logger.warning("Cannot read %s: %s", file_path, e)
            return []

        parser = self._parsers[lang]
        tree = parser.parse(source)
        source_str = source.decode("utf-8", errors="replace")

        return self._extract_symbols(tree, source_str, str(file_path), lang)

    def _extract_symbols(
        self,
        tree,
        source: str,
        file_path: str,
        lang: str,
    ) -> list[Symbol]:
        symbols: list[Symbol] = []
        lines = source.splitlines()

        language = self._languages[lang]
        query_str = _QUERIES[lang]

        try:
            query = language.query(query_str)
        except Exception as e:
            logger.warning("Query build failed for %s: %s", lang, e)
            return []

        captures = query.captures(tree.root_node)

        # captures returns list of (node, capture_name) tuples
        definitions = [
            node for node, name in captures if name == "definition"
        ]

        seen_ranges: set[tuple[int, int]] = set()
        for node in definitions:
            start_line = node.start_point[0] + 1  # 1-indexed
            end_line = node.end_point[0] + 1

            if (start_line, end_line) in seen_ranges:
                continue
            seen_ranges.add((start_line, end_line))

            name = self._get_node_name(node, captures)
            if not name:
                name = f"anonymous_{start_line}"

            symbol_code = "\n".join(lines[start_line - 1 : end_line])
            symbol_type = self._infer_type(node, lang)
            docstring = self._extract_docstring(symbol_code, lang)

            symbols.append(
                Symbol(
                    name=name,
                    symbol_type=symbol_type,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    source_code=symbol_code,
                    language=lang,
                    docstring=docstring,
                )
            )

        return symbols

    def _get_node_name(self, node, captures) -> str:
        """Find the @name capture that belongs to this @definition node."""
        for captured_node, capture_name in captures:
            if capture_name == "name" and node.start_byte <= captured_node.start_byte < node.end_byte:
                return captured_node.text.decode("utf-8", errors="replace")
        return ""

    def _infer_type(self, node, lang: str) -> SymbolType:
        ntype = node.type
        if "class" in ntype:
            return SymbolType.CLASS
        if "async" in ntype:
            return SymbolType.ASYNC_FUNCTION
        if "method" in ntype:
            return SymbolType.METHOD
        return SymbolType.FUNCTION

    def _extract_docstring(self, source_code: str, lang: str) -> str | None:
        if lang != "python":
            return None
        lines = source_code.strip().splitlines()
        # Look for triple-quoted string on first non-def line
        in_doc = False
        doc_lines: list[str] = []
        for line in lines[1:]:
            stripped = line.strip()
            if not in_doc and (stripped.startswith('"""') or stripped.startswith("'''")):
                in_doc = True
                doc_lines.append(stripped)
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    break
            elif in_doc:
                doc_lines.append(line)
                if '"""' in stripped or "'''" in stripped:
                    break
        return "\n".join(doc_lines) if doc_lines else None

    def scan_repository(self, repo_path: Path) -> list[Symbol]:
        """Recursively scan an entire repository and return all symbols."""
        all_symbols: list[Symbol] = []
        scanned_files = 0

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            if any(skip in file_path.parts for skip in SKIP_DIRS):
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            symbols = self.parse_file(file_path)
            all_symbols.extend(symbols)
            scanned_files += 1

        logger.info(
            "Scanned %d files, extracted %d symbols from %s",
            scanned_files,
            len(all_symbols),
            repo_path,
        )
        return all_symbols
