from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from database import crud
from database.database import async_session

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    async with async_session() as session:
        stats = await crud.get_stats(session)
        orders = await crud.list_orders(session, limit=10)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats, "orders": orders, "page": "dashboard"},
    )
