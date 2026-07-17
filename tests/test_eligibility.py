from src.eligibility import evaluate
from src.models import Lottery


def make_lottery():
    return Lottery("1", "test", "pokemon", "GEO", "geo", "https://example.com", "https://example.com", conditions=["購入履歴", "アプリ"], official_confirmed=True)


def test_unknown_conditions_require_check():
    item = evaluate(make_lottery(), {"geo": {"purchase_history": True}})
    assert item.eligibility == "check"
    assert "アプリを要確認" in item.eligibility_reasons


def test_failed_condition_is_ineligible():
    item = evaluate(make_lottery(), {"geo": {"purchase_history": False, "app_installed": True}})
    assert item.eligibility == "ineligible"

