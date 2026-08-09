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


def test_deduplicate_lotteries_merges_same_store_period_and_title_with_different_urls():
    first = Lottery(
        "first", "ONE PIECE Card Game Starter Deck EX Luffy & Ace [ST-30] lottery",
        "onepiece", "Otakarasoko Playz", "shop", "https://source-a.example",
        "https://shop.example/information/one", "2026-08-09T23:45:00+09:00",
        "2026-08-06T12:00:00+09:00",
    )
    second = Lottery(
        "second", "One Piece Card Game Starter Deck EX Luffy & Ace [ST-30] lottery (Otakarasoko Playz)",
        "onepiece", "Otakarasoko Playz", "shop", "https://source-b.example",
        "https://shop.example/information/two", "2026-08-09T23:45:00+09:00",
        "2026-08-06T12:00:00+09:00", ["Membership required"], "official", True,
    )
    merged = deduplicate_lotteries([first, second])
    assert len(merged) == 1
    assert merged[0].application_url == "https://shop.example/information/two"
    assert merged[0].conditions == ["Membership required"]


def test_deduplicate_lotteries_keeps_different_products_at_same_store_and_period():
    shared = dict(category="pokemon", store="Shop", store_key="shop", source_url="https://source.example", deadline="2026-08-09T23:45:00+09:00", start_at="2026-08-06T12:00:00+09:00")
    first = Lottery("first", "Pokemon Starter Deck 100 lottery", application_url="https://shop.example/one", **shared)
    second = Lottery("second", "Pokemon Mega Brave lottery", application_url="https://shop.example/two", **shared)
    assert len(deduplicate_lotteries([first, second])) == 2
