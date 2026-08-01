from src.x_discovery import candidate_sources


def test_x_discovery_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "secret")
    assert candidate_sources({"enabled": False}) == []


def test_priority_accounts_are_used_in_the_query(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "secret")
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [], "includes": {"users": []}}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("src.x_discovery.requests.get", fake_get)
    assert candidate_sources({"enabled": True, "priority_accounts": ["ExampleAccount"]}) == []
    assert "from:exampleaccount" in captured["params"]["query"]
