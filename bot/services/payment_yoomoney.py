"""YooMoney payment helpers (QuickPay + API + webhook)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Карта ЮMoney обычно берёт ~3% с получателя (50 ₽ → 48,50 ₽).
YM_MIN_RATIO = Decimal("0.90")
YM_MAX_OVER = Decimal("0.50")


def make_label() -> str:
    return secrets.token_hex(8)


def clean_oauth_token(token: str) -> str:
    t = (token or "").strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return "".join(t.split())


def yoomoney_amount_ok(expected: Decimal, received: Decimal, *, labeled: bool = False) -> bool:
    """True if received matches expected after typical card/wallet fees."""
    try:
        exp = Decimal(str(expected))
        got = Decimal(str(received))
    except Exception:
        return False
    if exp <= 0 or got <= 0:
        return False
    min_ok = (exp * (Decimal("0.80") if labeled else YM_MIN_RATIO)).quantize(Decimal("0.01"))
    max_ok = exp + YM_MAX_OVER
    return min_ok <= got <= max_ok


def build_quickpay_url(
    wallet: str,
    amount: Decimal,
    label: str,
    success_url: str = "",
    payment_type: str = "AC",
) -> str:
    params = {
        "receiver": wallet,
        "quickpay-form": "shop",
        "targets": f"Order {label}",
        "paymentType": payment_type,
        "sum": f"{amount:.2f}",
        "label": label,
    }
    if success_url:
        params["successURL"] = success_url
    return "https://yoomoney.ru/quickpay/confirm.xml?" + urlencode(params)


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


def _op_text(op: dict) -> str:
    bits = [
        op.get("label"),
        op.get("title"),
        op.get("details"),
        op.get("comment"),
        op.get("message"),
    ]
    return " ".join(str(x) for x in bits if x).lower()


def _parse_op_dt(op: dict) -> datetime | None:
    raw = op.get("datetime") or op.get("date") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _op_id(op: dict) -> str:
    return str(op.get("operation_id") or op.get("operationId") or "")


def _match_operation(
    operations: list,
    *,
    label: str,
    expected_amount: Decimal,
    used_ids: set[str],
    created_at: datetime | None,
) -> tuple[bool, str, str]:
    label = (label or "").strip()
    label_l = label.lower()
    created_utc = None
    if created_at is not None:
        created_utc = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        created_utc = created_utc.timestamp() - 180  # 3 мин запас на рассинхрон часов

    labeled: list[tuple[Decimal, dict]] = []
    unlabeled: list[tuple[Decimal, dict]] = []

    for op in operations:
        oid = _op_id(op)
        if oid and oid in used_ids:
            continue
        status = op.get("status")
        if status not in (None, "success", "done"):
            continue
        direction = str(op.get("direction") or op.get("type") or "")
        if direction in ("out", "payment"):
            continue
        try:
            amount = Decimal(str(op.get("amount", 0)))
        except Exception:
            continue
        if amount <= 0:
            continue

        op_dt = _parse_op_dt(op)
        if created_utc is not None and op_dt is not None:
            ts = op_dt.timestamp() if op_dt.tzinfo else op_dt.replace(tzinfo=timezone.utc).timestamp()
            if ts < created_utc:
                continue

        text = _op_text(op)
        op_label = str(op.get("label") or "").strip()
        has_label = bool(label) and (op_label == label or (label_l and label_l in text))
        if has_label:
            if yoomoney_amount_ok(expected_amount, amount, labeled=True):
                labeled.append((amount, op))
        else:
            unlabeled.append((amount, op))

    if labeled:
        _amt, op = labeled[0]
        return True, "ok", _op_id(op)

    # Без метки: сумма с учётом комиссии (50 → 48.50)
    for amount, op in unlabeled:
        if yoomoney_amount_ok(expected_amount, amount, labeled=False):
            return True, "ok_amount", _op_id(op)

    return False, "not_found", ""


async def _fetch_history(token: str, extra: dict) -> tuple[list, str | None]:
    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"records": 40, "details": "true", **extra}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, headers=headers, data=payload)
            if resp.status_code == 401:
                return [], "oauth_unauthorized"
            if resp.status_code == 403:
                return [], "oauth_forbidden"
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("YooMoney operation-history failed")
        return [], "api_error"

    if data.get("error"):
        logger.warning("YooMoney API error: %s", data.get("error"))
        return [], f"api_{data.get('error')}"
    return list(data.get("operations") or []), None


async def check_operation_by_label(
    token: str,
    label: str,
    expected_amount: Decimal,
    used_ids: set[str] | None = None,
    created_at: datetime | None = None,
) -> tuple[bool, str, str]:
    """Returns (paid, reason, operation_id)."""
    token = clean_oauth_token(token)
    if not token:
        return False, "no_oauth_token", ""
    if not label and expected_amount <= 0:
        return False, "no_label", ""

    used = used_ids or set()
    ops: list = []
    last_err: str | None = None

    queries = []
    if label:
        queries.append({"label": label, "type": "deposition"})
    queries.append({"type": "deposition"})
    queries.append({})

    seen: set[str] = set()
    for q in queries:
        chunk, err = await _fetch_history(token, q)
        if err and not chunk:
            last_err = err
            if err in ("oauth_unauthorized", "oauth_forbidden", "api_error"):
                return False, err, ""
            continue
        for op in chunk:
            oid = _op_id(op) or str(id(op))
            if oid in seen:
                continue
            seen.add(oid)
            ops.append(op)

    if not ops and last_err:
        return False, last_err, ""

    return _match_operation(
        ops,
        label=label or "",
        expected_amount=expected_amount,
        used_ids=used,
        created_at=created_at,
    )
