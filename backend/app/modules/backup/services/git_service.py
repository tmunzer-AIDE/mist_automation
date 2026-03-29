"""
Git service for backing up configurations to Git repositories.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError

from app.config import settings
from app.core.exceptions import ConfigurationError, GitError
from app.modules.backup.models import BackupObject

logger = structlog.get_logger(__name__)


class GitService:
    """Service for Git repository management and commits.

    Use the async factory method ``await GitService.create(...)`` instead of
    the constructor so that the blocking repository initialisation runs in a
    thread and never blocks the event loop.
    """

    def __init__(
        self,
        repo_path: str = "/backups/git",
        repo_url: str | None = None,
        branch: str = "main",
        author_name: str | None = None,
        author_email: str | None = None,
    ):
        self.repo_path = Path(repo_path)
        self.repo_url = repo_url or settings.backup_git_repo_url
        self.branch = branch or settings.backup_git_branch
        self.author_name = author_name or settings.backup_git_author_name
        self.author_email = author_email or settings.backup_git_author_email

        if not self.repo_url:
            raise ConfigurationError("Git repository URL not configured")

        self._validate_git_url(self.repo_url)
        self.repo: Repo | None = None  # set by create()

    @classmethod
    async def create(
        cls,
        repo_path: str = "/backups/git",
        repo_url: str | None = None,
        branch: str = "main",
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> "GitService":
        """Async factory — initialises the Git repo in a worker thread."""
        svc = cls(
            repo_path=repo_path,
            repo_url=repo_url,
            branch=branch,
            author_name=author_name,
            author_email=author_email,
        )
        svc.repo = await asyncio.to_thread(svc._init_or_open_repo)
        return svc

    # ------------------------------------------------------------------
    # Blocking helpers (always called via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _init_or_open_repo(self) -> Repo:
        """Initialize or open existing Git repository (blocking)."""
        try:
            repo = Repo(self.repo_path)
            logger.info("git_repo_opened", path=str(self.repo_path))
            return repo

        except InvalidGitRepositoryError:
            logger.info("git_repo_initializing", path=str(self.repo_path))
            self.repo_path.mkdir(parents=True, exist_ok=True)

            try:
                repo = Repo.clone_from(self.repo_url, self.repo_path, branch=self.branch)
                logger.info("git_repo_cloned", url=self.repo_url, path=str(self.repo_path))
            except GitCommandError:
                repo = Repo.init(self.repo_path)

                try:
                    origin = repo.create_remote("origin", self.repo_url)
                except Exception:
                    origin = repo.remote("origin")
                    origin.set_url(self.repo_url)

                gitignore_path = self.repo_path / ".gitignore"
                gitignore_path.write_text("*.pyc\n__pycache__/\n.DS_Store\n")
                repo.index.add([".gitignore"])
                repo.index.commit(
                    "Initial commit",
                    author_date=datetime.now(timezone.utc).isoformat(),
                )

                try:
                    repo.git.checkout("-b", self.branch)
                except GitCommandError:
                    repo.git.checkout(self.branch)

                logger.info("git_repo_initialized", path=str(self.repo_path))

            return repo

    def _ensure_repo(self) -> Repo:
        """Return the repo instance; raise if not yet initialised."""
        if self.repo is None:
            raise GitError("GitService not initialised — use GitService.create()")
        return self.repo

    def _commit_backup_sync(self, backup: BackupObject, message: str | None = None) -> str:
        """Write + stage + commit a single backup (blocking)."""
        repo = self._ensure_repo()
        object_dir = self.repo_path / backup.org_id / backup.object_type
        object_dir.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
        file_name = f"{safe_name}_{backup.object_id}.json"
        file_path = object_dir / file_name

        with open(file_path, "w") as f:
            json.dump(backup.configuration, f, indent=2, sort_keys=True)

        repo.index.add([str(file_path.relative_to(self.repo_path))])

        if not message:
            message = self._generate_commit_message(backup)

        commit = repo.index.commit(
            message,
            author=f"{self.author_name} <{self.author_email}>",
            author_date=datetime.now(timezone.utc).isoformat(),
        )
        return commit.hexsha

    def _commit_multiple_sync(self, backups: list[BackupObject], message: str | None = None) -> str:
        """Write + stage + commit multiple backups (blocking)."""
        repo = self._ensure_repo()
        files_added = []
        for backup in backups:
            object_dir = self.repo_path / backup.org_id / backup.object_type
            object_dir.mkdir(parents=True, exist_ok=True)

            safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
            file_name = f"{safe_name}_{backup.object_id}.json"
            file_path = object_dir / file_name

            with open(file_path, "w") as f:
                json.dump(backup.configuration, f, indent=2, sort_keys=True)

            files_added.append(str(file_path.relative_to(self.repo_path)))

        repo.index.add(files_added)

        if not message:
            message = f"Backup: {len(backups)} objects updated"

        commit = repo.index.commit(
            message,
            author=f"{self.author_name} <{self.author_email}>",
            author_date=datetime.now(timezone.utc).isoformat(),
        )
        return commit.hexsha

    def _push_sync(self) -> None:
        """Pull + push to remote (blocking)."""
        repo = self._ensure_repo()
        origin = repo.remote("origin")
        try:
            origin.pull(self.branch)
        except GitCommandError as e:
            if "couldn't find remote ref" not in str(e).lower():
                raise
        origin.push(self.branch)

    def _delete_object_sync(self, backup: BackupObject, message: str | None = None) -> str | None:
        """Delete file + stage + commit (blocking)."""
        repo = self._ensure_repo()
        object_dir = self.repo_path / backup.org_id / backup.object_type
        safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
        file_name = f"{safe_name}_{backup.object_id}.json"
        file_path = object_dir / file_name

        if not file_path.exists():
            logger.warning("git_file_not_found_for_deletion", file_path=str(file_path))
            return None

        file_path.unlink()
        repo.index.remove([str(file_path.relative_to(self.repo_path))])

        if not message:
            message = f"Deleted: {backup.object_type} {backup.object_name or backup.object_id}"

        commit = repo.index.commit(
            message,
            author=f"{self.author_name} <{self.author_email}>",
            author_date=datetime.now(timezone.utc).isoformat(),
        )
        return commit.hexsha

    def _get_commit_history_sync(
        self,
        object_type: str | None = None,
        object_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read commit log (blocking)."""
        repo = self._ensure_repo()
        path_filter = None
        if object_type and object_id:
            path_filter = f"*/{object_type}/*_{object_id}.json"
        elif object_type:
            path_filter = f"*/{object_type}/*.json"

        if path_filter:
            commits = list(repo.iter_commits(self.branch, paths=path_filter, max_count=limit))
        else:
            commits = list(repo.iter_commits(self.branch, max_count=limit))

        commit_history = []
        for commit in commits:
            commit_history.append(
                {
                    "sha": commit.hexsha,
                    "message": commit.message.strip(),
                    "author": str(commit.author),
                    "author_email": commit.author.email,
                    "committed_at": datetime.fromtimestamp(commit.committed_date, tz=timezone.utc).isoformat(),
                    "stats": {
                        "files_changed": commit.stats.total["files"],
                        "insertions": commit.stats.total["insertions"],
                        "deletions": commit.stats.total["deletions"],
                    },
                }
            )
        return commit_history

    def _test_connection_sync(self) -> tuple[bool, str | None]:
        """Fetch from remote to verify connection (blocking)."""
        repo = self._ensure_repo()
        origin = repo.remote("origin")
        origin.fetch()
        return True, None

    # ------------------------------------------------------------------
    # Public async API (delegates to thread pool)
    # ------------------------------------------------------------------

    async def commit_backup(self, backup: BackupObject, message: str | None = None) -> str:
        """Commit a backup object to Git."""
        try:
            commit_sha = await asyncio.to_thread(self._commit_backup_sync, backup, message)
            logger.info(
                "git_backup_committed",
                object_id=backup.object_id,
                object_type=backup.object_type,
                commit_sha=commit_sha,
            )
            return commit_sha
        except Exception as e:
            logger.error("git_commit_failed", object_id=backup.object_id, error=str(e))
            raise GitError("Failed to commit backup to Git") from e

    async def commit_multiple_backups(self, backups: list[BackupObject], message: str | None = None) -> str:
        """Commit multiple backup objects in a single commit."""
        if not backups:
            raise ValueError("No backups provided")
        try:
            commit_sha = await asyncio.to_thread(self._commit_multiple_sync, backups, message)
            logger.info("git_multiple_backups_committed", count=len(backups), commit_sha=commit_sha)
            return commit_sha
        except Exception as e:
            logger.error("git_commit_multiple_failed", error=str(e))
            raise GitError("Failed to commit multiple backups") from e

    async def push_to_remote(self, max_retries: int = 3) -> None:
        """Push commits to remote repository."""
        for attempt in range(max_retries):
            try:
                await asyncio.to_thread(self._push_sync)
                logger.info("git_pushed_to_remote", branch=self.branch, attempt=attempt + 1)
                return
            except GitCommandError as e:
                logger.warning("git_push_failed", attempt=attempt + 1, max_retries=max_retries, error=str(e))
                if attempt == max_retries - 1:
                    raise GitError(f"Failed to push to remote after {max_retries} attempts") from e

    async def delete_object_file(self, backup: BackupObject, message: str | None = None) -> str | None:
        """Delete an object file from Git (for deleted objects)."""
        try:
            commit_sha = await asyncio.to_thread(self._delete_object_sync, backup, message)
            if commit_sha:
                logger.info("git_object_deleted", object_id=backup.object_id, commit_sha=commit_sha)
            return commit_sha
        except Exception as e:
            logger.error("git_delete_failed", object_id=backup.object_id, error=str(e))
            raise GitError("Failed to delete object from Git") from e

    async def get_commit_history(
        self,
        object_type: str | None = None,
        object_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get commit history."""
        try:
            return await asyncio.to_thread(self._get_commit_history_sync, object_type, object_id, limit)
        except Exception as e:
            logger.error("git_history_retrieval_failed", error=str(e))
            return []

    async def test_connection(self) -> tuple[bool, str | None]:
        """Test Git repository connection."""
        try:
            await asyncio.to_thread(self._test_connection_sync)
            logger.info("git_connection_test_success")
            return True, None
        except Exception as e:
            error_msg = str(e)
            logger.warning("git_connection_test_failed", error=error_msg)
            return False, error_msg

    # ------------------------------------------------------------------
    # Pure helpers (no I/O)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_git_url(url: str) -> None:
        """Validate Git URL scheme to prevent command injection."""
        from urllib.parse import urlparse

        _ALLOWED_SCHEMES = {"https", "ssh", "git"}
        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ConfigurationError(
                f"Unsupported Git URL scheme '{parsed.scheme}'. " f"Allowed: {', '.join(sorted(_ALLOWED_SCHEMES))}"
            )
        if url.lower().startswith("ext::"):
            raise ConfigurationError("ext:: Git protocol is not allowed")

    def _generate_commit_message(self, backup: BackupObject) -> str:
        """Generate commit message for backup."""
        event_messages = {
            "full_backup": f"Full backup: {backup.object_type} {backup.object_name}",
            "created": f"Created: {backup.object_type} {backup.object_name}",
            "updated": f"Updated: {backup.object_type} {backup.object_name}",
            "deleted": f"Deleted: {backup.object_type} {backup.object_name}",
            "restored": f"Restored: {backup.object_type} {backup.object_name}",
        }

        message = event_messages.get(backup.event_type.value, f"Backup: {backup.object_type} {backup.object_name}")
        message += f" (v{backup.version})"

        if backup.changed_fields:
            message += f"\n\nChanged fields: {', '.join(backup.changed_fields[:10])}"
            if len(backup.changed_fields) > 10:
                message += f" and {len(backup.changed_fields) - 10} more"

        return message

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize object name for use in filename."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")

        if len(name) > 50:
            name = name[:50]

        name = name.strip().strip(".")
        return name or "unnamed"
