import time

import requests

COLORS = {"eligible": 0x2ECC71, "check": 0xF1C40F, "ineligible": 0xE74C3C, "unknown": 0x95A5A6}
LABELS = {"eligible": "🟢 応募可能", "check": "🟡 条件を要確認", "ineligible": "🔴 条件外の可能性", "unknown": "⚪ 公式確認待ち"}


def _payload(item):
    deadline = item.deadline or "締切不明"
    start_at = item.start_at or "記載なし（受付中か要確認）"
    conditions = "、".join(item.conditions) or "記載なし"
    reasons = "\n".join(f"・{x}" for x in item.eligibility_reasons) or "・追加確認事項なし"
    return {
        "content": "応募したら、この投稿に ✅ リアクションを付けてください。",
        "embeds": [{
            "title": item.title[:256],
            "url": item.application_url,
            "color": COLORS[item.eligibility],
            "description": f"**{LABELS[item.eligibility]}**\n開始：{start_at}\n締切：{deadline}\n条件：{conditions}\n{reasons}",
            "footer": {"text": f"情報元: {item.store} | {'公式確認済み' if item.official_confirmed else '未確認情報'}"},
        }],
    }


def send_heading(webhook_url: str, text: str):
    response = requests.post(webhook_url, params={"wait": "true"}, json={"content": text}, timeout=20)
    response.raise_for_status()


def send_or_update(webhook_url: str, item):
    payload = _payload(item)
    if item.discord_message_id:
        response = requests.patch(f"{webhook_url}/messages/{item.discord_message_id}", json=payload, timeout=20)
        if response.status_code != 404:
            response.raise_for_status()
            return item.discord_message_id
    response = requests.post(webhook_url, params={"wait": "true"}, json=payload, timeout=20)
    response.raise_for_status()
    time.sleep(0.4)
    return response.json()["id"]


def send_new(webhook_url: str, item, calendar_url: str | None = None):
    """Post one compact alert for a newly discovered lottery only."""
    # The website is the source of truth.  Link directly to this lottery's
    # expandable detail card, rather than taking people straight to a store.
    destination = f"{calendar_url}#lottery-{item.id}" if calendar_url else item.application_url
    start_at = item.start_at or "-"
    deadline = item.deadline or "-"
    payload = {
        "content": "\U0001f195 \u65b0\u3057\u3044\u62bd\u9078\u60c5\u5831",
        "embeds": [{
            "title": item.title[:256],
            "url": destination,
            "color": 0x2563EB,
            "description": (
                f"**\u5e97\u8217**\uff1a{item.store}\n"
                f"**\u53d7\u4ed8\u671f\u9593**\uff1a{start_at} \u301c {deadline}\n"
                f"[\U0001f517 Web\u30b5\u30a4\u30c8\u3067\u8a73\u7d30\u3068\u6761\u4ef6\u3092\u78ba\u8a8d\u3059\u308b]({destination})"
            ),
            "footer": {"text": "\u30ab\u30fc\u30c9\u62bd\u9078\u901a\u77e5"},
        }],
    }
    response = requests.post(webhook_url, params={"wait": "true"}, json=payload, timeout=20)
    response.raise_for_status()
    time.sleep(0.4)
    return response.json()["id"]


def send_site_update(
    webhook_url: str,
    new_count: int,
    calendar_url: str | None = None,
    daily: bool = False,
    development: bool = False,
):
    """Post one small alert; all lottery details live on the website."""
    destination = calendar_url or ""
    if development:
        message = "🧪 開発テストが完了しました。公開Websiteは更新していません。"
    elif daily and new_count:
        message = f"\U0001f4c5 \u672c\u65e5\u306e\u62bd\u9078\u60c5\u5831\u3092\u66f4\u65b0\u3057\u307e\u3057\u305f\u3002\u65b0\u7740\u304c{new_count}\u4ef6\u3042\u308a\u307e\u3059\u3002"
    elif daily:
        message = "\U0001f4c5 \u672c\u65e5\u306e\u62bd\u9078\u60c5\u5831\u3092\u66f4\u65b0\u3057\u307e\u3057\u305f\u3002"
    else:
        message = f"\U0001f195 \u62bd\u9078\u60c5\u5831\u3092\u66f4\u65b0\u3057\u307e\u3057\u305f\u3002\u65b0\u7740\u304c{new_count}\u4ef6\u3042\u308a\u307e\u3059\u3002"
    if destination:
        message += f"\n\n\U0001f517 \u8a73\u7d30\u30fb\u6761\u4ef6\u30fb\u5fdc\u52df\u30ea\u30f3\u30af\u306f\u3053\u3061\u3089\n{destination}"
    response = requests.post(webhook_url, params={"wait": "true"}, json={"content": message}, timeout=20)
    response.raise_for_status()
    return response.json()["id"]


def send_review_queue_update(webhook_url: str, count: int, dashboard_url: str | None = None):
    """Alert the private operations channel without exposing candidate details."""
    message = f"🛠️ 確認待ちの抽選候補が{count}件追加されました。"
    if dashboard_url:
        message += f"\n\n🔐 管理サイトで確認・補完・承認する\n{dashboard_url}"
    response = requests.post(webhook_url, params={"wait": "true"}, json={"content": message}, timeout=20)
    response.raise_for_status()
    return response.json()["id"]
