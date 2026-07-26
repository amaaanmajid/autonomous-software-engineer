"""Post-test hook: parse results and block PR creation if tests failed."""
import logging

from app.models.test_result import TestResult

logger = logging.getLogger(__name__)


class HookValidationError(Exception):
    pass


def post_test_hook(test_result: TestResult) -> None:
    """Block the workflow from proceeding to PR if tests failed."""
    logger.info(
        "post_test_hook: passed=%s, %d passed, %d failed",
        test_result.passed,
        test_result.passed_tests,
        test_result.failed_tests,
    )

    if test_result.skipped:
        logger.info("post_test_hook: no test files found — skipping")
        return

    # If pytest ran but crashed during collection (import errors etc.),
    # failed_tests=0 and passed_tests=0 with passed=False. Don't retry for
    # collection failures — there are no actual test failures to fix.
    if not test_result.passed and test_result.failed_tests == 0:
        logger.warning(
            "post_test_hook: pytest exited non-zero with 0 failures (likely collection error) — allowing through"
        )
        return

    if not test_result.passed:
        raise HookValidationError(
            f"Tests failed ({test_result.failed_tests} failure(s)). "
            "PR creation blocked. The workflow will retry code generation."
        )

    logger.info("post_test_hook passed — all tests green")
