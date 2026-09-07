"""CRUD helpers for bot and admin panel."""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    Category,
    Order,
    PaymentSettings,
    Product,
    ProductKey,
    ReferralEarning,
    Setting,
    User,
)


@dataclass
class CatalogGroup:
    """Одна кнопка каталога: товар с суммарным остатком (дубли по имени+цене схлопываются)."""

    product_id: int
    category_id: int
    name: str
    price: Decimal
    description: str | None
    image_path: str | None
    is_infinite: bool
    stock: int  # для infinite: 1 если есть контент, иначе 0
    product_ids: list[int] = field(default_factory=list)

    @property
    def in_stock(self) -> bool:
        return self.stock > 0

    @property
    def stock_label(self) -> str:
        if self.is_infinite:
            return "∞" if self.stock > 0 else "0"
        return str(self.stock)


# ── Settings ─────────────────────────────────────────────────────────────────

async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(Setting, key)
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def get_all_settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Setting))).scalars().all()
    return {r.key: r.value for r in rows}


async def get_payment_settings(session: AsyncSession) -> PaymentSettings:
    pay = await session.get(PaymentSettings, 1)
    if pay is None:
        pay = PaymentSettings(id=1)
        session.add(pay)
        await session.commit()
        await session.refresh(pay)
    return pay


async def update_payment_settings(session: AsyncSession, **kwargs) -> PaymentSettings:
    pay = await get_payment_settings(session)
    for k, v in kwargs.items():
        if hasattr(pay, k) and v is not None:
            setattr(pay, k, v)
    await session.commit()
    await session.refresh(pay)
    return pay


# ── Users ────────────────────────────────────────────────────────────────────

def _gen_ref_code() -> str:
    return secrets.token_hex(4)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    full_name: str | None = None,
    referral_code: str | None = None,
) -> tuple[User, bool]:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.username = username
        user.full_name = full_name
        await session.commit()
        return user, False

    referrer_id = None
    if referral_code:
        ref = await session.execute(
            select(User).where(User.referral_code == referral_code)
        )
        referrer = ref.scalar_one_or_none()
        if referrer and referrer.telegram_id != telegram_id:
            referrer_id = referrer.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        referral_code=_gen_ref_code(),
        referred_by_id=referrer_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, True


