# Работа с HTTP API

API включается в `config.yml`:

```yaml
api:
  enabled: true
  host: "0.0.0.0"
  port: 8080
```

После запуска `python -m scud_lgtu.app` сервер доступен на `http://<host>:<port>/`.

## Общие правила

- Все endpoint'ы возвращают JSON.
- `GET` — получение состояния.
- `POST` — изменение состояния или выполнение команды.
- В теле POST-запросов передаётся JSON.

## Endpoints

### `GET /health`

Проверка работоспособности движка.

```bash
curl http://localhost:8080/health
```

Ответ:

```json
{
  "healthy": true,
  "running": true
}
```

### `GET /cache`

Просмотр локального кэша доступа.

```bash
curl http://localhost:8080/cache
```

### `GET /events`

Последние 20 событий проходов.

```bash
curl http://localhost:8080/events
```

### `GET /mux/state`

Последнее состояние мультиплексора.

```bash
curl http://localhost:8080/mux/state
```

### `POST /cache/add`

Добавить идентификатор вручную.

```bash
curl -X POST http://localhost:8080/cache/add \
  -H "Content-Type: application/json" \
  -d '{"type": "maxid", "token": "12345", "user_id": 1}'
```

### `POST /cache/remove`

Удалить идентификатор.

```bash
curl -X POST http://localhost:8080/cache/remove \
  -H "Content-Type: application/json" \
  -d '{"type": "maxid", "token": "12345"}'
```

### `POST /qr/generate`

Сгенерировать тестовый QR URL.

```bash
curl -X POST http://localhost:8080/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"max_id": 12345, "key_id": 167, "timestamp": 1752510000, "keys_dir": "key"}'
```

### `POST /command/open`

Открыть турникет.

```bash
curl -X POST http://localhost:8080/command/open
```

### `POST /command/shift`

Записать значение в сдвиговый регистр.

```bash
curl -X POST http://localhost:8080/command/shift \
  -H "Content-Type: application/json" \
  -d '{"value": 1}'
```

## Примеры сценариев

### Проверка и открытие

```bash
curl http://localhost:8080/health
curl -X POST http://localhost:8080/command/open
```

### Добавить пользователя и сгенерировать QR

```bash
curl -X POST http://localhost:8080/cache/add \
  -H "Content-Type: application/json" \
  -d '{"type": "maxid", "token": "12345", "user_id": 1}'

curl -X POST http://localhost:8080/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"max_id": 12345, "key_id": 167}'
```

### Мониторинг мультиплексора

```bash
watch -n 0.5 'curl -s http://localhost:8080/mux/state | python -m json.tool'
```
