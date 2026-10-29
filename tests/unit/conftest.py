from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("DATABASE_MODE", "PERSISTENCE_BACKEND", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
