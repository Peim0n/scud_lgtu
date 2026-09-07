# Взаимодействие контроллера LGTU с backend

Этот документ описывает, **что и в каком формате контроллер отправляет бэкенду**, а также какие ответы ожидает. Основа — техническое задание и реализация в `app/infrastructure/backend/`.

## 1. Общие настройки транспорта

- **Протокол**: `HTTPS` + **mTLS** (клиентский сертификат контроллера + CA для проверки сервера).
- **Метод**: только `POST` (кроме bootstrap KMS — см. п. 2).
- **Content-Type**: `application/json; charset=utf-8`.
- **Accept**: `application/json`.
- **User-Agent**: `LGTU-SCUD-Controller/1.0` (задаётся в `config.yml`).
- **Префикс URL**: `/controller/v1`.
- **Полный URL**: `{base_url}/controller/v1/{resource}/{action}`.
- **TCP keepalive** (п. 6.4 ТЗ): `time=300`, `probes=3`, `interval=20`.
- **Timeout запроса**: `10` секунд.
- Прокси из окружения **не используется** (`trust_env=False`).

Код формирования запроса: `app/infrastructure/backend/rest_client.py`.

## 2. Жизненный цикл сертификатов

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

- Первичный сертификат/ключ хранятся **только в оперативной памяти** и удаляются сразу после успешного обмена на рабочий.
- CA сохраняется в `infrastructure/certs/ca.pem` для дальнейших mTLS-вызовов к бэкенду.

Реализация: `app/infrastructure/backend/certificate_manager.py::_fetch_initial_from_kms`.

### 2.2 Обмен первичного на рабочий (и дальнейшая ротация)

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
- Subject CSR совпадает с Subject сертификата, которым аутентифицируется запрос (O, OU, CN).
- Полученный рабочий сертификат атомарно записывается в `infrastructure/certs/working_cert.pem` / `working_key.pem`.
- Ротация запускается, когда остаток срока действия рабочего сертификата становится меньше `rotation_threshold_fraction` (по умолчанию 0.5 от 90 дней = ~45 дней). Повторные попытки не чаще `rotation_retry_interval_days` (по умолчанию 1 день).

Реализация: `app/infrastructure/backend/certificate_manager.py::_exchange_and_activate` и `maybe_rotate`.

## 3. Ключи QR / карт «МИР»

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
      "public": "<ed25519 public key, hex>",
      "shared": "<aes128 shared key, hex>",
      "dynamic": "<hmac key, hex>"
    }
  ]
}
```

- Контроллер хранит до **31 набора** ключей в памяти.
- `public` используется для проверки Ed25519-подписи QR.
- `shared` используется как AES-128 ключ для расшифровки QR.
- `num` — ID набора ключей (1 байт в фрейме QR).
- Синхронизация выполняется раз в сутки (`key_sync_interval_s = 86400`), но при старте — сразу.

Реализация: `app/infrastructure/backend/client.py::get_keys`, `app/application/services/key_sync_service.py`.

## 4. Список доступа

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
- `update: 1` — вернуть список, только если были изменения с прошлого запроса (по ТЗ п. 5.4.3).

### Ответ (полный или изменённый)

```json
{
  "status": "ok",
  "update": 0,
  "dynamic_key": "<32 bytes hex>",
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
  ],
  "users": {
    "123": {
      "phone_h": "<hash>",
      "cardid_h": "<hash>"
    }
  }
}
```

Если изменений нет:

```json
{
  "status": "ok",
  "update": 1
}
```

- `dynamic_key` — дневной ключ HMAC-SHA256 для финального хеширования идентификаторов.
- Допустимые `type` в `id[]`/`users`: `phone`, `phone_h`, `maxid`, `maxid_h`, `cardid`, `cardid_h`.
- Синхронизация выполняется каждые 10 минут (`backend_sync_interval_s = 600`).
- Контроллер хранит список в оперативной памяти; при отсутствии сети работает по последнему полученному кэшу.

Реализация: `app/infrastructure/backend/client.py::get_access_list`, `app/application/services/sync_service.py`, `app/infrastructure/cache/access_cache.py`.

### Хеширование идентификаторов

Формула для raw-идентификаторов (phone, maxid, PAN карты):

```text
HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)
```

- `STATIC_KEY` — уникален для точки доступа, задаётся в `config.yml` (`access.static_key`) и прописывается в Wiegand-считыватели.
- `DYNAMIC_KEY` — ежедневно новый, приходит в `access/get`.
- Для карт «МИР» Wiegand-ридер сам выполняет `SHA256(PAN) + HMAC(STATIC_KEY)` и обрезает до 8 байт; контроллер довычисляет только `HMAC(DYNAMIC_KEY)`.

Реализация: `app/infrastructure/cache/identifier_hash.py`.

## 5. Инвентаризация контроллера

### 5.1 Отправка (accesspoint/patch)

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
- `ip` — локальный IPv4, определяется маршрутом к `8.8.8.8:80` (UDP, без реальной отправки).
- `cpuid` — серийный номер CPU из `/sys/firmware/devicetree/base/serial-number` или `/proc/cpuinfo`, fallback на MAC.

Отправляется сразу после старта и далее раз в сутки (`accesspoint_sync_interval_s = 86400`).

Реализация: `app/application/services/accesspoint_inventory_service.py`.

### 5.2 Запрос (accesspoint/get)

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

Реализация: `app/infrastructure/backend/client.py::get_accesspoint` / `patch_accesspoint`.

## 6. События проходов

### 6.1 Запрос последнего подтверждённого события

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

Используется для сверки локального счётчика `event_id` при первой синхронизации.

### 6.2 Отправка события (event/put)

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
  "description": "Проход in: phone:+79876543210 — pass (raw: https://pass.lipetsk.ru/?...)"
}
```

