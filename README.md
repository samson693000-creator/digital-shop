# Digital Shop — Telegram-бот + веб-админка

Автопродажа цифровых товаров (aiogram 3) и панель администратора (FastAPI) в киберпанк-стиле. База — SQLite.

## Установка на сервер одной командой

На Ubuntu/Debian/CentOS (нужен root):

```bash
curl -fsSL https://raw.githubusercontent.com/samson693000-creator/digital-shop/main/install.sh | sudo bash
```

Репозиторий: https://github.com/samson693000-creator/digital-shop

Скрипт:
- ставит Python, git
- клонирует проект в `/opt/digital-shop`
- создаёт venv и ставит зависимости
- генерирует `.env` (пароль админа + SECRET_KEY)
- поднимает systemd-сервис `digital-shop` (бот + админка)

Опции:

```bash
curl -fsSL https://raw.githubusercontent.com/samson693000-creator/digital-shop/main/install.sh | sudo bash -s -- --port 8080 --dir /opt/digital-shop
```

После установки откройте админку → **Настройки** → вставьте `BOT_TOKEN` → `systemctl restart digital-shop`.

Обновление (уже установленный сервер):

```bash
curl -fsSL https://raw.githubusercontent.com/samson693000-creator/digital-shop/main/update.sh | sudo bash
```

или локально:

```bash
sudo bash /opt/digital-shop/update.sh
```

Полезные команды:

```bash
systemctl status digital-shop
journalctl -u digital-shop -f
```

## Локальный запуск (Windows / dev)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
copy .env.example .env
python main.py
```

- Админка: http://127.0.0.1:8000  
- Логин/пароль из `.env` (`ADMIN_USERNAME` / `ADMIN_PASSWORD`)

## Возможности

**Бот**
- Каталог: категории → подкатегории → товары
- Автовыдача ключа/текста/ссылки после оплаты
- Оплата: USDT TRC-20, ЮMoney, баланс
- Реферальная программа и личный кабинет

**Админка**
- Товары, категории, пакетная загрузка ключей
- Настройки бота (токен, admin IDs, приветствие)
- Кошельки USDT / ЮMoney, реферальный %
- Заказы, статистика, пользователи

## ЮMoney webhook

`https://YOUR_PUBLIC_DOMAIN/api/yoomoney/notify`

## Структура

```
main.py              # запуск бота + веб
install.sh           # установщик на сервер
update.sh            # обновление
bot/                 # aiogram 3
web/                 # FastAPI + Jinja2
database/            # SQLAlchemy + SQLite
deploy/              # systemd unit
```

## Важно

- Для продакшена смените пароль админа и `SECRET_KEY`, поставьте nginx + HTTPS.
- Курс USDT упрощён (`цена_₽ / 100` + уникальные микродоли) — при необходимости поправьте в `bot/handlers/payment.py`.
