# HTTP API для тестирования

API запускается автоматически, если `api.enabled: true` в `config.yml`.

## Endpoints

### `GET /health`

Проверка состояния движка.

```json
{
  "healthy": true,
  "running": true
}
```

### `GET /cache`

Содержимое локального кэша разрешённых идентификаторов.

### `GET /events`

Последние 20 событий проходов.

### `GET /mux/state`

Последнее состояние мультиплексора, полученное от MuxWorker.

```json
{
  "mux_state": {
    "{'PA6': 0, 'PA11': 0, 'PA12': 0}": 0,
    "{'PA6': 0, 'PA11': 0, 'PA12': 1}": 0,
    ...
  }
}
```

### `POST /cache/add`

Добавить идентификатор в локальный кэш.

```json
{
  "type": "maxid",
  "token": "12345",
  "user_id": 1
}
```

### `POST /cache/remove`

Удалить идентификатор из локального кэша.

```json
{
  "type": "maxid",
  "token": "12345"
}
```

### `POST /qr/generate`

Сгенерировать тестовый QR URL.

```json
{
  "max_id": 12345,
  "key_id": 167,
  "timestamp": 1752510000,
  "keys_dir": "key"
}
```

### `POST /command/open`

Открыть турникет.

### `POST /command/shift`

Записать значение в сдвиговый регистр.

```json
{
  "value": 1
}
```

## Примеры

```bash
# Проверка состояния
curl http://localhost:8080/health

# Добавить идентификатор
curl -X POST http://localhost:8080/cache/add \
  -H "Content-Type: application/json" \
  -d '{"type": "maxid", "token": "12345"}'

# Сгенерировать QR
curl -X POST http://localhost:8080/qr/generate \
  -H "Content-Type: application/json" \
  -d '{"max_id": 12345, "key_id": 167}'
```
