"""Pytest configuration for live tests."""
import os
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: marks tests as requiring live DeepSeek credentials"
    )


def pytest_collection_modifyitems(config, items):
    if not os.getenv("DEEPFREE_LIVE_TESTS"):
        skip_live = pytest.mark.skip(reason="Live tests require DEEPFREE_LIVE_TESTS=1")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)