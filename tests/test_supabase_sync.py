from datetime import datetime
from zoneinfo import ZoneInfo

from src.models import Lottery
from unittest.mock import patch

from src.supabase_sync import (
    archive_stale_suppressed,
    build_sync_rows,
    due_result_notifications,
    known_application_urls,
    manual_review_sources,
    published_listings,
)


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


def test_published_listings_uses_staff_approved_records_not_todays_scan(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "application_url": "https://shop.example/approved/?utm_source=x",
                    "status": "published",
                    "listing": {
                        "title": "Approved listing",
                        "start_at": "2026-08-10T10:00:00+09:00",
                        "deadline": "2026-08-12T23:59:00+09:00",
                    },
                },
                {
                    "application_url": "https://shop.example/pending",
                    "status": "pending",
                    "listing": {"title": "Not public"},
                },
                {
                    "application_url": "https://shop.example/expired",
                    "status": "published",
                    "listing": {"title": "Expired", "deadline": "2026-08-08T23:59:00+09:00"},
                },
            ]

    with patch("src.supabase_sync.requests.get", return_value=Response()):
        listings = published_listings(datetime(2026, 8, 11, tzinfo=ZoneInfo("Asia/Tokyo")))

    assert len(listings) == 1
    assert listings[0]["title"] == "Approved listing"
    assert listings[0]["application_url"] == "https://shop.example/approved"


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


def test_new_expired_listing_skips_the_review_queue():
    item = Lottery(
        "id", "Old lottery", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/old", "2026-08-08T23:59:00+09:00", "2026-08-01T10:00:00+09:00",
    )
    rows = build_sync_rows(
        [item],
        {},
        datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert rows[0]["status"] == "expired"


def test_pending_listing_becomes_expired_after_deadline():
    item = Lottery(
        "id", "Old pending lottery", "pokemon", "Shop", "shop", "https://source.example",
        "https://shop.example/old-pending", "2026-08-08T23:59:00+09:00", "2026-08-01T10:00:00+09:00",
    )
    rows = build_sync_rows(
        [item],
        {"https://shop.example/old-pending": {"status": "pending"}},
        datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    assert rows[0]["status"] == "expired"


def test_missing_source_does_not_leave_an_old_pending_listing_forever(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    existing = [{
        "application_url": "https://shop.example/source-gone",
        "status": "pending",
        "note": "",
        "overrides": {},
        "listing": {"deadline": "2026-08-08T23:59:00+09:00"},
    }]

    class GetResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return existing

    class PostResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    with patch("src.supabase_sync.requests.get", return_value=GetResponse()), \
         patch("src.supabase_sync.requests.post", return_value=PostResponse()) as post, \
         patch("src.supabase_sync.requests.patch", return_value=PostResponse()):
        from src.supabase_sync import sync_statuses
        states = sync_statuses([], datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Tokyo")))

    assert states["https://shop.example/source-gone"] == "expired"
    assert post.call_args.kwargs["json"][0]["status"] == "expired"


def test_old_rejected_listing_is_archived_but_its_url_is_kept(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"application_url": "https://shop.example/rejected"}]

    with patch("src.supabase_sync.requests.patch", return_value=Response()) as request:
        count = archive_stale_suppressed(
            datetime(2026, 8, 10, tzinfo=ZoneInfo("Asia/Tokyo")),
            retention_days=60,
        )
    assert count == 1
    assert request.call_args.kwargs["json"]["status"] == "expired"


def test_due_result_notification_requires_opt_in_and_is_not_already_sent(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"application_url": "https://shop.example/one", "listing": {
                    "title": "Notify", "result_notification_enabled": True,
                    "result_announcement_at": "2026-08-09T09:00:00+09:00",
                }},
                {"application_url": "https://shop.example/two", "listing": {
                    "result_notification_enabled": False,
                    "result_announcement_at": "2026-08-09T09:00:00+09:00",
                }},
                {"application_url": "https://shop.example/three", "listing": {
                    "result_notification_enabled": True,
                    "result_announcement_at": "2026-08-09T09:00:00+09:00",
                    "result_notified_at": "2026-08-09T09:05:00+09:00",
                }},
            ]

    with patch("src.supabase_sync.requests.get", return_value=Response()):
        due = due_result_notifications(datetime(2026, 8, 10, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert [record["application_url"] for record in due] == ["https://shop.example/one"]
