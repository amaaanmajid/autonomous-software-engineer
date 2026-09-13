"""
Patch Applicator

Applies FilePatch objects to the target repository:
1. Creates a new git branch from main
2. Applies each patch to the file on disk
3. Commits the changes
"""
import logging
from datetime import UTC, datetime
from pathlib import Path

import git

from app.config import settings
from app.models.patch import FilePatch, PatchOperation, PatchSet

logger = logging.getLogger(__name__)


class PatchApplicator:
    def __init__(self, github_token: str = "") -> None:
        self._github_token = github_token or settings.github_token

    def apply(self, patch_set: PatchSet, repository_path: str) -> PatchSet:
        """
        Apply all patches to the repository on a new branch.
        Returns updated PatchSet with applied=True and branch_name set.
        """
        repo_path = Path(repository_path)
        repo = git.Repo(repo_path)

        self._ensure_identity(repo)

        # Remember where we started so the abort path can get back — the default
        # branch is not always "main".
        base_branch = repo.active_branch.name

        # Create fix branch from current HEAD (usually main)
        branch_name = self._create_branch(repo, patch_set)

        # Apply each patch, track how many were skipped
        skipped = 0
        for patch in patch_set.patches:
            applied = self._apply_single_patch(patch, repo_path)
            if not applied:
                skipped += 1

        # Guard: if nothing actually changed on disk, abort — don't raise an empty PR
        if not repo.is_dirty():
            logger.error(
                "No patches were applied (%d/%d skipped) — aborting commit to avoid empty PR",
                skipped, len(patch_set.patches),
            )
            repo.git.checkout(base_branch)
            repo.git.branch("-D", branch_name)
            raise ValueError(
                f"All {len(patch_set.patches)} patch(es) were skipped — "
                "LLM original_code did not match file content. Retry with a cleaner prompt."
            )

        # Commit all changes
        repo.git.add(A=True)
        repo.git.commit(
            "-m",
            f"fix: {patch_set.description}\n\nApplied {len(patch_set.patches) - skipped}/{len(patch_set.patches)} patch(es) across {patch_set.total_files} file(s).",
        )

        # Push branch to origin so GitHub can create a PR from it
        self._push_branch(repo, branch_name)
        logger.info("Patches applied and committed on branch: %s", branch_name)

        return PatchSet(
            patches=patch_set.patches,
            total_files=patch_set.total_files,
            description=patch_set.description,
            applied=True,
            applied_at=datetime.now(UTC).isoformat(),
            branch_name=branch_name,
            patches_skipped=skipped,
        )

    def _ensure_identity(self, repo: git.Repo) -> None:
        """Give git an author for this clone.

        Containers have no global git config, so `git commit` aborts with
        "unable to auto-detect email address". Written at repository level —
        the clone is a throwaway, and this never touches the host's config.
        """
        with repo.config_writer() as cw:
            cw.set_value("user", "name", settings.git_author_name)
            cw.set_value("user", "email", settings.git_author_email)

    def _push_branch(self, repo: git.Repo, branch_name: str) -> None:
        if not self._github_token:
            logger.warning("No GITHUB_TOKEN — skipping push (PR creation will fail)")
            return
        origin_url = repo.remotes.origin.url
        if "github.com" in origin_url and "@" not in origin_url:
            authed_url = origin_url.replace(
                "https://", f"https://{self._github_token}@"
            )
            repo.remotes.origin.set_url(authed_url)
        repo.git.push("origin", branch_name)
        logger.info("Pushed branch %s to origin", branch_name)

    def _create_branch(self, repo: git.Repo, patch_set: PatchSet) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        branch_name = f"fix/auto-{timestamp}"

        repo.git.checkout("-b", branch_name)
        logger.info("Created branch: %s", branch_name)
        return branch_name

    def _apply_single_patch(self, patch: FilePatch, repo_path: Path) -> bool:
        """Apply a single patch. Returns True if applied, False if skipped."""
        file_path = repo_path / patch.file_path
        if not file_path.exists():
            raise FileNotFoundError(f"File not found for patching: {file_path}")

        content = file_path.read_text(encoding="utf-8")

        if patch.operation == PatchOperation.REPLACE:
            if patch.original_code and patch.original_code not in content:
                logger.warning(
                    "Skipping REPLACE in %s — original_code not found (LLM hallucination)",
                    patch.file_path,
                )
                return False
            new_content = content.replace(patch.original_code, patch.new_code, 1)

        elif patch.operation == PatchOperation.INSERT:
            lines = content.splitlines(keepends=True)
            insert_at = min(patch.start_line, len(lines))
            lines.insert(insert_at, patch.new_code + "\n")
            new_content = "".join(lines)

        elif patch.operation == PatchOperation.DELETE:
            if patch.original_code:
                new_content = content.replace(patch.original_code, "", 1)
            else:
                lines = content.splitlines(keepends=True)
                del lines[patch.start_line - 1 : patch.end_line]
                new_content = "".join(lines)
        else:
            raise ValueError(f"Unknown patch operation: {patch.operation}")

        file_path.write_text(new_content, encoding="utf-8")
        logger.info("Patched: %s (%s)", patch.file_path, patch.operation)
        return True
