# Пошаговая проверка backend

Простые скрипты для ручной проверки цепочки mTLS:

1. Получение первичного сертификата с KMS (`GET /bootstrap`).
2. Обмен первичного сертификата на рабочий (`POST /controller/v1/cert`).
3. Проверка получения ключей (`GET /controller/v1/keys`) с рабочим сертификатом.

> **Важно:** скрипты обращаются к внутренним хостам, поэтому **не используют** системный proxy (`trust_env = False`).

## Запуск

```bash
cd scripts/backend_check
python3 01_fetch_primary.py
python3 02_exchange_working.py
python3 03_get_keys.py
```

Результаты и сертификаты сохраняются в `certs/`.

## Переменные окружения

- `KMS_URL` — по умолчанию `https://kms-scud-dev.admlr.lipetsk.ru`
- `CONTROLLER_URL` — по умолчанию `https://195.34.235.89:8448`
- `OUT_DIR` — по умолчанию `./certs`
- `CN` — Common Name для CSR (по умолчанию `turnstile-test`)

## Замеченные особенности реального backend

- `/bootstrap` работает по `GET`, не `POST`.
- `/controller/v1/cert` принимает `POST` с телом `{"csr": "..."}`.
- `/controller/v1/keys` работает по `GET` (без тела), а не `POST .../keys/get`.
