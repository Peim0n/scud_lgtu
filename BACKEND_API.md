# Взаимодействие контроллера LGTU с backend

Этот документ — спецификация исходящего трафика контроллера к backend'у.
Описаны все endpoint'ы ветви `controller`, форматы JSON-запросов и ответов,
правила формирования событий, хеширования идентификаторов и поведение при
сбоях. Основа — техническое задание v4 (разделы 5.4–6.5) и реализация в
`app/infrastructure/backend/`.

## 1. Общий транспорт

| Параметр | Значение |
|----------|----------|
| Протокол | `HTTPS` + **mTLS** |
| Метод ветви `controller` | `POST` |
| Content-Type | `application/json; charset=utf-8` |
| Accept | `application/json` |
| User-Agent | задаётся в `config.yml`, по умолчанию `LGTU-SCUD-Controller/1.0` |
| URL | `https://{base_url}/controller/v1/{resource}/{action}` |
| Таймаут запроса | `10` секунд (`backend.request_timeout_s`) |
| TCP keepalive | `time=300`, `probes=3`, `interval=20` |
| Прокси из env | **не используется** (`trust_env=False`) |

Код: `app/infrastructure/backend/rest_client.py`,
`app/infrastructure/backend/client.py`.

## 2. Жизненный цикл mTLS-сертификатов

### 2.1 Получение первичного сертификата (KMS bootstrap)

Выполняется **один раз** при первом запуске, если нет рабочего сертификата.

```http
GET https://{kms_url}/bootstrap?access_point_id={id}
Accept: application/json
User-Agent: LGTU-SCUD-Controller/1.0
```

**Ожидаемый ответ (200 OK, JSON):**

```json
{
  "bootstrap": {
    "crt": "-----BEGIN CERTIFICATE-----\n...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n..."
  },
  "ca": {
    "crt": "-----BEGIN CERTIFICATE-----\n..."
  }
}
```

- Первичный сертификат/ключ хранятся **только в оперативной памяти** и
  удаляются сразу после успешного обмена на рабочий.
- CA сохраняется в `infrastructure/certs/ca.pem` для последующих mTLS-вызовов.
- Поддерживается также старый «плоский» формат `{"cert":..., "key":...}`.

Реализация: `app/infrastructure/backend/certificate_manager.py::_fetch_initial_from_kms`.

### 2.2 Обмен первичного/рабочего сертификата

```http
POST https://{base_url}/controller/v1/cert/get
Content-Type: application/json

{"csr": "-----BEGIN CERTIFICATE REQUEST-----\n..."}
```

**Ответ (200 OK, JSON):**

```json
{
  "status": "ok",
  "crt": "-----BEGIN CERTIFICATE-----\n..."
}
```

- Контроллер генерирует новую RSA-2048 ключевую пару и CSR.
- Subject CSR совпадает с Subject текущего сертификата (initial или working).
- Рабочий сертификат атомарно записывается в `working_cert.pem` / `working_key.pem`.
- Срок действия рабочего сертификата — 90 суток.
- Ротация запускается, когда остаток срока становится меньше
  `rotation_threshold_fraction` (по умолчанию 0.5 от 90 дней ≈ 45 дней).
- Повторные попытки ротации не чаще `rotation_retry_interval_days`
  (по умолчанию 1 сутки).

Реализация: `app/infrastructure/backend/certificate_manager.py::_exchange_and_activate`,
`maybe_rotate`.

## 3. Сводка endpoint'ов ветви `controller`

| Ресурс | Действие | Тело запроса | Назначение |
|--------|----------|--------------|------------|
| `keys` | `get` | `null` | Получить ключи QR/карт «МИР» |
| `cert` | `get` | `{"csr": "..."}` | Обменять CSR на рабочий сертификат |
| `access` | `get` | `{"update": 0\|1}` | Получить список доступа |
| `accesspoint` | `get` | `null` | Запросить данные точки доступа |
| `accesspoint` | `patch` | `{"mac", "ip", "cpuid"}` | Отправить инвентаризацию |
| `event` | `get` | `null` | Получить последнее подтверждённое событие |
| `event` | `put` | объект события | Отправить одно событие |

