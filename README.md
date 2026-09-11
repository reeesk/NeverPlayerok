# NeverBoost Playerok Bot

Самостоятельное ядро бота для продавца Playerok. Покупатели отправляют Discord-инвайт в чат сделки, а бот передаёт заказ в `https://api.neverboost.com` с API-ключом продавца.

## Статус

Уже реализованы:

- JSON-хранилище заказов без базы данных;
- защита от повторной обработки оплаченной сделки;
- извлечение `discord.gg/...` и `discord.com/invite/...`;
- передача проверки инвайта в NeverBoost API;
- обработка причин `invalid_invite`, `limited_invite`, `join_request_enabled`, `age_restricted`, `lookup_failed`;
- polling финального статуса заказа;
- отдельный интерфейс адаптера Playerok;
- восстановление проданных и истёкших лотов;
- автоматическое поднятие товаров;
- автоотправка сделки после успешной выдачи;
- уведомления администраторам;
- загрузка Universal-style Python-плагинов.

## Совместимые плагины

Бот загружает Python-плагины из папки `plugins`. Поддерживаются Universal-подобные метаданные `NAME`, `VERSION`, `DESCRIPTION`, а также словари `PLAYEROK_EVENT_HANDLERS` или `EVENT_HANDLERS`. Обработчики можно объявлять ключами `NEW_DEAL`, `NEW_MESSAGE` и другими строковыми событиями.

Настройки продавца задаются через installer и хранятся в `data/config.json`: cookies и User-Agent Playerok, прокси, API-ключ NeverBoost, Telegram, JSON-привязки лотов, путь к JSON-хранилищу, URL API и интервалы автоматизации. Это покрывает основные настройки, нужные для авто-выдачи, без отдельной базы данных.

Плагины запускаются в том же процессе, поэтому устанавливайте только проверенный исходный код. Плагины Universal, которые импортируют `core`, `tgbot` или конкретный singleton Universal, не являются полностью переносимыми без адаптера.

В репозитории используется локальный неофициальный `playerokapi`. Listener подключается в `app/main.py` и обрабатывает `NEW_DEAL`, `NEW_MESSAGE`, `ITEM_PAID` и `DEAL_STATUS_CHANGED`.

## Установка

На Windows запустите `install.bat`. Wizard создаст `.venv`, установит зависимости и сохранит настройки в `data/config.json`.

Установщик отдельно ставит `wrapper-tls-requests`, который нужен локальному `playerokapi` для импорта `tls_requests`.

Можно также запустить мастер вручную:

```powershell
python installer.py
```

Поддерживаются Playerok HTTP/HTTPS/SOCKS-прокси в формате `scheme://user:password@host:port`. Настройки прокси сохраняются в JSON и передаются в Playerok-клиент.

## Telegram-панель

В installer укажите токен бота и Telegram ID администраторов. После запуска доступны:

- `/start` — удобное inline-меню;
- `/set_key API_KEY` — смена NeverBoost-ключа;
- `/add_lot ITEM_ID oneMonth 2` — привязка лота;
- `/toggle auto_restore on` — включение функции.

В меню есть статус заказов, баланс и сток NeverBoost, список лотов, последние заказы и переключатели функций.

## Запуск

1. Запустите `install.bat`.
2. Заполните данные в консольном wizard.
3. Запустите `start.bat`.
4. Для проверки выполните `python -m pytest -q`.

Не публикуйте `.env`, cookies или API-ключ.
