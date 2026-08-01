from src.x_discovery import candidate_sources


def test_x_discovery_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "secret")
    assert candidate_sources({"enabled": False}) == []
