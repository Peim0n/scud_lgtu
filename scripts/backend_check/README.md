# Пошаговая проверка backend

Простые скрипты для ручной проверки цепочки mTLS:

1. Получение первичного сертификата с KMS (`GET /bootstrap?access_point_id=...`).
2. Обмен первичного сертификата на рабочий (`POST /controller/v1/cert/get`).
3. Проверка получения ключей (`POST /controller/v1/keys/get`) с рабочим сертификатом.
4. Проверка получения списка идентификаторов доступа (`POST /controller/v1/access/get`) с рабочим сертификатом.

> **Важно:** скрипты обращаются к внутренним хостам, поэтому **не используют** системный proxy (`trust_env = False`).

## Запуск

```bash
cd scripts/backend_check
python3 01_fetch_primary.py
python3 02_exchange_working.py
python3 03_get_keys.py
python3 04_get_access.py
```

Результаты и сертификаты сохраняются в `certs/` (в т.ч. `access_response_update0.json` /
`access_response_update1.json` от `04_get_access.py`).

## Переменные окружения

- `KMS_URL` — по умолчанию `https://kms-scud-dev.admlr.lipetsk.ru`
- `ACCESS_POINT_ID` — обязательный query-параметр `/bootstrap`. По умолчанию берётся
  из `app/config.yml` (`backend.access_point_id`) через `_config.py`, сейчас это `2`.
- `USER_AGENT` — заголовок `User-Agent` для всех запросов (к KMS и к controller).
  По умолчанию берётся из `app/config.yml` (`backend.user_agent`) через `_config.py` —
  тот же UA, что реально шлёт приложение (`RestClient`/`CertificateManager`), чтобы
  диагностика проверяла именно то, с чем столкнётся контроллер на WAF.
- `CONTROLLER_URL` — по умолчанию `https://195.34.235.89:8448`
- `OUT_DIR` — по умолчанию `./certs`
- `CN` — Common Name для CSR (по умолчанию `turnstile-test`)
- `UPDATE` — параметр `update` для `/access/get` (`04_get_access.py`). Если не задан —
  скрипт сам проверяет оба режима подряд: `0` (принудительно полный список) и `1`
  (только изменения). Можно задать `UPDATE=0` или `UPDATE=1`, чтобы сделать один запрос.

## Доступ к KMS (WAF по User-Agent + временный allowlist по IP)

`kms-scud-dev.admlr.lipetsk.ru` закрыт WAF-правилом, которое блокирует запросы
с "ботовским" `User-Agent` (в т.ч. дефолтный `python-requests/x.y`) — ответ
`403 Forbidden` от nginx (не JSON-ошибка приложения) **на любом пути**,
включая `/docs/controller`.

Решение — свой чёткий `User-Agent` вместо маскировки под браузер:
`backend.user_agent` в `app/config.yml` (сейчас `LGTU-SCUD-Controller/1.0`),
который используют и `RestClient`/`CertificateManager` в приложении, и эти
скрипты (через `_config.py`). Бэкенд-команда должна внести этот UA в
allowlist WAF на постоянной основе.

С 21.08 наш IP также временно добавлен в allowlist на фаерволе (пока это
правило действует — блокировки по UA не будет в любом случае):
- `213.129.118.19`
- `195.98.93.98`

allowlist могут снять в любой момент, поэтому свой `User-Agent` всё равно
подставляется явно, независимо от него.

С корпоративного прокси (другой исходящий IP, не входит в allowlist) доступа
к KMS нет — поэтому скрипты не используют системный proxy (`trust_env = False`).

## Замеченные особенности реального backend

- `/bootstrap` работает по `GET` и требует обязательный query-параметр `access_point_id`
  (тестовый контроллер — `id=2`).
- **С 21.08 роутинг controller полностью соответствует ТЗ:** единственный метод — `POST`,
  URL вида `/controller/v1/<resource>/<action>`. Старый dev-формат (`GET /controller/v1/keys`,
  `GET /controller/v1/access`, `POST /controller/v1/cert` без `/get`) больше не работает —
  отдаёт `404 неизвестный ресурс`.
  - `POST /controller/v1/cert/get` с `{"csr": "..."}`.
  - `POST /controller/v1/keys/get` — отдаёт ключи (включая `dynamic`).
  - `POST /controller/v1/access/get` — работает, отдаёт реальные идентификаторы
    (`phone`, `maxid` и т.д. в открытом виде, без хеширования на стороне бэкенда — см. ТЗ,
    `TokenTypeEnum` допускает и сырые, и уже хешированные (`*_h`) типы).
  - `POST /controller/v1/accesspoint/get` \| `/patch` — `403 точка доступа не заведена в системе`.
  - `POST /controller/v1/event/get` \| `/put` — `500 внутренняя ошибка сервера`, ещё не готово.
- Документация: `https://kms-scud-dev.admlr.lipetsk.ru/docs/controller`.
