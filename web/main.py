"""FastAPI admin panel."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from database.database import init_db
from web.auth import SESSION_COOKIE, load_session_token
from web.routes import auth, dashboard, orders, products, settings

STATIC_DIR = Path(__file__).parent / "static"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        request.state.user = None

        public = (
            path.startswith("/static")
            or path in ("/login", "/api/yoomoney/notify")
            or path == "/settings/yoomoney/callback"
        )
        if public:
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        user = load_session_token(token) if token else None
        request.state.user = user

        if not user and path != "/login":
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="Digital Shop Admin", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.add_middleware(AuthMiddleware)

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(products.router)
    app.include_router(settings.router)
    app.include_router(orders.router)

    @app.on_event("startup")
    async def _startup():
        await init_db()

    return app


app = create_app()
