from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.services.delivery import deliver_order
from bot.services.payment_usdt import check_usdt_incoming
from bot.services.payment_yoomoney import (
    check_operation_by_label,
    validate_oauth_token,
    verify_notification,
    yoomoney_amount_ok,
)
from database import crud
from database.database import async_session

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def _bot_from_token(token: str):
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    async with async_session() as session:
        orders = await crud.list_orders(session, limit=200)
        stats = await crud.get_stats(session)
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "orders": orders,
            "stats": stats,
            "page": "orders",
            "flash": request.query_params.get("ok"),
            "error": request.query_params.get("err"),
        },
    )


@router.post("/orders/{order_id}/confirm")
async def confirm_order(order_id: int):
    """Ручное подтверждение оплаты админом + выдача товара."""
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order:
            return RedirectResponse("/orders?err=not_found", status_code=302)
        if order.status == "paid":
            return RedirectResponse("/orders?ok=already", status_code=302)
        if order.status != "pending":
            return RedirectResponse("/orders?err=closed", status_code=302)

        token = await crud.get_setting(session, "bot_token", "")
        if token:
            bot = _bot_from_token(token)
            try:
                ok = await deliver_order(session, bot, order_id)
            finally:
                await bot.session.close()
        else:
            completed = await crud.complete_order(session, order_id)
            ok = bool(completed and completed.status == "paid")

    if ok:
        return RedirectResponse("/orders?ok=confirmed", status_code=302)
    return RedirectResponse("/orders?err=deliver", status_code=302)


@router.post("/orders/check-payments")
async def check_pending_payments():
    """Сразу проверить все pending ЮMoney/USDT через API."""
    async with async_session() as session:
        pay = await crud.get_payment_settings(session)
        pending = await crud.list_pending_orders(session)
        used = await crud.used_payment_refs(session)
        bot_token = await crud.get_setting(session, "bot_token", "")

        if not pending:
            return RedirectResponse("/orders?ok=" + quote("Нет ожидающих заказов"), status_code=302)

        # Сначала явная проверка прав токена
        if any(o.payment_method == "yoomoney" for o in pending):
            tok_ok, tok_msg = await validate_oauth_token(pay.yoomoney_token or "")
            if not tok_ok:
                return RedirectResponse(
                    "/orders?err=" + quote("ЮMoney токен: " + tok_msg[:160]),
                    status_code=302,
                )

        found = 0
        checked = 0
        last_miss = ""
        bot = _bot_from_token(bot_token) if bot_token else None
        try:
            for order in pending:
                if order.payment_method == "yoomoney":
                    checked += 1
                    ok, reason, op_id = await check_operation_by_label(
                        token=pay.yoomoney_token or "",
                        label=order.external_id or "",
                        expected_amount=Decimal(str(order.amount)),
                        used_ids=used,
                        created_at=order.created_at,
                    )
                    if not ok:
                        last_miss = f"#{order.id}:{reason}"
                        continue
                    if bot:
                        delivered = await deliver_order(
                            session, bot, order.id, payment_ref=op_id or None
                        )
                    else:
                        completed = await crud.complete_order(
                            session, order.id, payment_ref=op_id or None
                        )
                        delivered = bool(completed and completed.status == "paid")
                    if delivered:
                        found += 1
                        if op_id:
                            used.add(op_id)
                elif order.payment_method == "usdt" and order.payment_amount:
                    checked += 1
                    ts = (
                        int(order.created_at.timestamp() * 1000)
                        if order.created_at
                        else None
                    )
                    ok = await check_usdt_incoming(
                        wallet=pay.usdt_trc20_wallet,
                        expected_amount=Decimal(str(order.payment_amount)),
                        api_key=pay.trongrid_api_key or "",
                        min_timestamp_ms=ts,
                    )
                    if not ok:
                        last_miss = f"#{order.id}:usdt_not_found"
                        continue
                    ref = f"usdt:{order.payment_amount}"
                    if bot:
                        delivered = await deliver_order(
                            session, bot, order.id, payment_ref=ref
                        )
                    else:
                        completed = await crud.complete_order(
                            session, order.id, payment_ref=ref
                        )
                        delivered = bool(completed and completed.status == "paid")
                    if delivered:
                        found += 1
        finally:
            if bot:
                await bot.session.close()

    if found:
        return RedirectResponse(
            "/orders?ok=" + quote(f"Найдено и выдано: {found} из {checked}"),
            status_code=302,
        )
    msg = f"Проверено {checked}, платежей не найдено"
    if last_miss:
        msg += f" ({last_miss})"
    return RedirectResponse("/orders?err=" + quote(msg[:180]), status_code=302)


