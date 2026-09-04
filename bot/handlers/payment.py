from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards import check_payment_kb, payment_methods_kb
from bot.services.delivery import deliver_order
from bot.services.payment_usdt import check_usdt_incoming, unique_usdt_amount
from bot.services.payment_yoomoney import (
    build_quickpay_url,
    check_operation_by_label,
    make_label,
)
from database import crud
from database.database import async_session

router = Router()


@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user, _ = await crud.get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        product = await crud.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Товар недоступен", show_alert=True)
            return
        if product.available_count < 1:
            await callback.answer("Нет в наличии", show_alert=True)
            return

        # Placeholder order — payment method chosen next
        order = await crud.create_order(
            session,
            user_id=user.id,
            product_id=product.id,
            amount=Decimal(str(product.price)),
            payment_method="pending",
        )
        order_id = order.id
        price = product.price
        name = product.name

    await callback.message.edit_text(
        f"💳 <b>Оформление заказа #{order_id}</b>\n\n"
        f"📦 {name}\n"
        f"💰 Сумма: <b>{price} ₽</b>\n\n"
        f"Выберите способ оплаты:",
        reply_markup=payment_methods_kb(order_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay:usdt:"))
async def pay_usdt(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order or order.status != "pending":
            await callback.answer("Заказ недоступен", show_alert=True)
            return
        if order.user.telegram_id != callback.from_user.id:
            await callback.answer("Это не ваш заказ", show_alert=True)
            return

        pay = await crud.get_payment_settings(session)
        if not pay.usdt_trc20_wallet:
            await callback.answer("USDT временно недоступен", show_alert=True)
            return

        # Amount in USDT ≈ RUB/100 as placeholder rate; admin can adjust via unique micro
        # Better: treat product price as USDT if small, else convert ~100 RUB = 1 USDT demo
        usdt_amount = unique_usdt_amount(Decimal(str(order.amount)) / Decimal("100"))
        order.payment_method = "usdt"
        order.payment_address = pay.usdt_trc20_wallet
        order.payment_amount = usdt_amount
        await session.commit()
        wallet = pay.usdt_trc20_wallet

    await callback.message.edit_text(
        f"💎 <b>Оплата USDT TRC-20</b>\n"
        f"Заказ #{order_id}\n\n"
        f"Отправьте <b>ровно</b>:\n"
        f"<code>{usdt_amount}</code> USDT\n\n"
        f"На адрес (TRC-20):\n"
        f"<code>{wallet}</code>\n\n"
        f"⚠️ Сумма уникальна — отправьте её без округления.\n"
        f"После перевода нажмите «Проверить оплату».",
        reply_markup=check_payment_kb(order_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay:yoomoney:"))
async def pay_yoomoney(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order or order.status != "pending":
            await callback.answer("Заказ недоступен", show_alert=True)
            return
        if order.user.telegram_id != callback.from_user.id:
            await callback.answer("Это не ваш заказ", show_alert=True)
            return

        pay = await crud.get_payment_settings(session)
        if not pay.yoomoney_wallet:
            await callback.answer("ЮMoney временно недоступна", show_alert=True)
            return

        label = make_label()
        amount = Decimal(str(order.amount))
        url = build_quickpay_url(pay.yoomoney_wallet, amount, label)
        order.payment_method = "yoomoney"
        order.payment_memo = label
        order.external_id = label
        order.payment_amount = amount
        order.payment_address = pay.yoomoney_wallet
        await session.commit()

    await callback.message.edit_text(
        f"💰 <b>Оплата ЮMoney</b>\n"
        f"Заказ #{order_id}\n\n"
        f"Сумма: <b>{amount:.2f} ₽</b>\n"
        f"Метка платежа: <code>{label}</code>\n\n"
        f"Оплатить: {url}\n\n"
        f"После оплаты нажмите «Проверить оплату» "
        f"(или дождитесь автоуведомления).",
        reply_markup=check_payment_kb(order_id),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay:balance:"))
async def pay_balance(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order or order.status != "pending":
            await callback.answer("Заказ недоступен", show_alert=True)
            return
        if order.user.telegram_id != callback.from_user.id:
            await callback.answer("Это не ваш заказ", show_alert=True)
            return

        amount = Decimal(str(order.amount))
        ok = await crud.deduct_balance(session, order.user_id, amount)
        if not ok:
            await callback.answer("Недостаточно средств на балансе", show_alert=True)
            return

        order.payment_method = "balance"
        await session.commit()
        delivered = await deliver_order(session, callback.bot, order_id)

    if delivered:
        await callback.message.edit_text(
            f"✅ Заказ #{order_id} оплачен с баланса.\nТовар отправлен в чат."
        )
    else:
        await callback.message.edit_text(
            f"⚠️ Оплата прошла, но товар закончился. Обратитесь к администратору.\n"
            f"Заказ #{order_id}"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("check:"))
async def check_payment(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return
        if order.status == "paid":
            await callback.answer("Уже оплачен", show_alert=True)
            return
        if order.status != "pending":
            await callback.answer("Заказ закрыт", show_alert=True)
            return
        if order.user.telegram_id != callback.from_user.id:
            await callback.answer("Это не ваш заказ", show_alert=True)
            return

        pay = await crud.get_payment_settings(session)
        paid = False

        if order.payment_method == "usdt" and order.payment_amount:
            ts = int(order.created_at.timestamp() * 1000) if order.created_at else None
            paid = await check_usdt_incoming(
                wallet=pay.usdt_trc20_wallet,
                expected_amount=Decimal(str(order.payment_amount)),
                api_key=pay.trongrid_api_key or "",
                min_timestamp_ms=ts,
            )
        elif order.payment_method == "yoomoney":
            paid = await check_operation_by_label(
                token=pay.yoomoney_token or "",
                label=order.external_id or "",
                expected_amount=Decimal(str(order.amount)),
            )

        if not paid:
            await callback.answer("Оплата пока не найдена. Подождите и повторите.", show_alert=True)
            return

        delivered = await deliver_order(session, callback.bot, order_id)

    if delivered:
        await callback.message.edit_text(
            f"✅ Оплата найдена! Заказ #{order_id} выполнен. Товар в чате."
        )
    else:
        await callback.message.edit_text(
            f"⚠️ Оплата найдена, но выдача не удалась. Напишите в поддержку. #{order_id}"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_order_cb(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        order = await crud.get_order(session, order_id)
        if not order or order.user.telegram_id != callback.from_user.id:
            await callback.answer("Недоступно", show_alert=True)
            return
        await crud.cancel_order(session, order_id)

    await callback.message.edit_text(f"❌ Заказ #{order_id} отменён.")
    await callback.answer()