## 4. Ключи QR / карт «МИР» — `keys/get`

### Запрос

```http
POST https://{base_url}/controller/v1/keys/get
Content-Type: application/json

null
```

### Ответ

```json
{
  "status": "ok",
  "quantity": 28,
  "keys": [
    {
      "num": 145,
      "public": "<ed25519 public key, hex 64 chars>",
      "shared": "<aes128 shared key, hex 32 chars>",
      "dynamic": "<hmac key, hex>"
    }
  ]
}
```

- `public` — публичный ключ Ed25519 для проверки подписи QR.
- `shared` — общий ключ AES-128 для расшифровки QR.
- `num` — ID набора ключей (1 байт в фрейме QR).
- `dynamic` — динамический ключ HMAC, передаётся бэкендом, но для QR/cards
  используется в основном на стороне backend/мобильного приложения.
- Контроллер хранит до **31 набора** ключей в оперативной памяти.
- Синхронизация выполняется раз в сутки, при старте — сразу.

Реализация: `app/infrastructure/backend/client.py::get_keys`,
`app/application/services/key_sync_service.py`.

## 5. Список доступа — `access/get`

### Запрос

```http
POST https://{base_url}/controller/v1/access/get
Content-Type: application/json

{"update": 0}
```

или

```json
{"update": 1}
```

- `update: 0` — принудительно запросить полный список.
- `update: 1` — вернуть список, только если были изменения с прошлого запроса
  (п. 5.4.3 ТЗ).
- Первый запрос после старта контроллера всегда выполняется с `update: 0`.

### Ответ (полный список)

```json
{
  "status": "ok",
  "update": 0,
  "dynamic_key": "0123456789abcdef0123456789abcdef",
  "id": [
    {
      "type": "phone_h",
      "quantity": 5,
      "list": ["<hash>", "..."]
    },
    {
      "type": "cardid_h",
      "quantity": 3,
      "list": ["<hash>", "..."]
    }
  ]
}
```

### Ответ (изменений нет)

```json
{
  "status": "ok",
  "update": 1
}
```

- `dynamic_key` — дневной ключ HMAC-SHA256 для финального хеширования
  идентификаторов (hex, 32 байта).
- Допустимые `type` в `id[]`: `phone`, `phone_h`, `maxid`, `maxid_h`,
  `cardid`, `cardid_h`.
- Синхронизация выполняется каждые 10 минут
  (`backend_sync_interval_s = 600`).
- Контроллер хранит список в оперативной памяти; при отсутствии сети работает
  по последнему полученному кэшу.
- **Контроллер не получает и не отправляет `user_id`.** Соответствие
  идентификатора и пользователя хранится только на backend'е.

Реализация: `app/infrastructure/backend/client.py::get_access_list`,
`app/application/services/sync_service.py`,
`app/infrastructure/cache/access_cache.py`.

### Хеширование идентификаторов

Для raw-идентификаторов (phone, maxid, PAN карты):

```text
HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)
```

- `STATIC_KEY` — уникален для точки доступа, задаётся в `config.yml`
  (`access.static_key`) и прописывается в Wiegand-считыватели.
- `DYNAMIC_KEY` — ежедневно новый, приходит в `access/get`.
- Для карт «МИР» Wiegand-ридер сам выполняет `SHA256(PAN) + HMAC(STATIC_KEY)`
  и обрезает до 8 байт; контроллер довычисляет только финальный
  `HMAC(DYNAMIC_KEY)`.

Реализация: `app/infrastructure/cache/identifier_hash.py`.

## 6. Инвентаризация контроллера — `accesspoint`

### 6.1 `accesspoint/patch`

