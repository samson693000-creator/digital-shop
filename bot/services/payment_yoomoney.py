"""YooMoney payment helpers (P2P / quickpay)."""
from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal
from urllib.parse import urlencode

import httpx


def make_label() -> str:
    return secrets.token_hex(8)


def build_quickpay_url(
    wallet: str,
    amount: Decimal,
    label: str,
    success_url: str = "",
) -> str:
    """YooMoney QuickPay form URL for transfer to wallet."""
    params = {
        "receiver": wallet,
        "quickpay-form": "shop",
        "targets": f"Order {label}",
        "paymentType": "SB",
        "sum": f"{amount:.2f}",
        "label": label,
    }
    if success_url:
        params["successURL"] = success_url
    return "https://yoomoney.ru/quickpay/confirm.xml?" + urlencode(params)


def verify_notification(
    data: dict,
    notification_secret: str,
) -> bool:
    """
    Verify YooMoney HTTP notification signature.
    sha1(notification_type&operation_id&amount&currency&datetime&sender&codepro&notification_secret&label)
    """
    parts = [
        data.get("notification_type", ""),
        data.get("operation_id", ""),
        data.get("amount", ""),
        data.get("currency", ""),
        data.get("datetime", ""),
        data.get("sender", ""),
        data.get("codepro", ""),
        notification_secret,
        data.get("label", ""),
    ]
    check_string = "&".join(parts)
    digest = hashlib.sha1(check_string.encode("utf-8")).hexdigest()
    return digest == data.get("sha1_hash", "")


async def check_operation_by_label(
    token: str,
    label: str,
    expected_amount: Decimal,
) -> bool:
    """
    Optional: check recent operations via YooMoney API (OAuth token).
    Falls back to False if token empty / API fails — webhook is preferred.
    """
    if not token:
        return False

    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"label": label, "records": 10, "type": "deposition"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, data=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return False

    for op in data.get("operations", []):
        if op.get("label") != label:
            continue
        if op.get("status") != "success":
            continue
        try:
            amount = Decimal(str(op.get("amount", 0)))
        except Exception:
            continue
        if amount >= expected_amount:
            return True
    return False
