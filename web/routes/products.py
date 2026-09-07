from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import crud
from database.database import async_session
from database.models import ProductKey
from web.uploads import (
    DELIVERY_DIR,
    DELIVERY_EXTS,
    IMAGE_EXTS,
    PRODUCT_IMAGES_DIR,
    encode_file_key,
    ensure_upload_dirs,
    key_preview,
    read_txt_bytes,
    save_upload,
)

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="web/templates")
templates.env.globals["key_preview"] = key_preview


def _split_keys(keys_text: str) -> list[str]:
    return [
        line.strip()
        for line in keys_text.replace("\r", "").split("\n")
        if line.strip()
    ]


@router.get("", response_class=HTMLResponse)
async def products_page(request: Request):
    async with async_session() as session:
        products = await crud.list_products(session, active_only=False)
        categories = await crud.list_all_categories(session)
    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "page": "products",
            "flash": request.query_params.get("ok"),
            "error": request.query_params.get("err"),
        },
    )


@router.post("/create")
async def create_product(
    name: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    keys_text: str = Form(""),
    image: UploadFile | None = File(None),
    description_file: UploadFile | None = File(None),
    delivery_files: list[UploadFile] = File(default=[]),
):
    ensure_upload_dirs()
    desc = (description or "").strip()

    # Описание из .txt (поверх поля, если файл не пустой)
    if description_file and description_file.filename:
        raw = await description_file.read()
        if raw:
            from_file = read_txt_bytes(raw)
            if from_file:
                desc = from_file

    image_rel = None
    if image and image.filename:
        saved = await save_upload(image, PRODUCT_IMAGES_DIR, allowed=IMAGE_EXTS)
        if not saved:
            return RedirectResponse(
                "/products?err=" + quote("Фото: только jpg/png/webp/gif до 25 МБ"),
                status_code=302,
            )
        image_rel, _ = saved

    keys = _split_keys(keys_text)
    for uf in delivery_files or []:
        if not uf or not uf.filename:
            continue
        saved = await save_upload(uf, DELIVERY_DIR, allowed=DELIVERY_EXTS)
        if not saved:
            continue
        rel, original = saved
        keys.append(encode_file_key(rel, original))

    async with async_session() as session:
        product = await crud.create_product(
            session,
            category_id=category_id,
            name=name.strip(),
            price=Decimal(str(price)),
            description=desc or None,
            keys=keys,
            image_path=image_rel,
        )
        pid = product.id
    if keys:
        return RedirectResponse(f"/products?ok=created_{len(keys)}", status_code=302)
    return RedirectResponse(f"/products/{pid}/keys?new=1", status_code=302)


@router.post("/{product_id}/update")
async def update_product(
    product_id: int,
    name: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    is_active: str = Form("off"),
):
    async with async_session() as session:
        await crud.update_product(
            session,
            product_id,
            name=name.strip(),
            category_id=category_id,
            price=Decimal(str(price)),
            description=description.strip(),
            is_active=is_active == "on",
        )
    return RedirectResponse("/products", status_code=302)


@router.post("/{product_id}/delete")
async def delete_product(product_id: int):
    try:
        async with async_session() as session:
            ok = await crud.delete_product(session, product_id)
        if not ok:
            return RedirectResponse("/products?err=not_found", status_code=302)
        return RedirectResponse("/products?ok=deleted", status_code=302)
    except Exception:
        return RedirectResponse("/products?err=delete_failed", status_code=302)


@router.get("/{product_id}/keys", response_class=HTMLResponse)
async def keys_page(request: Request, product_id: int):
    async with async_session() as session:
        product = await crud.get_product(session, product_id)
        if not product:
            return RedirectResponse("/products", status_code=302)
        available = [k for k in product.keys if not k.is_sold]
        sold = [k for k in product.keys if k.is_sold]
    return templates.TemplateResponse(
        "keys.html",
        {
            "request": request,
            "product": product,
            "available": available,
            "sold": sold,
            "page": "products",
            "is_new": request.query_params.get("new") == "1",
        },
    )


@router.post("/{product_id}/keys")
async def add_keys(product_id: int, keys_text: str = Form("")):
    lines = _split_keys(keys_text)
    async with async_session() as session:
        if lines:
            await crud.add_keys(session, product_id, lines)
    return RedirectResponse(f"/products/{product_id}/keys", status_code=302)


@router.post("/{product_id}/keys/files")
async def add_key_files(
    product_id: int,
    delivery_files: list[UploadFile] = File(default=[]),
):
    ensure_upload_dirs()
    keys: list[str] = []
    for uf in delivery_files:
        if not uf or not uf.filename:
            continue
        saved = await save_upload(uf, DELIVERY_DIR, allowed=DELIVERY_EXTS)
        if not saved:
            continue
        rel, original = saved
        keys.append(encode_file_key(rel, original))
    if keys:
        async with async_session() as session:
            await crud.add_keys(session, product_id, keys)
        return RedirectResponse(
            f"/products/{product_id}/keys?ok=files_{len(keys)}",
            status_code=302,
        )
    return RedirectResponse(
        f"/products/{product_id}/keys?err=" + quote("Не удалось загрузить файлы"),
        status_code=302,
    )


@router.post("/{product_id}/keys/{key_id}/delete")
async def delete_key(product_id: int, key_id: int):
    async with async_session() as session:
        key = await session.get(ProductKey, key_id)
        if key and key.product_id == product_id and not key.is_sold:
            await session.delete(key)
            await session.commit()
    return RedirectResponse(f"/products/{product_id}/keys", status_code=302)


@router.get("/categories/manage", response_class=HTMLResponse)
async def categories_page(request: Request):
    async with async_session() as session:
        categories = await crud.list_all_categories(session)
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "categories": categories,
            "page": "categories",
            "flash": request.query_params.get("ok"),
            "error": request.query_params.get("err"),
        },
    )


@router.post("/categories/create")
async def create_category(
    name: str = Form(...),
    description: str = Form(""),
    parent_id: str = Form(""),
    sort_order: int = Form(0),
):
    parent = int(parent_id) if parent_id.strip() else None
    async with async_session() as session:
        await crud.create_category(
            session,
            name=name.strip(),
            description=description.strip() or None,
            parent_id=parent,
            sort_order=sort_order,
        )
    return RedirectResponse("/products/categories/manage?ok=created", status_code=302)


@router.post("/categories/{category_id}/delete")
async def delete_category(category_id: int):
    async with async_session() as session:
        ok, reason = await crud.delete_category(session, category_id)
    if ok:
        return RedirectResponse("/products/categories/manage?ok=deleted", status_code=302)
    messages = {
        "not_found": "Категория не найдена",
        "has_products": "Сначала удалите или перенесите товары из этой категории",
        "fk_error": "Не удалось удалить (есть связанные данные)",
    }
    err = quote(messages.get(reason, reason))
    return RedirectResponse(f"/products/categories/manage?err={err}", status_code=302)
