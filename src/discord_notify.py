import time

import requests

COLORS = {"eligible": 0x2ECC71, "check": 0xF1C40F, "ineligible": 0xE74C3C, "unknown": 0x95A5A6}
LABELS = {"eligible": "🟢 応募可能", "check": "🟡 条件を要確認", "ineligible": "🔴 条件外の可能性", "unknown": "⚪ 公式確認待ち"}


def _payload(item):
    deadline = item.deadline or "締切不明"
    conditions = "、".join(item.conditions) or "記載なし"
    reasons = "\n".join(f"・{x}" for x in item.eligibility_reasons) or "・追加確認事項なし"
    return {
        "content": "応募したら、この投稿に ✅ リアクションを付けてください。",
        "embeds": [{
            "title": item.title[:256],
            "url": item.application_url,
            "color": COLORS[item.eligibility],
            "description": f"**{LABELS[item.eligibility]}**\n締切：{deadline}\n条件：{conditions}\n{reasons}",
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