async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def list_users(session: AsyncSession, limit: int = 100) -> list[User]:
    result = await session.execute(
        select(User).order_by(User.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_broadcast_targets(session: AsyncSession) -> list[int]:
    """Telegram IDs активных пользователей для рассылки."""
    result = await session.execute(
        select(User.telegram_id).where(User.is_active.is_(True)).order_by(User.id.asc())
    )
    return [int(x) for x in result.scalars().all()]


async def add_balance(session: AsyncSession, user_id: int, amount: Decimal) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")
    user.balance = Decimal(str(user.balance)) + amount
    await session.commit()
    await session.refresh(user)
    return user


async def deduct_balance(session: AsyncSession, user_id: int, amount: Decimal) -> bool:
    user = await session.get(User, user_id)
    if user is None or Decimal(str(user.balance)) < amount:
        return False
    user.balance = Decimal(str(user.balance)) - amount
    await session.commit()
    return True


# ── Categories ───────────────────────────────────────────────────────────────

async def list_categories(
    session: AsyncSession, parent_id: int | None = None, active_only: bool = True
) -> list[Category]:
    q = select(Category).where(Category.parent_id == parent_id)
    if active_only:
        q = q.where(Category.is_active.is_(True))
    q = q.order_by(Category.sort_order, Category.id)
    return list((await session.execute(q)).scalars().all())


async def list_all_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(
        select(Category).order_by(Category.sort_order, Category.id)
    )
    return list(result.scalars().all())


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def create_category(
    session: AsyncSession,
    name: str,
    description: str | None = None,
    parent_id: int | None = None,
    sort_order: int = 0,
) -> Category:
    cat = Category(
        name=name,
        description=description,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def update_category(session: AsyncSession, category_id: int, **kwargs) -> Category | None:
    cat = await session.get(Category, category_id)
    if not cat:
        return None
    for k, v in kwargs.items():
        if hasattr(cat, k) and v is not None:
            setattr(cat, k, v)
    await session.commit()
    await session.refresh(cat)
    return cat


async def delete_category(session: AsyncSession, category_id: int) -> tuple[bool, str]:
    """
    Удалить категорию.
    Подкатегории поднимаются на уровень родителя.
    Если есть товары — отказ (сначала удалите/перенесите товары).
    """
    cat = await session.get(Category, category_id)
    if not cat:
        return False, "not_found"

    products_count = (
        await session.execute(
            select(func.count(Product.id)).where(Product.category_id == category_id)
        )
    ).scalar() or 0
    if products_count:
        return False, "has_products"

    # Подкатегории → тот же parent, что был у удаляемой (или корень)
    await session.execute(
        update(Category)
        .where(Category.parent_id == category_id)
        .values(parent_id=cat.parent_id)
    )

    await session.delete(cat)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return False, "fk_error"
    return True, "ok"


# ── Products ─────────────────────────────────────────────────────────────────

async def list_products(
    session: AsyncSession, category_id: int | None = None, active_only: bool = True
) -> list[Product]:
    q = select(Product).options(selectinload(Product.keys), selectinload(Product.category))
    if category_id is not None:
        q = q.where(Product.category_id == category_id)
    if active_only:
        q = q.where(Product.is_active.is_(True))
    q = q.order_by(Product.id.desc())
    return list((await session.execute(q)).scalars().all())


async def list_catalog_groups(
    session: AsyncSession, category_id: int
) -> list[CatalogGroup]:
    """
    Товары категории, сгруппированные по (имя + цена + infinite).
    Остаток = сумма невыданных ключей по всем дублям группы.
    """
    products = await list_products(session, category_id=category_id, active_only=True)
    groups: dict[tuple, CatalogGroup] = {}
    for p in products:
        gkey = (
            (p.name or "").strip().casefold(),
            format(Decimal(str(p.price)), "f"),
            bool(p.is_infinite),
        )
        if gkey not in groups:
            groups[gkey] = CatalogGroup(
                product_id=p.id,
                category_id=p.category_id,
                name=p.name,
                price=Decimal(str(p.price)),
                description=p.description,
                image_path=p.image_path,
                is_infinite=bool(p.is_infinite),
                stock=0,
                product_ids=[p.id],
            )
        else:
            groups[gkey].product_ids.append(p.id)
            # Карточка — у самого «полного» / свежего представителя
            if p.image_path and not groups[gkey].image_path:
                groups[gkey].image_path = p.image_path
            if p.description and not groups[gkey].description:
                groups[gkey].description = p.description

        if p.is_infinite:
            if p.keys:
                groups[gkey].stock = 1
        else:
            groups[gkey].stock += sum(1 for k in p.keys if not k.is_sold)

    # Стабильный порядок: по имени
    return sorted(groups.values(), key=lambda g: (g.name.casefold(), g.product_id))


async def sibling_product_ids(session: AsyncSession, product: Product) -> list[int]:
    """ID товаров с тем же именем/ценой/типом в той же категории (дубли админки)."""
    result = await session.execute(
        select(Product.id).where(
            Product.category_id == product.category_id,
            Product.name == product.name,
            Product.price == product.price,
            Product.is_infinite.is_(bool(product.is_infinite)),
            Product.is_active.is_(True),
        )
    )
    ids = list(result.scalars().all())
    return ids or [product.id]


async def count_available_keys(
    session: AsyncSession, product_ids: list[int], *, infinite: bool = False
) -> int:
    if not product_ids:
        return 0
    if infinite:
        n = (
            await session.execute(
                select(func.count(ProductKey.id)).where(
                    ProductKey.product_id.in_(product_ids)
                )
            )
        ).scalar() or 0
        return 1 if n else 0
    return (
        await session.execute(
            select(func.count(ProductKey.id)).where(
                ProductKey.product_id.in_(product_ids),
                ProductKey.is_sold.is_(False),
            )
        )
    ).scalar() or 0


async def take_available_keys(
    session: AsyncSession, product_ids: list[int], count: int = 1
) -> list[ProductKey]:
    """Взять count свободных ключей (FOR UPDATE), без пометки sold — вызывает complete_order."""
    if count < 1 or not product_ids:
        return []
    result = await session.execute(
        select(ProductKey)
        .where(
            ProductKey.product_id.in_(product_ids),
            ProductKey.is_sold.is_(False),
        )
        .order_by(ProductKey.id.asc())
        .limit(count)
        .with_for_update()
    )
    return list(result.scalars().all())


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.keys), selectinload(Product.category))
        .where(Product.id == product_id)
    )
    return result.scalar_one_or_none()


