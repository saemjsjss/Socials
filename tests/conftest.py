"""Shared pytest settings for every test file.

  * the "slow" marker: tests that load a real model (they skip themselves when it is not cached);
  * no test may publish to a real Supabase: whatever .env or the environment says, publishing is
    switched off for every test (src.cloud does nothing then: no file, no process, no request).
    A test that wants publishing uses test_cloud's `cloud` fixture, which switches it on against
    the fake Supabase (httpx.MockTransport) and a launcher that starts nothing.
Every test file keeps its own fixtures otherwise.
"""
import sys
from pathlib import Path

import pytest

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: loads a real model (skipped when the model is absent)")


@pytest.fixture(autouse=True)
def _no_real_supabase(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", False)
