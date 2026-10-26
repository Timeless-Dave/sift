import os

import pytest
from fastapi.testclient import TestClient

os.environ.pop("MODEL_API_KEY", None)


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    """Build an app with its own database and optional env overrides."""
    def build(**env):
        monkeypatch.setenv("SIFT_DB", str(tmp_path / "t.db"))
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        from sift.core.config import Settings
        from sift.http.app import create_app
        return TestClient(create_app(Settings()))
    return build


@pytest.fixture()
def client(make_client):
    return make_client()