async def create_product(
    session: AsyncSession,
    category_id: int,
    name: str,
    price: Decimal,
    description: str | None = None,
    keys: list[str] | None = None,
    image_path: str | None = None,
    is_infinite: bool = False,
) -> Product:
    product = Product(
        category_id=category_id,
        name=name,
        price=price,
        description=description,
        image_path=image_path,
        is_infinite=bool(is_infinite),
        is_active=True,
    )
    session.add(product)
    await session.flush()
    if keys:
        # Для бесконечного — только один постоянный контент
        to_add = keys[:1] if product.is_infinite else keys
        for content in to_add:
            content = content.strip()
            if content:
                session.add(ProductKey(product_id=product.id, content=content))
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, product_id: int, **kwargs) -> Product | None:
    product = await session.get(Product, product_id)
    if not product:
        return None
    for k, v in kwargs.items():
        if hasattr(product, k):
            setattr(product, k, v)
    await session.commit()
    await session.refresh(product)
    return product


async def set_product_static_content(
    session: AsyncSession, product_id: int, content: str
) -> bool:
    """Заменить постоянный контент бесконечного товара одним значением."""
    product = await get_product(session, product_id)
    if not product:
        return False
    content = (content or "").strip()
    if not content:
        return False
    await session.execute(delete(ProductKey).where(ProductKey.product_id == product_id))
    session.add(ProductKey(product_id=product_id, content=content, is_sold=False))
    product.is_active = True
    await session.commit()
    return True


