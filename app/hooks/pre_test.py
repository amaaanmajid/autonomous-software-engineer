"""Pre-test hook: verify Docker is running and the repository is ready."""
import logging
from pathlib import Path

import docker
from docker.errors import DockerException

logger = logging.getLogger(__name__)


class HookValidationError(Exception):
    pass


def pre_test_hook(repository_path: str) -> None:
    """Verify Docker daemon is reachable and the repo path exists."""
    # Check Docker
    try:
        client = docker.from_env()
        client.ping()
        logger.info("pre_test_hook: Docker daemon is running")
    except DockerException as e:
        raise HookValidationError(
            f"Docker daemon is not running or not accessible: {e}. "
            "Start Docker Desktop and retry."
        ) from e

    # Check repo path
    repo_path = Path(repository_path)
    if not repo_path.exists():
        raise HookValidationError(f"Repository path does not exist: {repository_path}")

    logger.info("pre_test_hook passed for: %s", repository_path)
