import pytest_asyncio


def test_async_test_plugin_is_installed_for_all_test_gates() -> None:
    assert pytest_asyncio.__version__ == "0.26.0"
