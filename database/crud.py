"""CRUD helpers for bot and admin panel."""
from __future__ import annotations

import secrets
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


async def delete_category(session: AsyncSession, category_id: int) -> bool:
    cat = await session.get(Category, category_id)
    if not cat:
        return False
    await session.delete(cat)
    await session.commit()
    return True


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
) -> Product:
    product = Product(
        category_id=category_id,
        name=name,
        price=price,
        description=description,
    )
    session.add(product)
    await session.flush()
    if keys:
        for content in keys:
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
        if hasattr(product, k) and v is not None:
            setattr(product, k, v)
    await session.commit()
    await session.refresh(product)
    return product


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
    count = 0
    for content in keys:
        content = content.strip()
        if not content:
            continue
        session.add(ProductKey(product_id=product_id, content=content))
        count += 1
    await session.commit()
    return count


async def take_available_key(session: AsyncSession, product_id: int) -> ProductKey | None:
    result = await session.execute(
        select(ProductKey)
        .where(ProductKey.product_id == product_id, ProductKey.is_sold.is_(False))
        .limit(1)
        .with_for_update()
    )
    key = result.scalar_one_or_none()
    return key


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
    )
    if method:
        q = q.where(Order.payment_method == method)
    return list((await session.execute(q)).scalars().all())


async def complete_order(session: AsyncSession, order_id: int) -> Order | None:
    """Mark order paid, deliver key, credit referral."""
    order = await get_order(session, order_id)
    if not order or order.status != "pending":
        return order

    key = await take_available_key(session, order.product_id)
    if key is None:
        order.status = "cancelled"
        await session.commit()
        return order

    key.is_sold = True
    key.sold_at = datetime.now(timezone.utc)
    key.order_id = order.id
    order.delivered_content = key.content
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
