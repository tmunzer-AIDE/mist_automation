"""
Git service for backing up configurations to Git repositories.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import json
import structlog
from git import Repo, GitCommandError
from git.exc import InvalidGitRepositoryError

from app.modules.backup.models import BackupObject
from app.core.exceptions import GitError, ConfigurationError
from app.config import settings

logger = structlog.get_logger(__name__)


class GitService:
    """Service for Git repository management and commits."""

    def __init__(
        self,
        repo_path: str = "/backups/git",
        repo_url: Optional[str] = None,
        branch: str = "main",
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
    ):
        """
        Initialize Git service.

        Args:
            repo_path: Local path for Git repository
            repo_url: Remote repository URL
            branch: Branch name to use
            author_name: Git commit author name
            author_email: Git commit author email
        """
        self.repo_path = Path(repo_path)
        self.repo_url = repo_url or settings.backup_git_repo_url
        self.branch = branch or settings.backup_git_branch
        self.author_name = author_name or settings.backup_git_author_name
        self.author_email = author_email or settings.backup_git_author_email

        if not self.repo_url:
            raise ConfigurationError("Git repository URL not configured")

        # Ensure repo exists
        self.repo = self._init_or_open_repo()

    def _init_or_open_repo(self) -> Repo:
        """Initialize or open existing Git repository."""
        try:
            # Try to open existing repo
            repo = Repo(self.repo_path)
            logger.info("git_repo_opened", path=str(self.repo_path))
            return repo

        except InvalidGitRepositoryError:
            # Clone or initialize new repo
            logger.info("git_repo_initializing", path=str(self.repo_path))

            # Create directory if it doesn't exist
            self.repo_path.mkdir(parents=True, exist_ok=True)

            try:
                # Try to clone from remote
                repo = Repo.clone_from(self.repo_url, self.repo_path, branch=self.branch)
                logger.info("git_repo_cloned", url=self.repo_url, path=str(self.repo_path))
            except GitCommandError:
                # Initialize new repo if clone fails (empty remote)
                repo = Repo.init(self.repo_path)
                
                # Add remote
                try:
                    origin = repo.create_remote("origin", self.repo_url)
                except Exception:
                    origin = repo.remote("origin")
                    origin.set_url(self.repo_url)

                # Create initial commit
                gitignore_path = self.repo_path / ".gitignore"
                gitignore_path.write_text("*.pyc\n__pycache__/\n.DS_Store\n")
                repo.index.add([".gitignore"])
                repo.index.commit(
                    "Initial commit",
                    author_date=datetime.now(timezone.utc).isoformat(),
                )

                # Create branch
                try:
                    repo.git.checkout("-b", self.branch)
                except GitCommandError:
                    repo.git.checkout(self.branch)

                logger.info("git_repo_initialized", path=str(self.repo_path))

            return repo

    async def commit_backup(
        self,
        backup: BackupObject,
        message: Optional[str] = None,
    ) -> str:
        """
        Commit a backup object to Git.

        Args:
            backup: Backup object to commit
            message: Optional custom commit message

        Returns:
            Git commit SHA

        Raises:
            GitError: If commit fails
        """
        try:
            # Create directory structure: org_id/object_type/
            object_dir = self.repo_path / backup.org_id / backup.object_type
            object_dir.mkdir(parents=True, exist_ok=True)

            # File name: object_name_object_id.json
            safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
            file_name = f"{safe_name}_{backup.object_id}.json"
            file_path = object_dir / file_name

            # Write configuration to file
            with open(file_path, "w") as f:
                json.dump(backup.configuration, f, indent=2, sort_keys=True)

            # Stage the file
            self.repo.index.add([str(file_path.relative_to(self.repo_path))])

            # Generate commit message
            if not message:
                message = self._generate_commit_message(backup)

            # Create commit
            commit = self.repo.index.commit(
                message,
                author=f"{self.author_name} <{self.author_email}>",
                author_date=datetime.now(timezone.utc).isoformat(),
            )

            commit_sha = commit.hexsha

            logger.info(
                "git_backup_committed",
                object_id=backup.object_id,
                object_type=backup.object_type,
                commit_sha=commit_sha,
                file_path=str(file_path),
            )

            return commit_sha

        except Exception as e:
            logger.error(
                "git_commit_failed",
                object_id=backup.object_id,
                error=str(e),
            )
            raise GitError(f"Failed to commit backup to Git: {str(e)}")

    async def commit_multiple_backups(
        self,
        backups: list[BackupObject],
        message: Optional[str] = None,
    ) -> str:
        """
        Commit multiple backup objects in a single commit.

        Args:
            backups: List of backup objects
            message: Optional commit message

        Returns:
            Git commit SHA

        Raises:
            GitError: If commit fails
        """
        if not backups:
            raise ValueError("No backups provided")

        try:
            files_added = []

            # Write all backup files
            for backup in backups:
                object_dir = self.repo_path / backup.org_id / backup.object_type
                object_dir.mkdir(parents=True, exist_ok=True)

                safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
                file_name = f"{safe_name}_{backup.object_id}.json"
                file_path = object_dir / file_name

                with open(file_path, "w") as f:
                    json.dump(backup.configuration, f, indent=2, sort_keys=True)

                files_added.append(str(file_path.relative_to(self.repo_path)))

            # Stage all files
            self.repo.index.add(files_added)

            # Generate commit message
            if not message:
                message = f"Backup: {len(backups)} objects updated"

            # Create commit
            commit = self.repo.index.commit(
                message,
                author=f"{self.author_name} <{self.author_email}>",
                author_date=datetime.now(timezone.utc).isoformat(),
            )

            commit_sha = commit.hexsha

            logger.info(
                "git_multiple_backups_committed",
                count=len(backups),
                commit_sha=commit_sha,
            )

            return commit_sha

        except Exception as e:
            logger.error("git_commit_multiple_failed", error=str(e))
            raise GitError(f"Failed to commit multiple backups: {str(e)}")

    async def push_to_remote(self, max_retries: int = 3) -> None:
        """
        Push commits to remote repository.

        Args:
            max_retries: Maximum number of push retries

        Raises:
            GitError: If push fails after retries
        """
        for attempt in range(max_retries):
            try:
                # Pull first to avoid conflicts
                origin = self.repo.remote("origin")
                
                # Try to pull (may fail if remote is empty)
                try:
                    origin.pull(self.branch)
                except GitCommandError as e:
                    if "couldn't find remote ref" not in str(e).lower():
                        raise

                # Push
                origin.push(self.branch)

                logger.info("git_pushed_to_remote", branch=self.branch, attempt=attempt + 1)
                return

            except GitCommandError as e:
                logger.warning(
                    "git_push_failed",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )

                if attempt == max_retries - 1:
                    raise GitError(f"Failed to push to remote after {max_retries} attempts: {str(e)}")

    async def delete_object_file(
        self,
        backup: BackupObject,
        message: Optional[str] = None,
    ) -> str:
        """
        Delete an object file from Git (for deleted objects).

        Args:
            backup: Backup object to delete
            message: Optional commit message

        Returns:
            Git commit SHA

        Raises:
            GitError: If deletion fails
        """
        try:
            # Find the file
            object_dir = self.repo_path / backup.org_id / backup.object_type
            safe_name = self._sanitize_filename(backup.object_name or backup.object_id[:8])
            file_name = f"{safe_name}_{backup.object_id}.json"
            file_path = object_dir / file_name

            if not file_path.exists():
                logger.warning("git_file_not_found_for_deletion", file_path=str(file_path))
                return None

            # Remove the file
            file_path.unlink()

            # Stage deletion
            self.repo.index.remove([str(file_path.relative_to(self.repo_path))])

            # Generate commit message
            if not message:
                message = f"Deleted: {backup.object_type} {backup.object_name or backup.object_id}"

            # Create commit
            commit = self.repo.index.commit(
                message,
                author=f"{self.author_name} <{self.author_email}>",
                author_date=datetime.now(timezone.utc).isoformat(),
            )

            commit_sha = commit.hexsha

            logger.info(
                "git_object_deleted",
                object_id=backup.object_id,
                commit_sha=commit_sha,
            )

            return commit_sha

        except Exception as e:
            logger.error("git_delete_failed", object_id=backup.object_id, error=str(e))
            raise GitError(f"Failed to delete object from Git: {str(e)}")

    def get_commit_history(
        self,
        object_type: Optional[str] = None,
        object_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get commit history.

        Args:
            object_type: Optional filter by object type
            object_id: Optional filter by object ID
            limit: Maximum number of commits to return

        Returns:
            List of commit information
        """
        try:
            # Build path filter
            path_filter = None
            if object_type and object_id:
                path_filter = f"*/{object_type}/*_{object_id}.json"
            elif object_type:
                path_filter = f"*/{object_type}/*.json"

            # Get commits
            if path_filter:
                commits = list(self.repo.iter_commits(self.branch, paths=path_filter, max_count=limit))
            else:
                commits = list(self.repo.iter_commits(self.branch, max_count=limit))

            # Format commit info
            commit_history = []
            for commit in commits:
                commit_history.append({
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
                })

            return commit_history

        except Exception as e:
            logger.error("git_history_retrieval_failed", error=str(e))
            return []

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """
        Test Git repository connection.

        Returns:
            tuple: (success, error_message)
        """
        try:
            origin = self.repo.remote("origin")
            origin.fetch()
            logger.info("git_connection_test_success")
            return True, None

        except Exception as e:
            error_msg = str(e)
            logger.warning("git_connection_test_failed", error=error_msg)
            return False, error_msg

    # ===== Helper Methods =====

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

        # Add version info
        message += f" (v{backup.version})"

        # Add changed fields if available
        if backup.changed_fields:
            message += f"\n\nChanged fields: {', '.join(backup.changed_fields[:10])}"
            if len(backup.changed_fields) > 10:
                message += f" and {len(backup.changed_fields) - 10} more"

        return message

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize object name for use in filename."""
        # Replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")
        
        # Limit length
        if len(name) > 50:
            name = name[:50]
        
        # Remove leading/trailing whitespace and dots
        name = name.strip().strip(".")
        
        return name or "unnamed"
