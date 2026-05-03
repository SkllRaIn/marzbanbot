# BlayVPN Bot — Деплой и настройка

## Требования

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Nginx (уже установлен с Remnawave)

---

## 1. Создание пользователя и директории

```bash
useradd -r -s /bin/false -d /opt/blayvpn blayvpn
mkdir -p /opt/blayvpn
cp -r /путь/к/проекту/* /opt/blayvpn/
chown -R blayvpn:blayvpn /opt/blayvpn
```

---

## 2. PostgreSQL — создание базы

```bash
sudo -u postgres psql

CREATE USER blayvpn WITH PASSWORD 'ваш_пароль';
CREATE DATABASE blayvpn OWNER blayvpn;
GRANT ALL PRIVILEGES ON DATABASE blayvpn TO blayvpn;
\q
```

---

## 3. Redis (если не установлен)

```bash
apt install redis-server -y
systemctl enable redis
systemctl start redis
```

---

## 4. Python окружение

```bash
cd /opt/blayvpn
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 5. Конфигурация

```bash
cp .env.example .env
nano .env  # заполнить все переменные
```

Обязательно заполнить:
- `BOT_TOKEN_USER` и `BOT_TOKEN_ADMIN` — токены от @BotFather
- `ADMIN_TG_IDS` — ваш Telegram ID
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` — из кабинета YooKassa
- `WEBHOOK_SECRET` — произвольная случайная строка
- `DATABASE_URL` — с паролем от шага 2
- `REQUIRED_CHANNEL_ID` — числовой ID канала (@vpnBlay)

---

## 6. Инициализация базы данных

```bash
cd /opt/blayvpn
source venv/bin/activate
python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())"
```

---

## 7. Nginx — добавить локейшены

```bash
nano /etc/nginx/sites-available/panel.komissarovka.ru
```

Вставить содержимое `nginx.conf.snippet` внутрь блока `server { ... }`.

```bash
nginx -t && systemctl reload nginx
```

---

## 8. Systemd сервис

```bash
cp /opt/blayvpn/blayvpn.service /etc/systemd/system/blayvpn.service
systemctl daemon-reload
systemctl enable blayvpn
systemctl start blayvpn
```

---

## 9. Проверка

```bash
systemctl status blayvpn
journalctl -u blayvpn -f
```

Бот должен вывести:
```
Database initialized.
Redis connected.
Scheduler started.
Webhook server listening on 127.0.0.1:8080
BlayVPN is running.
```

---

## 10. YooKassa — настройка webhook

В личном кабинете YooKassa укажите URL webhook:
```
https://panel.komissarovka.ru/webhook/blayvpn
```

---

## Управление

```bash
# Перезапуск
systemctl restart blayvpn

# Логи в реальном времени
journalctl -u blayvpn -f

# Остановка
systemctl stop blayvpn
```

---

## Структура проекта

```
/opt/blayvpn/
├── bots/
│   ├── launcher.py             # Точка входа — запускает всё
│   ├── shared.py               # Общий модуль для межботовой коммуникации
│   ├── user_bot/
│   │   ├── main.py
│   │   ├── handlers/
│   │   │   ├── start.py        # /start, проверка подписки на канал
│   │   │   ├── profile.py      # Мой профиль, мой ключ
│   │   │   ├── buy.py          # Покупка VPN, промокоды, оплата
│   │   │   ├── referral.py     # Реферальная система
│   │   │   ├── instructions.py # Инструкции по платформам
│   │   │   └── support.py      # Тикеты поддержки
│   │   └── keyboards/
│   └── admin_bot/
│       ├── main.py
│       └── handlers/
│           ├── start.py        # Авторизация с OTP
│           ├── users.py        # Управление пользователями
│           ├── stats.py        # Статистика
│           ├── promocodes.py   # Промокоды + CSV генерация
│           ├── broadcast.py    # Рассылки с остановкой
│           ├── tickets.py      # Тикеты поддержки
│           └── payments.py     # История платежей
├── core/
│   ├── database.py             # SQLAlchemy модели + engine
│   ├── remnawave.py            # Клиент Remnawave API (localhost)
│   ├── yookassa.py             # Клиент YooKassa
│   ├── scheduler.py            # APScheduler задачи
│   └── redis_client.py         # Redis кэш
├── webhook_server.py           # aiohttp сервер для webhook
├── config.py                   # Настройки через pydantic-settings
├── requirements.txt
├── alembic.ini
├── migrations/
├── .env.example
├── blayvpn.service
└── nginx.conf.snippet
```
