from src.models import Lottery
from src.supabase_sync import build_sync_rows


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
