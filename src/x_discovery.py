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
    priority_accounts = {account.lstrip("@").lower() for account in settings.get("priority_accounts", [])}
    account_clause = " OR ".join(f"from:{account}" for account in sorted(priority_accounts))
    broad_clause = settings.get("query", '"ポケカ" (抽選 OR 応募)')
    query = f"({account_clause}) OR ({broad_clause})" if account_clause else broad_clause
    params = {
        "query": f"({query}) has:links lang:ja -is:retweet -is:reply",
        "max_results": max_posts,
        "tweet.fields": "created_at,entities,author_id",
        "expansions": "author_id",
        "user.fields": "username",
    }
    response = requests.get(SEARCH_URL, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
    response.raise_for_status()
    users = {user["id"]: user.get("username", "") for user in response.json().get("includes", {}).get("users", [])}
    seen = set()
    sources = []
    for post in response.json().get("data", []):
        for url_data in post.get("entities", {}).get("urls", []):
            url = url_data.get("expanded_url")
            if not url or url in seen or urlparse(url).netloc.endswith("x.com"):
                continue
            seen.add(url)
            author = users.get(post.get("author_id"), "").lower()
            sources.append({
                "name": f"X候補 @{author}" if author else "Xで見つけた候補",
                "store_key": "x_candidate",
                "kind": "discovery",
                "category": "pokemon",
                "url": url,
                "x_post_id": post.get("id"),
                "require_official_confirmation": settings.get("require_official_confirmation", True),
                # Known curators are useful leads, but every candidate is still
                # checked against its linked page before it can be notified.
                "minimum_ai_confidence": settings.get("priority_minimum_ai_confidence", 0.75)
                if author in priority_accounts else settings.get("other_minimum_ai_confidence", 0.88),
            })
            if len(sources) >= max_posts:
                return sources
    return sources
