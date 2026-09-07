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

# Карта ЮMoney: ~3% с получателя (50 ₽ → 48,50 ₽). Запас шире на всякий случай.
YM_MIN_RATIO = Decimal("0.85")
YM_MAX_OVER = Decimal("1.00")

OAUTH_SCOPES = "account-info operation-history operation-details"


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
    min_ratio = Decimal("0.75") if labeled else YM_MIN_RATIO
    min_ok = (exp * min_ratio).quantize(Decimal("0.01"))
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
    """
    Verify token can read account AND operation-history.
    account-info alone is not enough for payment checks.
    """
    token = clean_oauth_token(token)
    if not token:
        return False, "Токен пустой"
    if len(token) < 40:
        return False, f"Токен слишком короткий ({len(token)} симв.) — похоже, вставлен не access_token"

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                "https://yoomoney.ru/api/account-info",
                headers=headers,
            )
            body = resp.text[:300]
            if resp.status_code == 401:
                return False, "401 — токен неверный или отозван. Получите заново через OAuth."
            if resp.status_code == 403:
                return False, "403 — нет права account-info. Получите токен заново и разрешите все права."
            if resp.status_code >= 400:
                return False, f"HTTP {resp.status_code}: {body}"
            data = resp.json()
            if data.get("error"):
                return False, f"Ошибка API: {data.get('error')}"

            account = data.get("account") or data.get("account_number") or "?"

            # Критично: без истории бот не найдёт оплату
            hist = await client.post(
                "https://yoomoney.ru/api/operation-history",
                headers=headers,
                data={"records": 1, "type": "deposition"},
            )
            if hist.status_code == 401:
                return False, "401 — токен неверный при чтении истории. Получите заново."
            if hist.status_code == 403:
                return (
                    False,
                    "НЕТ ПРАВА operation-history. В приложении ЮMoney включите "
                    "«Просмотр истории операций», затем снова: Открыть авторизацию → "
                    "разрешить ВСЕ права → обменять code.",
                )
            if hist.status_code >= 400:
                return False, f"История HTTP {hist.status_code}: {hist.text[:200]}"
            hist_data = hist.json()
            if hist_data.get("error"):
                err = str(hist_data.get("error"))
                if "forbidden" in err.lower() or "scope" in err.lower():
                    return (
                        False,
                        "Нет права operation-history. Перевыпустите токен и отметьте "
                        "просмотр истории операций.",
                    )
                return False, f"История: {err}"
    except Exception as exc:
        return False, f"Сеть: {exc}"

    return True, f"OK · кошелёк {account} · история доступна · токен {len(token)} симв."


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


def _op_amount(op: dict) -> Decimal | None:
    for key in ("amount", "amount_due", "sum"):
        if op.get(key) is None:
            continue
        try:
            val = Decimal(str(op.get(key)))
            if val > 0:
                return val
        except Exception:
            continue
    return None


def _is_incoming(op: dict) -> bool:
    direction = str(op.get("direction") or "").lower()
    if direction in ("out",):
        return False
    if direction in ("in",):
        return True
    op_type = str(op.get("type") or "").lower()
    if op_type in ("payment", "out"):
        return False
    if op_type in ("deposition", "incoming", "in"):
        return True
    # неизвестный тип — пробуем как входящий, если сумма > 0
    return True


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
    created_ts = None
    if created_at is not None:
        aware = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        created_ts = aware.timestamp() - 300  # 5 мин запас

    labeled: list[tuple[float, Decimal, dict]] = []
    unlabeled: list[tuple[float, Decimal, dict]] = []

    for op in operations:
        oid = _op_id(op)
        if oid and oid in used_ids:
            continue
        status = op.get("status")
        if status not in (None, "success", "done"):
            continue
        if not _is_incoming(op):
            continue
        amount = _op_amount(op)
        if amount is None:
            continue

        op_dt = _parse_op_dt(op)
        sort_ts = 0.0
        if op_dt is not None:
            sort_ts = op_dt.timestamp() if op_dt.tzinfo else op_dt.replace(tzinfo=timezone.utc).timestamp()
            if created_ts is not None and sort_ts < created_ts:
                continue

        text = _op_text(op)
        op_label = str(op.get("label") or "").strip()
        has_label = bool(label) and (
            op_label == label
            or (label_l and label_l in text)
            or (label_l and label_l in op_label.lower())
        )
        if has_label:
            if yoomoney_amount_ok(expected_amount, amount, labeled=True):
                labeled.append((sort_ts, amount, op))
        elif yoomoney_amount_ok(expected_amount, amount, labeled=False):
            # Чем ближе сумма к ожидаемой — тем лучше
            diff = abs(amount - expected_amount)
            unlabeled.append((diff, amount, op))

    if labeled:
        labeled.sort(key=lambda x: x[0])  # раньше по времени
        _ts, _amt, op = labeled[0]
        return True, "ok", _op_id(op)

    if unlabeled:
        unlabeled.sort(key=lambda x: (x[0], x[1]))  # ближе к сумме
        _diff, _amt, op = unlabeled[0]
        return True, "ok_amount", _op_id(op)

    return False, "not_found", ""


async def _fetch_history(token: str, extra: dict) -> tuple[list, str | None]:
    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"records": "50", **extra}
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
        err = str(data.get("error"))
        logger.warning("YooMoney API error: %s", err)
        if "forbidden" in err.lower():
            return [], "oauth_forbidden"
        return [], f"api_{err}"
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
    if expected_amount <= 0:
        return False, "no_amount", ""

    used = used_ids or set()
    ops: list = []
    last_err: str | None = None

    queries: list[dict] = []
    if label:
        queries.append({"label": label})
        queries.append({"label": label, "type": "deposition"})
    queries.append({"type": "deposition"})
    queries.append({})

    seen: set[str] = set()
    for q in queries:
        chunk, err = await _fetch_history(token, q)
        if err and not chunk:
            last_err = err
            if err in ("oauth_unauthorized", "oauth_forbidden"):
                return False, err, ""
            continue
        for op in chunk:
            oid = _op_id(op) or f"anon:{id(op)}"
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
