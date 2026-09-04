from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

from bot.services.payment_yoomoney import clean_oauth_token, validate_oauth_token
from config import settings as app_settings
from database import crud
from database.database import async_session

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="web/templates")
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

DEFAULT_PUBLIC_BASE = "http://213.108.3.100:8000"

# ЮMoney НЕ принимает http://IP — только HTTPS или их свой URI.
# Рабочий вариант без домена:
YOOMONEY_REDIRECT_URI = "https://yoomoney.ru"


def _sync_env_bot_token(token: str) -> None:
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


def _state_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(app_settings.secret_key, salt="yoomoney-oauth")


def _public_base(stored: str, request: Request) -> str:
    base = (stored or "").strip().rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


def _auth_url(client_id: str, state: str) -> str:
    q = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": YOOMONEY_REDIRECT_URI,
            "scope": "account-info operation-history",
            "state": state,
        }
    )
    return f"https://yoomoney.ru/oauth/authorize?{q}"


async def _exchange_code(client_id: str, code: str) -> tuple[str | None, str]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://yoomoney.ru/oauth/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "grant_type": "authorization_code",
                    "redirect_uri": YOOMONEY_REDIRECT_URI,
                },
            )
            data = resp.json()
    except Exception as exc:
        return None, f"network:{exc}"

    token = (data.get("access_token") or "").strip()
    if not token:
        err = data.get("error") or data.get("error_description") or "no_token"
        return None, str(err)
    return token, "ok"


def _extract_code(raw: str) -> str:
    raw = (raw or "").strip()
    if "code=" in raw:
        raw = raw.split("code=")[-1].split("&")[0].strip()
    return raw


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    async with async_session() as session:
        settings_map = await crud.get_all_settings(session)
        pay = await crud.get_payment_settings(session)
        client_id = await crud.get_setting(session, "yoomoney_client_id", "")
        public_base = await crud.get_setting(session, "public_base_url", DEFAULT_PUBLIC_BASE)

    public_base = _public_base(public_base, request)
    auth_url = ""
    if client_id:
        state = _state_serializer().dumps({"cid": client_id})
        auth_url = _auth_url(client_id, state)

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
            "public_base": public_base,
            "oauth_ok": request.query_params.get("oauth"),
            "oauth_err": request.query_params.get("oauth_err"),
            "oauth_ready": request.query_params.get("oauth_ready"),
            "has_oauth_token": bool(pay.yoomoney_token),
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
    public_base: str = Form(""),
):
    token = clean_oauth_token(yoomoney_token)
    async with async_session() as session:
        if public_base.strip():
            await crud.set_setting(session, "public_base_url", public_base.strip().rstrip("/"))
        if not token:
            pay = await crud.get_payment_settings(session)
            token = clean_oauth_token(pay.yoomoney_token or "")
        await crud.update_payment_settings(
            session,
            usdt_trc20_wallet=usdt_trc20_wallet.strip(),
            trongrid_api_key=trongrid_api_key.strip(),
            yoomoney_wallet=yoomoney_wallet.strip(),
            yoomoney_secret=yoomoney_secret.strip(),
            yoomoney_token=token,
            referral_percent=referral_percent,
        )
    return RedirectResponse("/settings?saved=pay", status_code=302)


@router.post("/yoomoney/test-token")
async def test_yoomoney_token(yoomoney_token: str = Form("")):
    async with async_session() as session:
        pay = await crud.get_payment_settings(session)
        token = clean_oauth_token(yoomoney_token) or clean_oauth_token(pay.yoomoney_token or "")
    ok, msg = await validate_oauth_token(token)
    key = "oauth_ok" if ok else "oauth_err"
    return RedirectResponse(f"/settings?{key}=" + quote(msg[:120]) + "#ym", status_code=302)


@router.post("/yoomoney/prepare")
async def prepare_yoomoney_oauth(
    client_id: str = Form(...),
    mode: str = Form("link"),
):
    cid = client_id.strip()
    async with async_session() as session:
        await crud.set_setting(session, "yoomoney_client_id", cid)

    state = _state_serializer().dumps({"cid": cid})
    auth = _auth_url(cid, state)
    if mode == "go":
        return RedirectResponse(auth, status_code=302)
    return RedirectResponse("/settings?oauth_ready=1#ym", status_code=302)


@router.post("/yoomoney/exchange")
async def exchange_yoomoney_code(
    client_id: str = Form(""),
    code: str = Form(...),
):
    """Paste code or full https://yoomoney.ru/?code=... URL after authorize."""
    async with async_session() as session:
        stored_cid = await crud.get_setting(session, "yoomoney_client_id", "")
    cid = (client_id or stored_cid).strip()
    if not cid:
        return RedirectResponse(
            "/settings?oauth_err=" + quote("Сначала укажите Client ID") + "#ym",
            status_code=302,
        )

    raw_code = _extract_code(code)
    if not raw_code:
        return RedirectResponse(
            "/settings?oauth_err=" + quote("Пустой code") + "#ym",
            status_code=302,
        )

    token, status = await _exchange_code(cid, raw_code)
    if not token:
        return RedirectResponse(
            "/settings?oauth_err=" + quote(status[:100]) + "#ym",
            status_code=302,
        )

    token = clean_oauth_token(token)
    ok, msg = await validate_oauth_token(token)
    async with async_session() as session:
        await crud.set_setting(session, "yoomoney_client_id", cid)
        await crud.update_payment_settings(session, yoomoney_token=token)

    if ok:
        return RedirectResponse("/settings?oauth=ok#ym", status_code=302)
    return RedirectResponse(
        "/settings?oauth_err=" + quote("Сохранён, проверка: " + msg[:80]) + "#ym",
        status_code=302,
    )
