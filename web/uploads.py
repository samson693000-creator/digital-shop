"""File uploads for product images and delivery stock."""
from __future__ import annotations

import re
import secrets
import uuid
from pathlib import Path

from config import DATA_DIR

UPLOADS_DIR = DATA_DIR / "uploads"
PRODUCT_IMAGES_DIR = UPLOADS_DIR / "products"
DELIVERY_DIR = UPLOADS_DIR / "delivery"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
TXT_EXTS = {".txt"}
# что можно выдавать покупателю как файл
DELIVERY_EXTS = IMAGE_EXTS | TXT_EXTS | {
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp4",
    ".mp3",
}


def ensure_upload_dirs() -> None:
    PRODUCT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\-а-яА-ЯёЁ]+", "_", name, flags=re.UNICODE)
    return name[:120] or "file"


def encode_file_key(rel_path: str, original_name: str) -> str:
    return f"file:{rel_path}|{original_name}"


def parse_file_key(content: str) -> tuple[Path, str] | None:
    """Returns (absolute path, display name) for file: keys."""
    raw = (content or "").strip()
    if not raw.startswith("file:"):
        return None
    rest = raw[5:]
    if "|" in rest:
        rel, name = rest.split("|", 1)
    else:
        rel, name = rest, Path(rest).name
    path = (DATA_DIR / rel).resolve()
    try:
        path.relative_to(UPLOADS_DIR.resolve())
    except ValueError:
        return None
    return path, name


def is_file_key(content: str) -> bool:
    return (content or "").strip().startswith("file:")


def key_preview(content: str, max_len: int = 60) -> str:
    parsed = parse_file_key(content)
    if parsed:
        _path, name = parsed
        return f"📎 {name}"
    text = content or ""
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


async def save_upload(upload, dest_dir: Path, *, allowed: set[str]) -> tuple[str, str] | None:
    """
    Save UploadFile. Returns (path relative to DATA_DIR, original filename) or None.
    """
    ensure_upload_dirs()
    dest_dir.mkdir(parents=True, exist_ok=True)
    original = _safe_name(upload.filename or "file")
    ext = Path(original).suffix.lower()
    if ext not in allowed:
        return None
    stored = f"{uuid.uuid4().hex[:12]}_{secrets.token_hex(2)}{ext}"
    target = dest_dir / stored
    data = await upload.read()
    if not data:
        return None
    # limit ~25 MB
    if len(data) > 25 * 1024 * 1024:
        return None
    target.write_bytes(data)
    rel = str(target.relative_to(DATA_DIR)).replace("\\", "/")
    return rel, original


def read_txt_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()
