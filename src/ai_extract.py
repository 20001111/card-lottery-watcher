import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

API_URL = "https://models.github.ai/inference/chat/completions"


def page_document(html: str, page_url: str, max_chars: int = 30000):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, noscript, svg, header, footer"):
        tag.decompose()
    links = []
    for link in soup.find_all("a", href=True):
        label = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(page_url, link["href"])
        if label and url.startswith("http"):
            links.append((label[:160], url))
    text = "\n".join(x.strip() for x in soup.get_text("\n").splitlines() if x.strip())
    link_text = "\n".join(f"- {label}: {url}" for label, url in links[:250])
    return f"本文:\n{text[:max_chars]}\n\nページ内リンク:\n{link_text}"[:max_chars], {url for _, url in links}


def _json_content(content: str):
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
    return json.loads(content)


def extract_with_ai(source: dict, document: str, allowed_links: set[str], now: datetime, config: dict):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for AI extraction")
    max_days = int(config.get("max_deadline_days", 45))
    minimum_confidence = float(source.get("minimum_ai_confidence", config.get("minimum_ai_confidence", 0.75)))
    system = """あなたは日本のトレーディングカード抽選情報の検証担当です。
ページ本文に明記された事実だけを使います。商品紹介、発売予定だけ、終了済み、予約ではない通常販売、大会情報は除外してください。
現在応募受付中、または開始日時が明記された近日開始の抽選だけを抽出します。
日付を推測しません。応募締切と応募先URLが明記されていないものは除外します。
ポケモンカードとONE PIECEカードだけが対象です。URLを創作しません。
購入履歴、会員登録期限、アプリ、本人確認、受取店舗などの条件を短く正確に残してください。
JSON以外は出力しないでください。"""
    user = f"""現在日時: {now.isoformat()}
締切上限: 現在から{max_days}日以内
情報元: {source['name']}
情報元URL: {source['url']}

次のJSON形式で返してください。
{{"lotteries":[{{
  "title":"商品名を含む抽選名",
  "card_type":"pokemon または onepiece",
  "store":"実施店舗",
  "start_at":"ISO 8601またはnull",
  "deadline":"タイムゾーン付きISO 8601",
  "application_url":"本文のページ内リンクに存在する正式な応募・詳細URL",
  "requirements":["応募条件"],
  "evidence":"受付期間と抽選である根拠を短く記載",
  "confidence":0.0
}}]}}

ページ内容:
{document}"""
    user += """

For every result, inspect the linked page itself. Set official_confirmed to true only
when it is an official brand, store, or authorised retailer's actual application
page. Do not treat an X post, a news article, or an aggregation page as official.
Only include a result when the page states a real future application deadline and
the evidence states the dates and application conditions you found.
"""
    response = requests.post(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        json={
            "model": config.get("ai_model", "openai/gpt-4.1"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=90,
    )
    response.raise_for_status()
    data = _json_content(response.json()["choices"][0]["message"]["content"])
    valid = []
    for item in data.get("lotteries", []):
        try:
            deadline = date_parser.isoparse(item["deadline"])
        except (KeyError, TypeError, ValueError):
            continue
        if deadline.tzinfo is None or not (now < deadline <= now + __import__("datetime").timedelta(days=max_days)):
            continue
        url = item.get("application_url")
        if url not in allowed_links and url != source["url"]:
            continue
        if item.get("card_type") not in ("pokemon", "onepiece"):
            continue
        if source.get("require_official_confirmation") and item.get("official_confirmed") is not True:
            continue
        if source.get("require_official_confirmation") and not item.get("evidence"):
            continue
        if float(item.get("confidence", 0)) < minimum_confidence:
            continue
        valid.append(item)
    return valid
