"""Shared fixture for the dbt-commerce-marts flows: the environment, a seeded store and dbt packages."""
import pytest

from e2e_support import dbt, local_env, seed_store


@pytest.fixture(scope="session")
def env():
    contract = local_env()
    seed_store(contract)
    dbt("deps")
    return contract