@router.post("/orders/{order_id}/check")
async def check_one_order(order_id: int):
    """Проверить один pending-заказ через API."""
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order:
            return RedirectResponse("/orders?err=not_found", status_code=302)
        if order.status != "pending":
            return RedirectResponse("/orders?err=closed", status_code=302)

        pay = await crud.get_payment_settings(session)
        used = await crud.used_payment_refs(session)
        bot_token = await crud.get_setting(session, "bot_token", "")
        paid = False
        ref = None
        reason = "unsupported"

        if order.payment_method == "yoomoney":
            tok_ok, tok_msg = await validate_oauth_token(pay.yoomoney_token or "")
            if not tok_ok:
                return RedirectResponse(
                    "/orders?err=" + quote(tok_msg[:180]),
                    status_code=302,
                )
            paid, reason, op_id = await check_operation_by_label(
                token=pay.yoomoney_token or "",
                label=order.external_id or "",
                expected_amount=Decimal(str(order.amount)),
                used_ids=used,
                created_at=order.created_at,
            )
            ref = op_id or None
        elif order.payment_method == "usdt" and order.payment_amount:
            ts = int(order.created_at.timestamp() * 1000) if order.created_at else None
            paid = await check_usdt_incoming(
                wallet=pay.usdt_trc20_wallet,
                expected_amount=Decimal(str(order.payment_amount)),
                api_key=pay.trongrid_api_key or "",
                min_timestamp_ms=ts,
            )
            reason = "ok" if paid else "usdt_not_found"
            ref = f"usdt:{order.payment_amount}" if paid else None

        if not paid:
            return RedirectResponse(
                "/orders?err=" + quote(f"Заказ #{order_id}: {reason}"),
                status_code=302,
            )

        if bot_token:
            bot = _bot_from_token(bot_token)
            try:
                ok = await deliver_order(session, bot, order_id, payment_ref=ref)
            finally:
                await bot.session.close()
        else:
            completed = await crud.complete_order(session, order_id, payment_ref=ref)
            ok = bool(completed and completed.status == "paid")

    if ok:
        return RedirectResponse(
            "/orders?ok=" + quote(f"Заказ #{order_id} оплачен и выдан"),
            status_code=302,
        )
    return RedirectResponse("/orders?err=deliver", status_code=302)


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    async with async_session() as session:
        users = await crud.list_users(session, limit=500)
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "users": users, "page": "users"},
    )


@router.post("/api/yoomoney/notify")
async def yoomoney_notify(request: Request):
    """Public webhook for YooMoney HTTP notifications."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    async with async_session() as session:
        pay = await crud.get_payment_settings(session)
        if not pay.yoomoney_secret or not verify_notification(form, pay.yoomoney_secret):
            return HTMLResponse("bad signature", status_code=400)

        label = form.get("label", "")
        op_id = form.get("operation_id", "")
        orders = await crud.list_pending_orders(session, method="yoomoney")
        order = next((o for o in orders if label and o.external_id == label), None)
        if not order:
            try:
                got = Decimal(str(form.get("amount") or form.get("withdraw_amount") or "0"))
            except Exception:
                got = Decimal("0")
            order = next(
                (o for o in orders if yoomoney_amount_ok(Decimal(str(o.amount)), got)),
                None,
            )
        if not order:
            return HTMLResponse("ok")

        token = await crud.get_setting(session, "bot_token", "")
        if token:
            bot = _bot_from_token(token)
            try:
                await deliver_order(session, bot, order.id, payment_ref=op_id or None)
            finally:
                await bot.session.close()
        else:
            await crud.complete_order(session, order.id, payment_ref=op_id or None)

    return HTMLResponse("ok")
