import pytest

from .e2e import stack


# These hooks must be outside e2e/: the xdist controller does not collect tests.
def pytest_configure(config: pytest.Config) -> None:
    if not hasattr(config, "workerinput"):
        stack.create_state_dir()


def pytest_sessionfinish(session: pytest.Session) -> None:
    if not hasattr(session.config, "workerinput"):
        stack.stop()