```http
POST https://{base_url}/controller/v1/accesspoint/patch
Content-Type: application/json

{
  "mac": "02:81:a6:72:4e:c0",
  "ip": "192.168.0.181",
  "cpuid": "02c00081a6724ec0"
}
```

- `mac` — MAC-адрес сетевого интерфейса, нижний регистр, через `:`.
- `ip` — локальный IPv4, определяется маршрутом к `8.8.8.8:80`
  (UDP, без реальной отправки).
- `cpuid` — серийный номер CPU из `/sys/firmware/devicetree/base/serial-number`
  или `/proc/cpuinfo`, fallback на MAC.

Отправляется **сразу после первого успешного онлайн-подключения** и далее
раз в сутки (`accesspoint_sync_interval_s = 86400`). Если backend недоступен,
запрос пропускается до следующего цикла.

### 6.2 `accesspoint/get`

```http
POST https://{base_url}/controller/v1/accesspoint/get
Content-Type: application/json

null
```

**Ответ:**

```json
{
  "status": "ok",
  "mac": "02:81:a6:72:4e:c0",
  "ip": "192.168.0.181",
  "cpuid": "02c00081a6724ec0"
}
```

Реализация: `app/infrastructure/backend/client.py::get_accesspoint` /
`patch_accesspoint`,
`app/application/services/accesspoint_inventory_service.py`.

## 7. События проходов — `event`

### 7.1 `event/get`

```http
POST https://{base_url}/controller/v1/event/get
Content-Type: application/json

null
```

**Ответ:**

```json
{
  "status": "ok",
  "event_id": 42,
  "stime": "2025-09-07T12:34:56+03:00",
  "ftime": "2025-09-07T12:35:01+03:00"
}
```

Используется при первой синхронизации для раннего обнаружения разрыва
локального счётчика `event_id`.

Реализация: `app/infrastructure/backend/client.py::get_last_event`,
`app/application/services/sync_service.py::_reconcile_events`.

### 7.2 `event/put`

Каждое событие отправляется **отдельным запросом** (не batch).

```http
POST https://{base_url}/controller/v1/event/put
Content-Type: application/json

{
  "event_id": 123,
  "stime": "2025-09-07T12:34:56.123456+03:00",
  "ftime": null,
  "event_type": "access",
  "direction": "in",
  "token_type": "phone",
  "token": "+79876543210",
  "result": "pass",
  "severity": "info",
  "description": "Проход in: phone:+79876543210 — pass"
}
```

#### Поля события

| Поле | Обязательное | Описание | Допустимые значения |
|------|--------------|----------|---------------------|
| `event_id` | да | uint64, монотонно возрастающий счётчик на контроллере, начинается с 1 | `1..2^64-1` |
| `stime` | да | Время начала события, ISO 8601 с timezone | например `2025-09-07T12:34:56.123456+03:00` |
| `ftime` | нет | Время окончания события, ISO 8601 с timezone | добавляется при завершении прохода |
| `event_type` | да | Тип события | `access`, `system`, `firmware`, `security`, `connection` |
| `direction` | нет* | Запрошенное направление прохода | `in`, `out` |
| `token_type` | нет* | Тип идентификатора | `phone`, `phone_h`, `maxid`, `maxid_h`, `cardid`, `cardid_h` |
| `token` | нет* | Значение идентификатора | строка |
| `result` | нет* | Результат прохода | `pass`, `timeout`, `denied`, `oncoming`, `double`, `forced` |
| `severity` | да | Важность | `fatal`, `critical`, `error`, `warning`, `notice`, `info`, `debug` |
| `description` | да | Человекочитаемое описание | строка |

\* Для `event_type=access` поля `direction`, `token_type`, `token`, `result`
заполняются. Для системных событий они могут отсутствовать или быть пустыми.

#### Форматы значений

- `event_id` — идемпотентность: повторная отправка того же `event_id`
  не создаёт дубль на backend'е.