Поле `ftime` отсутствует, если проход ещё не завершён; при завершении добавляется `ftime`.

**Возможные значения полей:**

| Поле | Значения |
|------|----------|
| `event_type` | `access`, `system`, `firmware`, `security`, `connection` |
| `direction` | `in`, `out` |
| `token_type` | `phone`, `phone_h`, `maxid`, `maxid_h`, `cardid`, `cardid_h` |
| `result` | `pass`, `timeout`, `denied`, `oncoming`, `double`, `forced` |
| `severity` | `fatal`, `critical`, `error`, `warning`, `notice`, `info`, `debug` |

- `event_id` — монотонно возрастающий `uint64` на стороне контроллера, начинается с 1. Обеспечивает идемпотентность: повторная отправка не создаёт дубль.
- При ошибках/офлайне события накапливаются в памяти и отправляются в порядке `event_id`.
- `description` — обязательное поле. Для отказов в description добавляется сырой QR URL или данные карты.

Реализация: `app/infrastructure/backend/client.py::put_event` / `send_events`, `app/infrastructure/persistence/event_store.py`, `app/infrastructure/persistence/event_log.py`.

## 7. Обработка ошибок

### 7.1 Со стороны бэкенда

Если HTTP-код не 200 или `status == "error"`, `RestClient` поднимает `BackendApiError`:

- `400` — невалидный запрос;
- `401` / `403` — проблема с mTLS/сертификатом;
- `404` — ресурс/экшен не найден;
- `500` — внутренняя ошибка бэкенда.

Тело ответа, не являющееся JSON, трактуется как `{"status":"error","description":"<текст ответа>"}`.

### 7.2 Офлайн / недоступность сети

- События не теряются: возвращаются в локальную очередь (`EventStore.requeue`).
- `BackendClient.is_online()` отражает результат последнего вызова.
- `CertificateManager` и `KeySyncService` повторяют попытки с заданными интервалами.
- Список доступа и ключи остаются в памяти; контроллер продолжает пускать по последнему актуальному кэшу.

## 8. Типы событий и их источники внутри контроллера

| Событие | Источник | Что журналируется |
|---------|----------|-------------------|
| QR от Serial-ридера | `SERIAL_DATA` → `QrRead` | `token_type` + `token` + сырой QR URL (`raw_input`) |
| Карта от Wiegand | `CARD_READ` | `token_type=cardid_h` + `card_data` |
| Проход (сенсор) | `INPUT_SIGNAL` → `PassageDetected` | `result=pass`, `ftime` при завершении |
| Отказ в доступе | `AccessDenied` | `result=denied` + сырой QR/карта |
| Тревога / пожар | `ALARM_CHANGED` | `system`/`security` событие |
| Ошибка watchdog | `ERROR` | `system` событие |

## 9. Примечания по production

- `config.yml` содержит `backend.verify_hostname: false` — это **только для dev/тестов по IP**. Для production должно быть `true`.
- Диагностические скрипты `scripts/backend_check/` используют `verify=False` вручную; production-код не делает этого.
- Все криптографические ключи и списки доступа хранятся в оперативной памяти, как требуется ТЗ.
- Рабочий сертификат и CA хранятся на диске (`infrastructure/certs/`); первичный сертификат — только в RAM.

## 10. Ссылки на код

- Формирование HTTP-запросов: `app/infrastructure/backend/rest_client.py`
- Высокоуровневый backend-клиент: `app/infrastructure/backend/client.py`
- Сертификаты и ротация: `app/infrastructure/backend/certificate_manager.py`
- Синхронизация ключей: `app/application/services/key_sync_service.py`
- Синхронизация списков доступа: `app/application/services/sync_service.py`
- Инвентаризация: `app/application/services/accesspoint_inventory_service.py`
- Хранение событий: `app/infrastructure/persistence/event_store.py`, `app/infrastructure/persistence/event_log.py`
- Кэш и хеширование идентификаторов: `app/infrastructure/cache/access_cache.py`, `app/infrastructure/cache/identifier_hash.py`
