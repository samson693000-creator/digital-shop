from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import crud
from database.database import async_session

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="web/templates")


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    async with async_session() as session:
        settings_map = await crud.get_all_settings(session)
        pay = await crud.get_payment_settings(session)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings_map,
            "pay": pay,
            "page": "settings",
        },
    )


@router.post("/bot")
async def save_bot_settings(
    bot_token: str = Form(""),
    admin_ids: str = Form(""),
    welcome_text: str = Form(""),
):
    async with async_session() as session:
        await crud.set_setting(session, "bot_token", bot_token.strip())
        await crud.set_setting(session, "admin_ids", admin_ids.strip())
        await crud.set_setting(session, "welcome_text", welcome_text.strip())
    return RedirectResponse("/settings?saved=bot", status_code=302)


@router.post("/payments")
async def save_payment_settings(
    usdt_trc20_wallet: str = Form(""),
    trongrid_api_key: str = Form(""),
    yoomoney_wallet: str = Form(""),
    yoomoney_secret: str = Form(""),
    yoomoney_token: str = Form(""),
    referral_percent: float = Form(5.0),
):
    async with async_session() as session:
        await crud.update_payment_settings(
            session,
            usdt_trc20_wallet=usdt_trc20_wallet.strip(),
            trongrid_api_key=trongrid_api_key.strip(),
            yoomoney_wallet=yoomoney_wallet.strip(),
            yoomoney_secret=yoomoney_secret.strip(),
            yoomoney_token=yoomoney_token.strip(),
            referral_percent=referral_percent,
        )
    return RedirectResponse("/settings?saved=pay", status_code=302)
