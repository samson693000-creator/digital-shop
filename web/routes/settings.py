from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import crud
from database.database import async_session

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="web/templates")
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Must match the Redirect URI in the YooMoney app settings
YOOMONEY_REDIRECT_URI = "https://yoomoney.ru"


def _sync_env_bot_token(token: str) -> None:
    """Keep .env BOT_TOKEN in sync so restarts always see the token."""
    if not ENV_PATH.exists():
        return
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith("BOT_TOKEN="):
            out.append(f"BOT_TOKEN={token}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"BOT_TOKEN={token}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def _yoomoney_auth_url(client_id: str) -> str:
    q = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": YOOMONEY_REDIRECT_URI,
            "scope": "account-info operation-history",
        }
    )
    return f"https://yoomoney.ru/oauth/authorize?{q}"


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    async with async_session() as session:
        settings_map = await crud.get_all_settings(session)
        pay = await crud.get_payment_settings(session)
        client_id = await crud.get_setting(session, "yoomoney_client_id", "")

    auth_url = _yoomoney_auth_url(client_id) if client_id else ""
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings_map,
            "pay": pay,
            "page": "settings",
            "yoomoney_client_id": client_id,
            "yoomoney_auth_url": auth_url,
            "yoomoney_redirect": YOOMONEY_REDIRECT_URI,
            "oauth_ok": request.query_params.get("oauth"),
            "oauth_err": request.query_params.get("oauth_err"),
        },
    )


@router.post("/bot")
async def save_bot_settings(
    bot_token: str = Form(""),
    admin_ids: str = Form(""),
    welcome_text: str = Form(""),
):
    token = bot_token.strip()
    async with async_session() as session:
        await crud.set_setting(session, "bot_token", token)
        await crud.set_setting(session, "admin_ids", admin_ids.strip())
        await crud.set_setting(session, "welcome_text", welcome_text.strip())
    _sync_env_bot_token(token)
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


@router.post("/yoomoney/save-client")
async def save_yoomoney_client(client_id: str = Form(...)):
    cid = client_id.strip()
    async with async_session() as session:
        await crud.set_setting(session, "yoomoney_client_id", cid)
    return RedirectResponse("/settings#yoomoney-oauth", status_code=302)


@router.post("/yoomoney/exchange")
async def exchange_yoomoney_code(
    client_id: str = Form(...),
    code: str = Form(...),
):
    """Exchange OAuth code → access_token and save to payment settings."""
    cid = client_id.strip()
    raw_code = code.strip()
    # User may paste full URL or "code=xxx"
    if "code=" in raw_code:
        raw_code = raw_code.split("code=")[-1].split("&")[0].strip()

    async with async_session() as session:
        await crud.set_setting(session, "yoomoney_client_id", cid)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://yoomoney.ru/oauth/token",
                data={
                    "code": raw_code,
                    "client_id": cid,
                    "grant_type": "authorization_code",
                    "redirect_uri": YOOMONEY_REDIRECT_URI,
                },
            )
            data = resp.json()
    except Exception:
        return RedirectResponse(
            "/settings?oauth_err=" + quote("network"),
            status_code=302,
        )

    token = (data.get("access_token") or "").strip()
    if not token:
        err = data.get("error") or data.get("error_description") or "no_token"
        return RedirectResponse(
            "/settings?oauth_err=" + quote(str(err)[:80]),
            status_code=302,
        )

    async with async_session() as session:
        await crud.update_payment_settings(session, yoomoney_token=token)

    return RedirectResponse("/settings?oauth=ok#yoomoney-oauth", status_code=302)
