"""Shared fixture for the dbt-sessions-funnel flows: the local environment, with dbt packages installed."""
import pytest

from e2e_support import dbt, local_env


@pytest.fixture(scope="session")
def env():
    contract = local_env()
    dbt("deps")
    return contract
