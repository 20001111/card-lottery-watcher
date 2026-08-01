from src.models import lottery_identity


def test_lottery_identity_ignores_tracking_parameters():
    first = lottery_identity("Shop", "Pokemon lottery", "https://shop.example/entry/?utm_source=x", "2026-08-10T23:59:00+09:00")
    second = lottery_identity("shop", "Pokemon lottery", "https://shop.example/entry", "2026-08-10T10:00:00+09:00")
    assert first == second
