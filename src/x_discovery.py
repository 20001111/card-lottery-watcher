"""Use the official X API only as a narrow source of candidate pages."""

import os
from urllib.parse import urlparse

import requests


SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


def candidate_sources(settings: dict) -> list[dict]:
    """Return at most ``max_posts`` external links from one recent-search request."""
    if not settings.get("enabled"):
        return []
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        print("X discovery skipped: X_BEARER_TOKEN is not configured.")
        return []
    max_posts = max(10, min(int(settings.get("max_posts", 10)), 10))
    params = {
        "query": settings.get("query", '"ポケカ" (抽選 OR 応募) has:links lang:ja -is:retweet -is:reply'),
        "max_results": max_posts,
        "tweet.fields": "created_at,entities",
    }
    response = requests.get(SEARCH_URL, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
    response.raise_for_status()
    seen = set()
    sources = []
    for post in response.json().get("data", []):
        for url_data in post.get("entities", {}).get("urls", []):
            url = url_data.get("expanded_url")
            if not url or url in seen or urlparse(url).netloc.endswith("x.com"):
                continue
            seen.add(url)
            sources.append({
                "name": "Xで見つけた候補",
                "store_key": "x_candidate",
                "kind": "discovery",
                "category": "pokemon",
                "url": url,
                "x_post_id": post.get("id"),
            })
            if len(sources) >= max_posts:
                return sources
    return sources
