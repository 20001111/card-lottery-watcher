from datetime import datetime
from zoneinfo import ZoneInfo

from src.models import Lottery
from unittest.mock import patch

from src.supabase_sync import build_sync_rows, known_application_urls, manual_review_sources


def test_sync_rows_preserve_existing_staff_status_and_memo():
    item = Lottery(
        "id", "New AI title", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/entry/?utm_source=x", "2026-08-10T23:59:00+09:00", "2026-08-01T10:00:00+09:00",
    )
    rows = build_sync_rows([item], {"https://shop.example/entry": {"status": "suppressed", "note": "対象地域外"}})
    assert rows[0]["application_url"] == "https://shop.example/entry"
    assert rows[0]["status"] == "suppressed"
    assert rows[0]["note"] == "対象地域外"


def test_new_sync_rows_start_pending():
    item = Lottery("id", "Lottery", "pokemon", "Shop", "shop", "https://source.example", "https://shop.example/entry")
    assert build_sync_rows([item], {})[0]["status"] == "pending"


def test_sync_rows_merge_same_application_url_before_upsert():
    first = Lottery(
        "first", "Short title", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/entry?utm_source=one",
    )
    richer = Lottery(
        "second", "Complete title", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/entry?utm_source=two", "2026-08-10T23:59:00+09:00", "2026-08-01T10:00:00+09:00",
    )
    rows = build_sync_rows([first, richer], {})
    assert len(rows) == 1
    assert rows[0]["application_url"] == "https://shop.example/entry"
    assert rows[0]["listing"]["title"] == "Complete title"


def test_incomplete_later_scan_does_not_erase_staff_confirmed_dates():
    item = Lottery("id", "Lottery", "pokemon", "Shop", "shop", "https://source.example", "https://shop.example/entry")
    existing = {
        "https://shop.example/entry": {
            "status": "published",
            "listing": {
                "title": "Confirmed lottery",
                "store": "Confirmed shop",
                "start_at": "2026-08-10T10:00:00+09:00",
                "deadline": "2026-08-12T23:59:00+09:00",
                "conditions": ["Membership required"],
            },
        }
    }
    row = build_sync_rows([item], existing)[0]
    assert row["status"] == "published"
    assert row["listing"]["start_at"] == "2026-08-10T10:00:00+09:00"
    assert row["listing"]["deadline"] == "2026-08-12T23:59:00+09:00"


def test_sync_rows_keep_officer_micro_corrections():
    item = Lottery("id", "AI title", "pokemon", "AI shop", "shop", "https://source.example", "https://shop.example/entry")
    row = build_sync_rows([item], {"https://shop.example/entry": {"overrides": {"title": "Correct title", "region": "関東"}}})[0]
    assert row["listing"]["title"] == "Correct title"
    assert row["listing"]["region"] == "関東"


def test_manual_review_sources_include_only_pending_dashboard_urls(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"application_url": "https://shop.example/entry/?utm_source=discord", "listing": {"source_kind": "manual", "category": "pokemon"}},
                {"application_url": "https://shop.example/auto", "listing": {"source_kind": "discovery"}},
            ]

    with patch("src.supabase_sync.requests.get", return_value=Response()):
        sources = manual_review_sources()
    assert sources == [{
        "name": "確認待ちの応募URL",
        "store_key": "manual_submission",
        "kind": "manual",
        "category": "pokemon",
        "url": "https://shop.example/entry",
    }]


def test_known_application_urls_canonicalizes_tracking_parameters(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"application_url": "https://shop.example/entry/?utm_source=x"}]

    with patch("src.supabase_sync.requests.get", return_value=Response()):
        assert known_application_urls() == {"https://shop.example/entry"}


def test_published_listing_becomes_expired_after_deadline():
    item = Lottery(
        "id", "Lottery", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/entry", "2026-08-08T23:59:00+09:00", "2026-08-01T10:00:00+09:00",
    )
    rows = build_sync_rows(
        [item],
        {"https://shop.example/entry": {"status": "published"}},
        datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert rows[0]["status"] == "expired"
