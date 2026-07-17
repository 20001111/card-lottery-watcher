from datetime import datetime
from zoneinfo import ZoneInfo

from src.ai_extract import page_document


def test_page_document_keeps_absolute_links():
    html = '<main><a href="/lottery/1">ポケモンカード抽選応募</a></main>'
    document, links = page_document(html, "https://shop.example.com/news")
    assert "https://shop.example.com/lottery/1" in document
    assert "https://shop.example.com/lottery/1" in links


def test_current_jst_fixture():
    assert datetime(2026, 7, 17, tzinfo=ZoneInfo("Asia/Tokyo")).utcoffset() is not None
