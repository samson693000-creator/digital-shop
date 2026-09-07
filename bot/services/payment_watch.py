"""Background scan of pending YooMoney / USDT payments."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Bot

from bot.services.delivery import deliver_order
from bot.services.payment_usdt import check_usdt_incoming
from bot.services.payment_yoomoney import check_operation_by_label
from database import crud
from database.database import async_session

logger = logging.getLogger(__name__)

POLL_SEC = 12
MAX_AGE = timedelta(hours=36)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _scan_once(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        pay = await crud.get_payment_settings(session)
        pending = await crud.list_pending_orders(session)
        used = await crud.used_payment_refs(session)

    for order in pending:
        created = _aware(order.created_at)
        if created and now - created > MAX_AGE:
            continue
        method = order.payment_method
        if method not in ("yoomoney", "usdt"):
            continue

        paid = False
        ref: str | None = None
        try:
            if method == "yoomoney":
                if not (pay.yoomoney_token or "").strip():
                    continue
                ok, reason, op_id = await check_operation_by_label(
                    token=pay.yoomoney_token or "",
                    label=order.external_id or "",
                    expected_amount=Decimal(str(order.amount)),
                    used_ids=used,
                    created_at=order.created_at,
                )
                if not ok and reason == "oauth_forbidden":
                    logger.error(
                        "YooMoney token missing operation-history — "
                        "re-authorize in admin settings (order #%s)",
                        order.id,
                    )
                    continue
                paid = ok
                ref = op_id or None
            elif method == "usdt" and order.payment_amount and pay.usdt_trc20_wallet:
                ts = int(created.timestamp() * 1000) if created else None
                paid = await check_usdt_incoming(
                    wallet=pay.usdt_trc20_wallet,
                    expected_amount=Decimal(str(order.payment_amount)),
                    api_key=pay.trongrid_api_key or "",
                    min_timestamp_ms=ts,
                )
                if paid:
                    ref = f"usdt:{order.payment_amount}"
        except Exception:
            logger.exception("watch order #%s", order.id)
            continue

        if not paid:
            continue

        async with async_session() as session:
            fresh = await crud.get_order(session, order.id)
            if not fresh or fresh.status != "pending":
                continue
            delivered = await deliver_order(session, bot, order.id, payment_ref=ref)
            if delivered:
                logger.info("Auto-delivered order #%s via %s", order.id, method)
                if ref:
                    used.add(ref)
            else:
                logger.warning("Payment found for #%s but delivery failed", order.id)


async def watch_pending_payments(bot: Bot) -> None:
    await asyncio.sleep(8)
    logger.info("Payment watcher started (every %ss)", POLL_SEC)
    while True:
        try:
            await _scan_once(bot)
        except Exception:
            logger.exception("Payment watcher cycle failed")
        await asyncio.sleep(POLL_SEC)
