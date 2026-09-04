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


def clean_oauth_token(token: str) -> str:
    t = (token or "").strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    # remove accidental whitespace/newlines from copy-paste
    return "".join(t.split())


def build_quickpay_url(
    wallet: str,
    amount: Decimal,
    label: str,
    success_url: str = "",
    payment_type: str = "AC",
) -> str:
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


async def validate_oauth_token(token: str) -> tuple[bool, str]:
    """Call account-info to verify token. Returns (ok, message)."""
    token = clean_oauth_token(token)
    if not token:
        return False, "Токен пустой"
    if len(token) < 40:
        return False, f"Токен слишком короткий ({len(token)} симв.) — похоже, вставлен не access_token"

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                "https://yoomoney.ru/api/account-info",
                headers={"Authorization": f"Bearer {token}"},
            )
            body = resp.text[:300]
            if resp.status_code == 401:
                return False, "401 — токен неверный или отозван. Получите заново через OAuth."
            if resp.status_code == 403:
                return False, "403 — нет прав. При авторизации нужны account-info и operation-history."
            if resp.status_code >= 400:
                return False, f"HTTP {resp.status_code}: {body}"
            data = resp.json()
    except Exception as exc:
        return False, f"Сеть: {exc}"

    if data.get("error"):
        return False, f"Ошибка API: {data.get('error')}"

    account = data.get("account") or data.get("account_number") or "?"
    return True, f"OK · кошелёк API: {account} · длина токена: {len(token)}"


async def check_operation_by_label(
    token: str,
    label: str,
    expected_amount: Decimal,
) -> tuple[bool, str]:
    token = clean_oauth_token(token)
    if not token:
        return False, "no_oauth_token"
    if not label:
        return False, "no_label"

    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"label": label, "records": 50}

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
        if status not in (None, "success", "done"):
            continue
        try:
            amount = Decimal(str(op.get("amount", 0)))
        except Exception:
            continue
        if amount + Decimal("0.01") >= expected_amount:
            return True, "ok"

    # Fallback: recent incoming with same amount (label sometimes missing)
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={"records": 20, "type": "deposition"},
            )
            if resp.status_code == 200:
                data2 = resp.json()
                for op in data2.get("operations", []):
                    try:
                        amount = Decimal(str(op.get("amount", 0)))
                    except Exception:
                        continue
                    if abs(amount - expected_amount) <= Decimal("0.01"):
                        op_label = str(op.get("label") or "")
                        if not op_label or op_label == label:
                            return True, "ok_amount"
    except Exception:
        pass

    return False, "not_found"
