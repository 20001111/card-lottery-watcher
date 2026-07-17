def evaluate(lottery, profile: dict):
    data = profile.get(lottery.store_key, {})
    reasons = []
    failed = False

    checks = {
        "購入履歴": "purchase_history",
        "会員登録": "account",
        "アプリ": "app_installed",
        "本人確認": "identity_ready",
        "フォロー": "following",
        "クレジットカード": "credit_card_registered",
    }
    for label, key in checks.items():
        if label not in lottery.conditions:
            continue
        value = data.get(key)
        if value is False:
            failed = True
            reasons.append(f"{label}の条件を満たしていない可能性")
        elif value is not True:
            reasons.append(f"{label}を要確認")

    if failed:
        lottery.eligibility = "ineligible"
    elif reasons:
        lottery.eligibility = "check"
    else:
        lottery.eligibility = "eligible" if lottery.official_confirmed else "unknown"
    lottery.eligibility_reasons = reasons
    return lottery

