from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.services.delivery import deliver_order
from bot.services.payment_yoomoney import verify_notification
from database import crud
from database.database import async_session

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    async with async_session() as session:
        orders = await crud.list_orders(session, limit=200)
        stats = await crud.get_stats(session)
    return templates.TemplateResponse(
        "orders.html",
        {"request": request, "orders": orders, "stats": stats, "page": "orders"},
    )


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
    form = dict(await request.form())
    async with async_session() as session:
        pay = await crud.get_payment_settings(session)
        if not pay.yoomoney_secret or not verify_notification(form, pay.yoomoney_secret):
            return HTMLResponse("bad signature", status_code=400)

        label = form.get("label", "")
        orders = await crud.list_pending_orders(session, method="yoomoney")
        order = next((o for o in orders if o.external_id == label), None)
        if not order:
            return HTMLResponse("ok")

        # Need bot instance — delivery message best-effort via token
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        token = await crud.get_setting(session, "bot_token", "")
        if token:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            try:
                await deliver_order(session, bot, order.id)
            finally:
                await bot.session.close()
        else:
            await crud.complete_order(session, order.id)

    return HTMLResponse("ok")
