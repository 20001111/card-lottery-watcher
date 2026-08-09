from src.models import Lottery, deduplicate_lotteries, lottery_identity


def test_lottery_identity_ignores_tracking_parameters():
    first = lottery_identity("Shop", "Pokemon lottery", "https://shop.example/entry/?utm_source=x", "2026-08-10T23:59:00+09:00")
    second = lottery_identity("shop", "Pokemon lottery", "https://shop.example/entry", "2026-08-10T10:00:00+09:00")
    assert first == second


def test_lottery_identity_is_one_per_application_page():
    first = lottery_identity("Store A", "Pokemon lottery", "https://shop.example/entry#details", "2026-08-10T23:59:00+09:00")
    second = lottery_identity("Store B", "Different AI title", "https://shop.example/entry", "2026-08-20T23:59:00+09:00")
    assert first == second


def test_deduplicate_lotteries_keeps_one_richer_record_per_application_url():
    url = "https://shop.example/entry"
    brief = Lottery("old", "Pokemon lottery", "pokemon", "Shop", "shop", "https://source.example", url, "2026-08-10T23:59:00+09:00", "2026-08-01T10:00:00+09:00")
    rich = Lottery("new", "Pokemon lottery - detailed", "pokemon", "Shop", "shop", "https://official.example", f"{url}?utm_source=x", "2026-08-10T23:59:00+09:00", "2026-08-01T10:00:00+09:00", ["Account required"], "official", True)
    merged = deduplicate_lotteries([brief, rich])
    assert len(merged) == 1
    assert merged[0].title == "Pokemon lottery - detailed"
    assert merged[0].conditions == ["Account required"]