- `stime`/`ftime` формируются через
  `datetime.fromtimestamp(t).astimezone().isoformat()`:
  содержат дату, время, микросекунды и локальный offset.
- При ошибках/офлайне события накапливаются в памяти и отправляются в порядке
  `event_id`.

#### Примеры `description`

- Успешный проход:
  `Проход in: maxid:103295689 — pass`
- Отказ (неизвестный QR):
  `Доступ out: maxid:103295689 — denied (raw: https://pass.lipetsk.ru/?...)`
- Системное событие watchdog:
  `[watchdog] Serial reader thread died`

### 7.3 Как события попадают в `event/put`

| Источник в контроллере | `event_type` | `result` | Примечание |
|------------------------|--------------|----------|------------|
| QR от Serial-ридера | `access` | `denied` / `pass` | `description` содержит сырой QR URL при отказе |
| Карта от Wiegand | `access` | `denied` / `pass` | `token_type=cardid_h` |
| Сенсор прохода | `access` | `pass` | `ftime` добавляется при завершении |
| Тревога / пожар | `system`/`security` | — | если журналируется |
| Ошибка watchdog | `system` | — | `severity=critical` |

Реализация: `app/infrastructure/backend/client.py::put_event` / `send_events`,
`app/infrastructure/persistence/event_store.py`,
`app/infrastructure/persistence/event_log.py`,
`app/application/lgtu_application.py`.

## 8. Обработка ошибок

### 8.1 Ответы backend'а

Если HTTP-код не 200 или `status == "error"`, `RestClient` поднимает
`BackendApiError`:

- `400` — невалидный запрос;
- `401` / `403` — проблема с mTLS/сертификатом;
- `404` — ресурс/экшен не найден;
- `405` — метод не разрешён;
- `500` — внутренняя ошибка backend'а.

Тело ответа, не являющееся JSON, трактуется как
`{"status":"error","description":"<текст ответа>"}` (п. 6.1 ТЗ).

### 8.2 Офлайн / недоступность сети

- События не теряются: возвращаются в локальную очередь (`EventStore.requeue`).
- `BackendClient.is_online()` отражает результат последнего вызова.
- `CertificateManager` и `KeySyncService` повторяют попытки с заданными
  интервалами.
- Список доступа и ключи остаются в памяти; контроллер продолжает пускать по
  последнему актуальному кэшу.
- Инвентаризация `accesspoint/patch` пропускается, пока backend недоступен.

## 9. Примечания по production

- `config.yml` содержит `backend.verify_hostname: false` — это **только для
  dev/тестов по IP**. Для production должно быть `true`.
- Диагностические скрипты `scripts/backend_check/` используют `verify=False`
  вручную; production-код не делает этого.
- Все криптографические ключи и списки доступа хранятся в оперативной памяти,
  как требуется ТЗ.
- Рабочий сертификат и CA хранятся на диске (`infrastructure/certs/`);
  первичный сертификат — только в RAM.
- Контроллер **не отправляет `user_id`** в событиях: `access/get` по ТЗ не
  возвращает `user_id`, поэтому это поле отсутствует во всех исходящих
  запросах.

## 10. Ссылки на код

- Формирование HTTP-запросов: `app/infrastructure/backend/rest_client.py`
- Высокоуровневый backend-клиент: `app/infrastructure/backend/client.py`
- Сертификаты и ротация: `app/infrastructure/backend/certificate_manager.py`
- Синхронизация ключей: `app/application/services/key_sync_service.py`
- Синхронизация списков доступа: `app/application/services/sync_service.py`
- Инвентаризация: `app/application/services/accesspoint_inventory_service.py`
- Хранение событий: `app/infrastructure/persistence/event_store.py`,
  `app/infrastructure/persistence/event_log.py`
- Кэш и хеширование идентификаторов: `app/infrastructure/cache/access_cache.py`,
  `app/infrastructure/cache/identifier_hash.py`
- Преобразование событий устройства в backend-события:
  `app/application/lgtu_application.py`
