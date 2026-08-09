from datetime import datetime
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.ai_extract import extract_with_ai, page_document
from src.main import discovery_detail_urls, discovery_outbound_links


def test_page_document_keeps_absolute_links():
    html = '<main><a href="/lottery/1">ポケモンカード抽選応募</a></main>'
    document, links = page_document(html, "https://shop.example.com/news")
    assert "https://shop.example.com/lottery/1" in document
    assert "https://shop.example.com/lottery/1" in links


def test_current_jst_fixture():
    assert datetime(2026, 7, 17, tzinfo=ZoneInfo("Asia/Tokyo")).utcoffset() is not None


class _Response:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, lotteries):
        self._lotteries = lotteries

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"lotteries": self._lotteries})}}]}


def test_incomplete_linked_candidate_reaches_review_at_lower_confidence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    candidate = {
        "title": "Possible lottery",
        "card_type": "pokemon",
        "store": "Shop",
        "start_at": None,
        "deadline": None,
        "application_url": "https://shop.example/entry",
        "requirements": [],
        "confidence": 0.50,
    }
    with patch("src.ai_extract.requests.post", return_value=_Response([candidate])):
        results = extract_with_ai(
            {"name": "Discovery", "url": "https://news.example", "kind": "discovery"},
            "candidate page",
            {"https://shop.example/entry"},
            datetime(2026, 8, 1, tzinfo=ZoneInfo("Asia/Tokyo")),
            {"minimum_ai_confidence": 0.75, "candidate_minimum_ai_confidence": 0.45},
        )
    assert len(results) == 1
    assert results[0]["application_url"] == "https://shop.example/entry"


def test_discovery_page_itself_is_not_saved_as_application_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    candidate = {
        "title": "Aggregate page false lead",
        "card_type": "pokemon",
        "store": "Shop",
        "start_at": None,
        "deadline": None,
        "application_url": "https://news.example",
        "requirements": [],
        "confidence": 0.95,
    }
    with patch("src.ai_extract.requests.post", return_value=_Response([candidate])):
        results = extract_with_ai(
            {"name": "Discovery", "url": "https://news.example", "kind": "discovery"},
            "candidate page",
            {"https://shop.example/entry"},
            datetime(2026, 8, 1, tzinfo=ZoneInfo("Asia/Tokyo")),
            {"minimum_ai_confidence": 0.75, "candidate_minimum_ai_confidence": 0.45},
        )
    assert results == []


def test_discovery_detail_urls_stay_on_source_and_match_card_category():
    html = """
    <a href="/pokemon-summary">ポケモンカード 抽選まとめ</a>
    <a href="/onepiece-summary">ワンピースカード 抽選まとめ</a>
    <a href="https://other.example/pokemon">ポケカ外部リンク</a>
    <a href="/about">このサイトについて</a>
    """
    urls = discovery_detail_urls(
        html,
        "https://leads.example/",
        {"category": "pokemon"},
        3,
    )
    assert urls == ["https://leads.example/pokemon-summary"]


def test_discovery_outbound_links_keep_only_card_entry_links():
    html = """
    <p>ポケモンカードの抽選受付 <a href="https://shop.example/entry?utm_source=blog">応募ページ</a></p>
    <p>ポケモンカード相場 <a href="https://shop.example/market">市場価格</a></p>
    <p>ポケカ抽選 <a href="/internal">内部記事</a></p>
    """
    leads = discovery_outbound_links(
        html,
        "https://leads.example/summary",
        {"category": "pokemon"},
        20,
    )
    assert leads == [("https://shop.example/entry", "ポケモンカードの抽選受付 応募ページ")]


def test_discovery_outbound_links_use_relevant_page_scope_but_skip_ads():
    html = """
    <title>ポケモンカード 抽選まとめ</title><h1>ポケカ応募情報</h1>
    <p>店舗はこちら <a href="https://shop.example/entry">応募先</a></p>
    <p><a href="https://amzn.to/ad">広告</a></p><p><a href="https://wordpress.org">テーマ</a></p>
    """
    leads = discovery_outbound_links(html, "https://leads.example/summary", {"category": "pokemon"}, 20)
    assert leads == [("https://shop.example/entry", "店舗はこちら 応募先")]
