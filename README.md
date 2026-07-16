# СКУД ЛГТУ

Модульный контроллер доступа для системы СКУД ЛГТУ.

## Структура проекта

- `scud_lgtu/` — основной пакет приложения
  - `engine.py` — управление GPIO, потоками, watchdog
  - `access_controller.py` — бизнес-логика доступа
  - `api_server.py` — HTTP API для тестирования
  - `qr_encoder.py`, `qr_decoder.py` — работа с QR-кодами
  - `local_access_cache.py`, `event_store.py`, `backend_client.py` — хранение и связь
  - `config.py`, `config.yml` — централизованная конфигурация
- `scripts/` — вспомогательные скрипты (`generate_qr.py`, `manage_access.py`)
- `tests/` — юнит-тесты
- `key/` — ключи для QR-кодов
- `old/` — архивные/устаревшие модули

## Конфигурация

Все тайминги, ключи, логирование и параметры API настраиваются в `config.yml`:

```yaml
access:
  static_key: "..."
  dynamic_key: "..."

timings:
  auth_timeout_s: 5.0
  watchdog_check_interval_s: 2.0
  ...

logging:
  level: INFO
  format: "%(asctime)s %(name)s [%(levelname)s] %(message)s"

api:
  enabled: true
  host: "0.0.0.0"
  port: 8080
```

## Запуск

```bash
python -m scud_lgtu.app
```

## HTTP API

При включённом `api.enabled` запускается HTTP API:

- `GET /health` — состояние системы
- `GET /cache` — содержимое локального кэша
- `GET /events` — последние события
- `POST /cache/add` — добавить идентификатор
- `POST /cache/remove` — удалить идентификатор
- `POST /qr/generate` — сгенерировать тестовый QR
- `POST /command/open` — открыть турникет
- `POST /command/shift` — записать сдвиговый регистр

## Тестирование

```bash
python -m unittest discover -s tests
```