async def get_static_key(session: AsyncSession, product_id: int) -> ProductKey | None:
    result = await session.execute(
        select(ProductKey)
        .where(ProductKey.product_id == product_id)
        .order_by(ProductKey.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def take_available_key(session: AsyncSession, product_id: int) -> ProductKey | None:
    result = await session.execute(
        select(ProductKey)
        .where(ProductKey.product_id == product_id, ProductKey.is_sold.is_(False))
        .limit(1)
        .with_for_update()
    )
    key = result.scalar_one_or_none()
    return key


async def delete_product(session: AsyncSession, product_id: int) -> bool:
    """Hard-delete product with related keys/orders (avoids FK 500)."""
    product = await session.get(Product, product_id)
    if not product:
        return False

    order_ids = list(
        (
            await session.execute(
                select(Order.id).where(Order.product_id == product_id)
            )
        ).scalars().all()
    )
    if order_ids:
        await session.execute(
            delete(ReferralEarning).where(ReferralEarning.order_id.in_(order_ids))
        )

    await session.execute(
        update(ProductKey)
        .where(ProductKey.product_id == product_id)
        .values(order_id=None)
    )
    await session.execute(
        delete(ProductKey).where(ProductKey.product_id == product_id)
    )
    if order_ids:
        await session.execute(delete(Order).where(Order.product_id == product_id))

    await session.delete(product)
    await session.commit()
    return True


async def add_keys(session: AsyncSession, product_id: int, keys: list[str]) -> int:
    product = await session.get(Product, product_id)
    count = 0
    if product and product.is_infinite:
        # Бесконечный: заменить одним контентом
        content = next((k.strip() for k in keys if k and k.strip()), "")
        if not content:
            return 0
        await session.execute(delete(ProductKey).where(ProductKey.product_id == product_id))
        session.add(ProductKey(product_id=product_id, content=content, is_sold=False))
        product.is_active = True
        await session.commit()
        return 1
    for content in keys:
        content = content.strip()
        if not content:
            continue
        session.add(ProductKey(product_id=product_id, content=content))
        count += 1
    await session.commit()
    return count


# ── Orders ───────────────────────────────────────────────────────────────────

async def create_order(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    amount: Decimal,
    payment_method: str,
    payment_address: str | None = None,
    payment_amount: Decimal | None = None,
    payment_memo: str | None = None,
    external_id: str | None = None,
    quantity: int = 1,
) -> Order:
    order = Order(
        user_id=user_id,
        product_id=product_id,
        amount=amount,
        payment_method=payment_method,
        payment_address=payment_address,
        payment_amount=payment_amount,
        payment_memo=payment_memo,
        external_id=external_id,
        quantity=max(1, int(quantity or 1)),
        status="pending",
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders(
    session: AsyncSession, user_id: int | None = None, limit: int = 100
) -> list[Order]:
    q = select(Order).options(selectinload(Order.product), selectinload(Order.user))
    if user_id is not None:
        q = q.where(Order.user_id == user_id)
    q = q.order_by(Order.created_at.desc()).limit(limit)
    return list((await session.execute(q)).scalars().all())


async def list_pending_orders(session: AsyncSession, method: str | None = None) -> list[Order]:
    q = (
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(Order.status == "pending")
        .order_by(Order.created_at.asc())
    )
    if method:
        q = q.where(Order.payment_method == method)
    return list((await session.execute(q)).scalars().all())


async def used_payment_refs(session: AsyncSession) -> set[str]:
    rows = (
        await session.execute(
            select(Order.payment_ref).where(
                Order.payment_ref.isnot(None),
                Order.payment_ref != "",
            )
        )
    ).scalars().all()
    return {str(r) for r in rows if r}


async def complete_order(
    session: AsyncSession,
    order_id: int,
    payment_ref: str | None = None,
) -> Order | None:
    """Mark order paid, deliver key(s), credit referral."""
    order = await get_order(session, order_id)
    if not order or order.status != "pending":
        return order
    if payment_ref:
        order.payment_ref = payment_ref[:128]

    product = order.product
    if product is None:
        product = await get_product(session, order.product_id)

    qty = max(1, int(getattr(order, "quantity", None) or 1))

    if product and product.is_infinite:
        ids = await sibling_product_ids(session, product)
        key = None
        for pid in ids:
            key = await get_static_key(session, pid)
            if key:
                break
        if key is None:
            order.status = "cancelled"
            await session.commit()
            return order
        # Один и тот же контент (qty раз только для отображения не дублируем файл)
        order.delivered_content = key.content
        product.is_active = True
    else:
        ids = await sibling_product_ids(session, product) if product else [order.product_id]
        keys = await take_available_keys(session, ids, qty)
        if len(keys) < qty:
            order.status = "cancelled"
            await session.commit()
            return order
        now = datetime.now(timezone.utc)
        parts: list[str] = []
        for i, key in enumerate(keys, start=1):
            key.is_sold = True
            key.sold_at = now
            key.order_id = order.id
            if qty > 1:
                parts.append(f"#{i}\n{key.content}")
            else:
                parts.append(key.content)
        order.delivered_content = "\n\n——————\n\n".join(parts)

    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)

    # Referral bonus
    user = await session.get(User, order.user_id)
    if user and user.referred_by_id:
        pay = await get_payment_settings(session)
        percent = Decimal(str(pay.referral_percent))
        bonus = (Decimal(str(order.amount)) * percent / Decimal("100")).quantize(
            Decimal("0.01")
        )
        if bonus > 0:
            referrer = await session.get(User, user.referred_by_id)
            if referrer:
                referrer.balance = Decimal(str(referrer.balance)) + bonus
                session.add(
                    ReferralEarning(
                        referrer_id=referrer.id,
                        referred_id=user.id,
                        order_id=order.id,
                        amount=bonus,
                        percent=percent,
                    )
                )

    await session.commit()
    await session.refresh(order)
    return order


async def cancel_order(session: AsyncSession, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order and order.status == "pending":
        order.status = "cancelled"
        await session.commit()
        await session.refresh(order)
    return order


# ── Stats / Referral ─────────────────────────────────────────────────────────

async def get_stats(session: AsyncSession) -> dict:
    users_count = (await session.execute(select(func.count(User.id)))).scalar() or 0
    orders_paid = (
        await session.execute(
            select(func.count(Order.id)).where(Order.status == "paid")
        )
    ).scalar() or 0
    revenue = (
        await session.execute(
            select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid")
        )
    ).scalar() or 0
    products_count = (await session.execute(select(func.count(Product.id)))).scalar() or 0
    keys_available = (
        await session.execute(
            select(func.count(ProductKey.id)).where(ProductKey.is_sold.is_(False))
        )
    ).scalar() or 0
    return {
        "users": users_count,
        "orders_paid": orders_paid,
        "revenue": float(revenue),
        "products": products_count,
        "keys_available": keys_available,
    }


async def get_referral_stats(session: AsyncSession, user_id: int) -> dict:
    refs = (
        await session.execute(select(func.count(User.id)).where(User.referred_by_id == user_id))
    ).scalar() or 0
    earned = (
        await session.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount), 0)).where(
                ReferralEarning.referrer_id == user_id
            )
        )
    ).scalar() or 0
    return {"referrals": refs, "earned": float(earned)}
