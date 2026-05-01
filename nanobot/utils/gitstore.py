"""Git-backed version control for memory files, using dulwich."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


@dataclass
class CommitInfo:
    sha: str  # Short SHA (8 chars)
    message: str
    timestamp: str  # Formatted datetime

    def format(self, diff: str = "") -> str:
        """Format this commit for display, optionally with a diff."""
        header = f"## {self.message.splitlines()[0]}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"


@dataclass
class LineAge:
    """Age of a single line based on git blame."""

    age_days: int  # days since last modification


def _compute_line_ages(annotated) -> list[LineAge]:
    """Convert annotate results to per-line ages."""
    now = datetime.now(tz=timezone.utc).date()
    ages: list[LineAge] = []
    for (commit, _tree_entry), _line_bytes in annotated:
        dt = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc).date()
        ages.append(LineAge(age_days=(now - dt).days))
    return ages


class GitStore:
    """Git-backed version control for memory files."""

    def __init__(self, workspace: Path, tracked_files: list[str]):
        self._workspace = workspace
        self._tracked_files = tracked_files

    def is_initialized(self) -> bool:
        """Check if the git repo has been initialized."""
        return (self._workspace / ".git").is_dir()

    # -- init ------------------------------------------------------------------

    def init(self) -> bool:
        """Initialize a git repo if not already initialized.

        Creates .gitignore and makes an initial commit.
        Returns True if a new repo was created, False if already exists.
        """
        if self.is_initialized():
            return False

        if self._is_inside_git_repo():
            logger.warning(
                "Workspace {} is already inside a git repo; "
                "skipping nested repo initialization",
                self._workspace,
            )
            return False

        try:
            from dulwich import porcelain

            porcelain.init(str(self._workspace))

            # Write .gitignore (merge with existing if present)
            gitignore = self._workspace / ".gitignore"
            dream_entries = self._build_gitignore()
            if gitignore.exists():
                existing = gitignore.read_text(encoding="utf-8")
                existing_lines = set(existing.splitlines())
                new_lines = [
                    line
                    for line in dream_entries.splitlines()
                    if line not in existing_lines
                ]
                if new_lines:
                    merged = existing.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
                    gitignore.write_text(merged, encoding="utf-8")
            else:
                gitignore.write_text(dream_entries, encoding="utf-8")

            # Ensure tracked files exist (touch them if missing) so the initial
            # commit has something to track. Directories are created with a
            # .gitkeep placeholder so git tracks empty directories.
            for rel in self._tracked_files:
                p = self._workspace / rel
                if p.is_dir():
                    # Directory already exists; ensure it has a .gitkeep for git
                    gitkeep = p / ".gitkeep"
                    if not gitkeep.exists():
                        gitkeep.write_text("", encoding="utf-8")
                elif not p.exists():
                    # Heuristic: paths with file extensions (e.g. "MEMORY.md") are files,
                    # dotfiles (e.g. ".nanobot") and paths without extensions are directories.
                    basename = rel.split("/")[-1].split("\\")[-1]
                    # Check if it has a file extension (not just a leading dot)
                    has_extension = "." in basename[1:] if basename.startswith(".") else "." in basename
                    if has_extension:
                        p.write_text("", encoding="utf-8")
                    else:
                        p.mkdir(parents=True, exist_ok=True)
                        (p / ".gitkeep").write_text("", encoding="utf-8")

            # Initial commit
            porcelain.add(str(self._workspace), paths=[".gitignore"] + self._tracked_files)
            porcelain.commit(
                str(self._workspace),
                message=b"init: nanobot memory store",
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            logger.info("Git store initialized at {}", self._workspace)
            return True
        except Exception:
            logger.warning("Git store init failed for {}", self._workspace)
            return False

    # -- daily operations ------------------------------------------------------

    def auto_commit(self, message: str) -> str | None:
        """Stage tracked memory files and commit if there are changes.

        Uses the existing git repo at <workspace>/.git — never creates a new one.
        Only stages files listed in tracked_files (e.g. .nanobot/**).

        Returns the short commit SHA, or None if nothing to commit.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich import porcelain

            # Stage only our tracked files first
            porcelain.add(str(self._workspace), paths=self._tracked_files)

            # Check if any of our files have staged changes
            st = porcelain.status(str(self._workspace))
            if not any(st.staged.values()):
                return None

            msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=msg_bytes,
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            if sha_bytes is None:
                return None
            sha = sha_bytes.hex()[:8]
            logger.debug("Git auto-commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.warning("Git auto-commit failed: {}", message)
            return None

    # -- internal helpers ------------------------------------------------------

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """Resolve a short SHA prefix to the full SHA bytes."""
        try:
            from dulwich.repo import Repo

            with Repo(str(self._workspace)) as repo:
                try:
                    sha = repo.refs[b"HEAD"]
                except KeyError:
                    return None

                while sha:
                    if sha.hex().startswith(short_sha):
                        return sha
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    sha = commit.parents[0] if commit.parents else None
            return None
        except Exception:
            return None

    def _is_inside_git_repo(self) -> bool:
        """Check if self._workspace is already inside a git repository.

        Walks up from self._workspace to the filesystem root, returning True
        if any parent directory contains a .git entry.

        Git worktrees and submodules can use a ``.git`` file instead of a
        directory, so we must treat either form as "already inside a repo".
        """
        current = self._workspace.resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return True
            current = current.parent
        return False

    def _build_gitignore(self) -> str:
        """Generate .gitignore content from tracked files."""
        dirs: set[str] = set()
        for f in self._tracked_files:
            parent = str(Path(f).parent)
            if parent != ".":
                dirs.add(parent)
        lines = ["/*"]
        for d in sorted(dirs):
            lines.append(f"!{d}/")
        for f in self._tracked_files:
            lines.append(f"!{f}")
        lines.append("!.gitignore")
        return "\n".join(lines) + "\n"

    # -- query -----------------------------------------------------------------

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        """Return simplified commit log."""
        if not self.is_initialized():
            return []

        try:
            from dulwich.repo import Repo

            entries: list[CommitInfo] = []
            with Repo(str(self._workspace)) as repo:
                try:
                    head = repo.refs[b"HEAD"]
                except KeyError:
                    return []

                sha = head
                while sha and len(entries) < max_entries:
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    ts = time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(commit.commit_time),
                    )
                    msg = commit.message.decode("utf-8", errors="replace").strip()
                    entries.append(CommitInfo(
                        sha=sha.hex()[:8],
                        message=msg,
                        timestamp=ts,
                    ))
                    sha = commit.parents[0] if commit.parents else None

            return entries
        except Exception:
            logger.warning("Git log failed")
            return []

    def line_ages(self, file_path: str) -> list[LineAge]:
        """Compute the age of each line in a tracked file via git blame.

        Returns one LineAge per line, in order.
        Returns an empty list if the repo is not initialized, the file is
        empty, or annotation fails.
        """

        if not self.is_initialized():
            return []

        target = self._workspace / file_path
        if not target.exists() or target.stat().st_size == 0:
            return []

        try:
            from dulwich import porcelain

            annotated = porcelain.annotate(str(self._workspace), file_path)
        except Exception:
            logger.warning("Git line_ages annotate failed for {}", file_path)
            return []

        if not annotated:
            return []

        return _compute_line_ages(annotated)

    def diff_commits(self, sha1: str, sha2: str) -> str:
        """Show diff between two commits."""
        if not self.is_initialized():
            return ""

        try:
            from dulwich import porcelain

            full1 = self._resolve_sha(sha1)
            full2 = self._resolve_sha(sha2)
            if not full1 or not full2:
                return ""

            out = io.BytesIO()
            porcelain.diff(
                str(self._workspace),
                commit=full1,
                commit2=full2,
                outstream=out,
            )
            return out.getvalue().decode("utf-8", errors="replace")
        except Exception:
            logger.warning("Git diff_commits failed")
            return ""

    def find_commit(self, short_sha: str, max_entries: int = 20) -> CommitInfo | None:
        """Find a commit by short SHA prefix match."""
        for c in self.log(max_entries=max_entries):
            if c.sha.startswith(short_sha):
                return c
        return None

    def show_commit_diff(self, short_sha: str, max_entries: int = 20) -> tuple[CommitInfo, str] | None:
        """Find a commit and return it with its diff vs the parent."""
        commits = self.log(max_entries=max_entries)
        for i, c in enumerate(commits):
            if c.sha.startswith(short_sha):
                if i + 1 < len(commits):
                    diff = self.diff_commits(commits[i + 1].sha, c.sha)
                else:
                    diff = ""
                return c, diff
        return None

    # -- restore ---------------------------------------------------------------

    def revert(self, commit: str) -> str | None:
        """Revert (undo) the changes introduced by the given commit.

        Restores all tracked memory files to the state at the commit's parent,
        then creates a new commit recording the revert.

        Returns the new commit SHA, or None on failure.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich.repo import Repo

            full_sha = self._resolve_sha(commit)
            if not full_sha:
                logger.warning("Git revert: SHA not found: {}", commit)
                return None

            with Repo(str(self._workspace)) as repo:
                commit_obj = repo[full_sha]
                if commit_obj.type_name != b"commit":
                    return None

                if not commit_obj.parents:
                    logger.warning("Git revert: cannot revert root commit {}", commit)
                    return None

                # Use the parent's tree — this undoes the commit's changes
                parent_obj = repo[commit_obj.parents[0]]
                tree = repo[parent_obj.tree]

                # Collect all files that should exist after revert
                expected_files: set[str] = set()
                for filepath in self._tracked_files:
                    self._collect_tree_files(repo, tree, filepath, expected_files)

                # Remove files not in parent's tree, restore files from parent
                restored: list[str] = []
                for filepath in self._tracked_files:
                    restored.extend(
                        self._restore_from_tree(repo, tree, filepath, restored)
                    )

                # Remove files that shouldn't exist
                for root, dirs, files in self._workspace.walk():
                    for fname in files:
                        full_path = Path(root) / fname
                        rel_path = str(full_path.relative_to(self._workspace))
                        if rel_path not in expected_files and self._is_tracked(rel_path):
                            full_path.unlink()
                            restored.append(f"removed:{rel_path}")

            if not restored:
                return None

            # Commit the restored state
            msg = f"revert: undo {commit}"
            return self.auto_commit(msg)
        except Exception:
            logger.warning("Git revert failed for {}", commit)
            return None

    @staticmethod
    def _read_blob_from_tree(repo, tree, filepath: str) -> str | None:
        """Read a blob's content from a tree object by walking path parts."""
        parts = Path(filepath).parts
        current = tree
        for part in parts:
            try:
                entry = current[part.encode()]
            except KeyError:
                return None
            obj = repo[entry[1]]
            if obj.type_name == b"blob":
                return obj.data.decode("utf-8", errors="replace")
            if obj.type_name == b"tree":
                current = obj
            else:
                return None
        return None

    def _collect_tree_files(self, repo, tree, filepath: str, result: set[str]) -> None:
        """Collect all file paths under a tree entry."""
        parts = Path(filepath).parts
        current = tree
        rel_parts = []

        for part in parts:
            try:
                entry = current[part.encode()]
            except KeyError:
                return
            obj = repo[entry[1]]
            rel_parts.append(part)
            if obj.type_name == b"blob":
                result.add(str(Path(*rel_parts)))
            elif obj.type_name == b"tree":
                current = obj

        # If we reached a tree (directory), collect all files
        if rel_parts and current is not tree:
            for tree_entry in current.items():
                obj = repo[tree_entry.sha]
                if obj.type_name == b"blob":
                    name = tree_entry.path.decode()
                    result.add(str(Path(*rel_parts, name)))

    def _is_tracked(self, rel_path: str) -> bool:
        """Check if a relative path is under a tracked directory."""
        for tracked in self._tracked_files:
            if rel_path.startswith(tracked):
                return True
        return False

    def _restore_from_tree(self, repo, tree, filepath: str, restored: list[str]) -> list[str]:
        """Restore files from a tree entry, handling both blobs and directories.

        Returns a list of restored file paths.
        """
        parts = Path(filepath).parts
        current = tree
        rel_parts = []

        for part in parts:
            try:
                entry = current[part.encode()]
            except KeyError:
                return restored
            obj = repo[entry[1]]
            rel_parts.append(part)
            if obj.type_name == b"blob":
                # Restore this file
                rel_path = str(Path(*rel_parts))
                dest = self._workspace / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(obj.data.decode("utf-8", errors="replace"), encoding="utf-8")
                restored.append(rel_path)
            elif obj.type_name == b"tree":
                current = obj

        # If we reached a tree (directory), walk all entries and restore them
        if rel_parts and current is not tree:
            for tree_entry in current.items():
                obj = repo[tree_entry.sha]
                if obj.type_name == b"blob":
                    name = tree_entry.path.decode()
                    rel_path = str(Path(*rel_parts, name))
                    dest = self._workspace / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(obj.data.decode("utf-8", errors="replace"), encoding="utf-8")
                    restored.append(rel_path)

        return restored
