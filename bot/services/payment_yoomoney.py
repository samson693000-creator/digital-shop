"""YooMoney payment helpers (QuickPay + API + webhook)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from decimal import Decimal
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


def make_label() -> str:
    return secrets.token_hex(8)


def build_quickpay_url(
    wallet: str,
    amount: Decimal,
    label: str,
    success_url: str = "",
    payment_type: str = "AC",
) -> str:
    """
    YooMoney QuickPay link.
    payment_type: AC = карта, PC = кошелёк ЮMoney.
    """
    params = {
        "receiver": wallet,
        "quickpay-form": "button",
        "targets": f"Order {label}",
        "paymentType": payment_type,
        "sum": f"{amount:.2f}",
        "label": label,
    }
    if success_url:
        params["successURL"] = success_url
    return "https://yoomoney.ru/quickpay/confirm?" + urlencode(params)


def verify_notification(data: dict, notification_secret: str) -> bool:
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
) -> tuple[bool, str]:
    """
    Check incoming payment via YooMoney OAuth API (operation-history).
    Returns (paid, reason_code).
    """
    if not token:
        return False, "no_oauth_token"
    if not label:
        return False, "no_label"

    url = "https://yoomoney.ru/api/operation-history"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    # Without type filter — label can be on incoming-transfer / deposition
    payload = {"label": label, "records": 30}

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, headers=headers, data=payload)
            if resp.status_code == 401:
                return False, "oauth_unauthorized"
            if resp.status_code == 403:
                return False, "oauth_forbidden"
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("YooMoney operation-history failed")
        return False, "api_error"

    if data.get("error"):
        logger.warning("YooMoney API error: %s", data.get("error"))
        return False, f"api_{data.get('error')}"

    for op in data.get("operations", []):
        op_label = str(op.get("label") or "")
        if op_label != label:
            continue
        status = op.get("status")
        # success / in_progress — для входящих часто success
        if status not in (None, "success", "done"):
            continue
        try:
            amount = Decimal(str(op.get("amount", 0)))
        except Exception:
            continue
        # допускаем небольшую погрешность
        if amount + Decimal("0.01") >= expected_amount:
            return True, "ok"

    return False, "not_found"
