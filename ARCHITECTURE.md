# Архитектура LGTU Controller

LGTU Controller — это система контроля доступа (СКУД) для Orange Pi Zero LTS, построенная на принципах **Clean Architecture** с разделением на доменный, прикладной и инфраструктурный слои. Проект использует `gpiod` и `threading` для работы с GPIO, Wiegand-считывателями, последовательными портами, мультиплексорами и сдвиговыми регистрами.

## Общие принципы

- **Разделение слоёв**: доменный слой не зависит от инфраструктуры; инфраструктура адаптируется через адаптеры.
- **Событийная архитектура**: события от оборудования преобразуются в доменные события и обрабатываются в `LGTUApplication`.
- **Потокобезопасность**: hardware-модули работают в отдельных потоках и передают данные через `queue.Queue`.
- **Офлайн-режим**: in-memory кэш списка доступа позволяет работать при отсутствии связи с бэкендом (данные загружаются заново после перезагрузки).
- **Конфигурация через YAML**: `app/config.yml` задаёт пины, тайминги, устройства и параметры бэкенда.

## Структура слоёв

```
┌─────────────────────────────────────────────────────┐
│  Interfaces  │ run_lgtu_controller.py, interfaces/cli│
├─────────────────────────────────────────────────────┤
│ Application  │ LGTUApplication, services             │
├─────────────────────────────────────────────────────┤
│    Domain    │ models, enums, events,                │
│              │ access services                       │
├─────────────────────────────────────────────────────┤
│ Infrastructure│ ScudEngine, firmware, cache,         │
│              │ persistence, backend, sound           │
└─────────────────────────────────────────────────────┘
```

---

## 1. Доменный слой (`app/domain/`)

Содержит бизнес-логику и сущности, независимые от оборудования.

### 1.1. Domain (`app/domain/`)

| Модуль | Назначение |
|--------|------------|
| `enums.py` | Перечисления: `DirectionEnum`, `TokenTypeEnum`, `ResultEnum`, `SeverityEnum`, `EventTypeEnum` |
| `models.py` | Доменные модели: `Credential`, `AccessDecision`, `AuthSession`, `Passage`, `OutputCommand` |
| `events.py` | Доменные события: `CardRead`, `QrRead`, `ButtonPressed`, `AlarmChanged`, `PassageDetected` |
| `access.py` | `AccessPolicy` (проверка доступа), `PassageTracker` |

### 1.2. Турникет (`app/infrastructure/devices/turnstile/`)

| Модуль | Назначение |
|--------|------------|
| `turnstile_device.py` | FSM турникета: обработка `AccessGranted`/`AccessDenied`/`PassageDetected`/`AlarmChanged`/`DeviceCommand` и генерация `Command`. Режимы: idle, entry_open, exit_open, unlocked_entry, unlocked_exit, blocked, alarm |
| `commands.py` | Асинхронные команды: `OpenEntryCommand`, `OpenExitCommand`, `UnlockEntryCommand`, `UnlockExitCommand`, `CloseCommand`, `LockCommand`, `UnlockCommand`, `AlarmCommand`, `ClearAlarmCommand`, `DenyCommand` |

---

## 2. Прикладной слой (`app/application/`)

Связывает инфраструктуру и доменную логику.

### 2.1. Оркестрация

| Модуль | Назначение |
|--------|------------|
| `lgtu_application.py` | `LGTUApplication` — чтение `ScudEvent`, преобразование в доменные события, запуск команд устройства |

### 2.2. Команды приложения

| Модуль | Назначение |
|--------|------------|
| `commands.py` | `CommandAction`, `CommandTarget`, `ScudCommand` — типы команд |

### 2.3. Сервисы приложения (`app/application/services/`)

| Модуль | Назначение |
|--------|------------|
| `passage_service.py` | Журналирование проходов |
| `sync_service.py` | Синхронизация событий и списка доступа с бэкендом |
| `key_sync_service.py` | Синхронизация ключей QR-кодов (загрузка в память через QRDecoder) |
| `accesspoint_inventory_service.py` | Инвентаризация точки доступа (accesspoint/patch) |

---

## 3. Инфраструктурный слой (`app/infrastructure/`)

Адаптеры оборудования и внешних систем.

### 3.1. Ядро

| Модуль | Назначение |
|--------|------------|
| `engine.py` | `ScudEngine` — главный оркестратор hardware: запуск потоков, мосты очередей, watchdog |

### 3.2. GPIO (`app/infrastructure/firmware/gpio/`)

| Модуль | Назначение |
|--------|------------|
| `firmware/gpio/controller.py` | `GpiodPinController` и `PinControllerThread`: управление пинами, мультиплексором и сдвиговым регистром |
| `firmware/gpio/multiplexor.py` | `Multiplexer` и `MuxEventMapper` — опрос входов и генерация событий |
| `firmware/gpio/shift_register.py` | `ShiftRegister` — вывод битовой маски в сдвиговый регистр |
| `firmware/gpio/signal_reader.py` | Чтение сигналов с GPIO |
| `firmware/gpio/actuator.py` | `ShiftRegisterActuator` — адаптер `Actuator` для сдвигового регистра |
| `firmware/gpio/wiegand_reader.py` | `WiegandReader` — чтение карт по Wiegand-интерфейсу |

### 3.3. Serial (`app/infrastructure/firmware/serial/`)

| Модуль | Назначение |
|--------|------------|
| `firmware/serial/serial_reader.py` | `BackgroundSerialReader` — фоновое чтение из Serial-порта |
| `firmware/serial/qr_decoder.py` | `QRDecoder` — декодирование URL QR-кодов с проверкой подписи |

### 3.4. Кэш и хранение (in-memory)

Все данные хранятся **только в оперативной памяти** — на SD-карту ничего не пишется (кроме mTLS-сертификатов). При перезагрузке данные загружаются заново с бэкенда.

| Модуль | Назначение |
|--------|------------|
| `cache/access_cache.py` | `LocalAccessCache` — in-memory кэш списка доступа |
| `cache/repository.py` | `AccessRepositoryAdapter` — адаптер `AccessRepository` |
| `cache/identifier_hash.py` | Хеширование идентификаторов |
| `persistence/event_store.py` | `EventStore` — in-memory очередь событий для отправки на бэкенд |
| `persistence/event_log.py` | `EventLogAdapter` — адаптер журналирования |

### 3.5. Бэкенд

| Модуль | Назначение |
|--------|------------|
| `backend/rest_client.py` | `RestClient` — низкоуровневый REST-клиент (HTTPS + mTLS, TCP keepalive) |
| `backend/client.py` | `BackendClient` — бизнес-операции (ключи, списки доступа, события) |
| `backend/certificate_manager.py` | `CertificateManager` — управление mTLS-сертификатами (генерация, ротация) |
| `backend/gateway.py` | `BackendGatewayAdapter` — адаптер шлюза бэкенда |

### 3.6. Звук

| Модуль | Назначение |
|--------|------------|
| `sound/player.py` | `SoundPlayer` — неблокирующий проигрыватель звуковых эффектов |
| `sound/output.py` | `SoundOutputAdapter` — адаптер звукового выхода |

### 3.7. Устройства (`app/infrastructure/devices/turnstile/`)

| Модуль | Назначение |
|--------|------------|
| `turnstile_device.py` | `TurnstileDevice` — FSM турникета (режимы: idle, entry_open, exit_open, unlocked_entry, unlocked_exit, blocked, alarm) |
| `commands.py` | Асинхронные команды: `OpenEntryCommand`, `OpenExitCommand`, `UnlockEntryCommand`, `UnlockExitCommand`, `CloseCommand`, `LockCommand`, `UnlockCommand`, `AlarmCommand`, `ClearAlarmCommand`, `DenyCommand` |

### 3.8. Конфигурация и загрузка

| Модуль | Назначение |
|--------|------------|
| `config/config_loader.py` | Загрузка `config.yml` |
| `config/module_resolver.py` | `ModuleResolver` — разрешение имён пинов/таймингов по конфигурации |

### 3.9. Загрузка приложения

| Модуль | Назначение |
|--------|------------|
| `bootstrap.py` | `build_application()` — сборка всех компонентов и внедрение зависимостей |

---

## 4. Точки входа (`app/interfaces/`, корневые скрипты)

| Файл | Назначение |
|------|------------|
| `interfaces/cli.py` | Командный интерфейс для управления и диагностики |
| `run_lgtu_controller.py` | Запуск реального контроллера |

---

## 5. Поток данных

### 5.1. Чтение карты Wiegand

```
[WiegandReader] → ScudEvent(CARD_READ) → LGTUApplication → CardRead
                                                                     ↓
                                                    _to_device_event → TurnstileDevice
                                                                     ↓
                                              Command → _CommandRunner → ShiftRegisterActuator → ScudEngine → GPIO
```

### 5.2. Чтение QR через Serial

```
[BackgroundSerialReader] → ScudEvent(SERIAL_DATA) → LGTUApplication (QRDecoder) → QrRead
```

### 5.3. Кнопки и тревога

```
[Multiplexer] → ScudEngine → ScudEvent(BUTTON_PRESSED / ALARM_CHANGED) → LGTUApplication
                                                ↓
                              ButtonPressed / AlarmChanged → _to_device_event
```

### 5.4. Датчики прохода

```
[Multiplexer] → ScudEngine (MuxEventMapper) → ScudEvent(INPUT_SIGNAL) → LGTUApplication → PassageDetected
                                              ↓
                                              _to_device_event → TurnstileDevice
```

---

## 6. Очереди и потоки

| Очередь | Производитель | Потребитель | Тип данных |
|---------|---------------|-------------|------------|
| `WiegandReader.output_queue` | `WiegandReader` | `ScudEngine._wiegand_queue_loop` | `CardData` |
| Serial `queue` | `BackgroundSerialReader` | `ScudEngine._serial_queue_loop` | `str` |
| `Multiplexer.output_queue` | `Multiplexer` | `PinControllerThread._mux_loop` | `dict[str, int]` |
| `mux_queue` | `PinControllerThread` | `ScudEngine._mux_queue_loop` | `dict[str, int]` |
| `shift_queue` | `PinControllerThread` | `ShiftRegister` | `int` (битовая маска) |
| `event_queue` | `ScudEngine` | `LGTUApplication` | `ScudEvent` |

---

## 7. Конфигурация

Основной файл — `app/config.yml`. Ключевые секции:

- `gpiod` — пины GPIO: mux, shift, wiegand.
- `mux.inputs` — имена входов мультиплексора.
- `shift_register.pins` — имена выходов сдвигового регистра.
- `timings` — таймауты прохода, Wiegand, синхронизации, очередей, `command_stop_timeout_s`, `open_beep_duration_s`.
- `backend` — `base_url`, `api_path_prefix`, `tcp_keepalive_time_s`/`probes`/`intvl_s`, `request_timeout_s`, `cert` (включая `rsa_key_size`).
- `qr_decoder` — `base_url` (базовый URL QR-кодов).
- `sound` — `sound_dir`, `player_cmd`, `stop_timeout_s`, `play_timeout_s`.
- `devices` — конфигурация кнопок, считывателей, маппинги.
- `logging` — уровни логирования по каждому модулю индивидуально (20 модулей).

---

## 8. Тестирование

| Файл/папка | Назначение |
|------------|------------|
| `tests/test_bootstrap.py` | Проверка сборки приложения и DI |
| `tests/test_config.py` | Проверка загрузки и валидации конфигурации |
| `tests/test_turnstile_fsm.py` | Тесты FSM турникета (все переходы состояний) |
| `tests/test_qr_decoder.py` | Тесты QR-кодирования/декодирования |
| `tests/test_backend_rest_client.py` | Тесты REST-клиента |
| `tests/test_backend_client.py` | Тесты бизнес-клиента бэкенда |
| `tests/test_certificate_manager.py` | Тесты управления сертификатами |
| `tests/test_sync_service.py` | Тесты синхронизации с бэкендом |
| `tests/test_key_sync_service.py` | Тесты синхронизации ключей |
| `tests/test_accesspoint_inventory_service.py` | Тесты инвентаризации |
| `tests/test_identifier_hash.py` | Тесты хеширования идентификаторов |
| `tests/test_event_store_persistence.py` | Тесты in-memory хранилища событий |
| `tests/test_watchdog.py` | Тесты watchdog |
| `tests/mocks/` | Моки: `MockEngine`, `MockGPIO`, `MockSerial`, `MockWiegand` |

Запуск тестов:
```bash
pytest app/tests/ -v --ignore=app/tests/test_backend_integration.py
```

---

## 9. Соглашения по коду

- **Docstrings**: оформлены на русском языке в формате reStructuredText (Sphinx) с секциями `Parameters`, `Returns`, `Example`.
- **Импорты**: группируются в порядке: стандартная библиотека, сторонние пакеты, внутренние модули `app`.
- **Типизация**: используется `typing` (`Optional`, `Any`, `dict`, `list` и т.д.), требуется Python 3.10+.
- **Стилистика**: проект ориентирован на `ruff` для линтинга и форматирования.
- **Логирование**: структурированные логи с форматом `[CommandName] действие, token=..., user_id=...`. Уровни логирования настраиваются в `config.yml`.

---

## 10. Как и где менять бизнес-логику приложения

Бизнес-логика — это всё, что определяет *поведение* СКУД: когда открывать турникет, на какое время, что делать при тревоге, как обрабатывать проходы и т.д. Она сосредоточена в **доменном** и **прикладном** слоях. Инфраструктурный слой (GPIO, сеть, звук) трогать обычно не нужно.

### 10.1. Основные точки изменений

| Что меняешь | Где править | Что именно |
|-------------|-------------|------------|
| **Время открытия турникета** после карты/QR | `app/config.yml` → `timings.relay_open_duration_s` | Время в секундах, пока реле остаётся открытым |
| **Время открытия турникета** после отжатия кнопки | `app/config.yml` → `timings.button_timer_duration_s` | Время до автоматического закрытия после отпускания кнопки |
| **Логика открытия/закрытия, индикация, тревога** | `app/infrastructure/devices/turnstile/turnstile_device.py` + `commands.py` | `TurnstileDevice.handle()` выбирает `Command` по событию на основе текущего режима FSM; `commands.py` выполняет выходы асинхронно с таймерами и прерыванием |
| **Правила доступа** (кто проходит, кто нет) | `app/domain/access.py` | Класс `AccessPolicy`, метод `check`. Источник данных — `AccessRepository` (`cache/repository.py`) |
| **Реакция на кнопки** | `app/application/lgtu_application.py` → `_map_button_event()` + `app/config.yml` → `devices.buttons` | Сопоставление `label` → `action` (`open_entry`, `open_exit`, `shift`). Кнопка 3 (Shift) используется как модификатор для переключения в режимы unlocked_entry/unlocked_exit |
| **Реакция на тревогу** | `app/infrastructure/devices/turnstile/turnstile_device.py` → `_on_alarm_changed()` | Генерация `AlarmCommand` / `ClearAlarmCommand` |
| **Обработка проходов** (логирование, закрытие после прохода) | `app/application/lgtu_application.py` → `_log_passage()` + `TurnstileDevice._on_passage_detected()` | `PassageService.log_passage()` + `CloseCommand` |
| **Преобразование событий оборудования в доменные** | `app/application/lgtu_application.py` | Метод `_convert_scud_event_to_domain()` |
| **Админ-команды** | `app/application/lgtu_application.py` → `send_admin_command()` + `interfaces/cli.py` | `AdminCommand` → `DeviceCommand` → `TurnstileDevice` |
| **Добавить новое событие** | `app/domain/events.py` + `app/application/lgtu_application.py` | Определить dataclass события и обработать его в `_to_device_event()` / `TurnstileDevice.handle()` |
| **Тайминги, мапинги пинов, устройства** | `app/config.yml` | Секции `timings`, `mappings`, `devices`, `mux`, `shift_register` |

### 10.2. Принцип: доменный слой не зависит от инфраструктуры

- `AccessPolicy` **не импортирует** GPIO, HTTP, базы данных.
- `TurnstileDevice` (пока в инфраструктурном слое) знает имена пинов через `ModuleResolver`, но не работает с GPIO напрямую.
- Вместо этого они работают с моделями (`Passage`, `Credential`, `OutputCommand`) и портами (`AccessRepository`, `EventLog`).
- Если нужно изменить, *как* включается реле (инверсия, длительность импульса), править надо в инфраструктуре (`ShiftRegister`, `GpiodPinController`).
- Если нужно изменить, *когда* включается реле (по какому событию, на сколько), править в домене/приложении.

### 10.3. Типовые сценарии

#### Изменить действие кнопки

1. Открыть `app/config.yml`.
2. Найти секцию `devices.buttons`:

   ```yaml
   devices:
     buttons:
       entry:
         label: "button_1"
         action: "open_entry"
       exit:
         label: "button_2"
         action: "open_exit"
   ```

3. Изменить `action` на одно из: `open_entry`, `open_exit`, `close`.
4. Если нужно новое действие, расширить `_map_button_event()` в `app/application/lgtu_application.py` и добавить обработку в `TurnstileDevice._on_device_command()`.

#### Изменить поведение при тревоге

1. Открыть `app/infrastructure/devices/turnstile/commands.py`.
2. Найти классы `AlarmCommand` и `ClearAlarmCommand`.
3. Изменить список `OutputCommand`, который они применяют:

   ```python
   OutputCommand(name=self._exit_relay, state=True),   # открыть выход
   OutputCommand(name=self._main_buzzer, state=True),  # включить бипер
   OutputCommand(name=self._exit_red, state=True),     # красный индикатор
   ```

4. При необходимости добавить новые бизнес-имена в `mappings` конфига.

#### Изменить время автозакрытия после карты

1. Открыть `app/config.yml`.
2. Изменить:

   ```yaml
   timings:
     relay_open_duration_s: 3.0
   ```

3. `TurnstileDevice._load_config()` подхватит значение автоматически.

#### Добавить новый обработчик события

1. Определить событие в `app/domain/events.py`:

   ```python
   @dataclass
   class MyEvent:
       payload: str
   ```

2. Преобразовать `ScudEvent` в него в `app/application/lgtu_application.py` → `_convert_scud_event_to_domain()`.

3. Обработать его в `app/application/lgtu_application.py` → `_to_device_event()` и/или в `app/infrastructure/devices/turnstile/turnstile_device.py` → `handle()`.

4. Если нужно добавить новую команду, создать класс в `app/infrastructure/devices/turnstile/commands.py` и вернуть его из `TurnstileDevice.handle()`.

### 10.4. Что трогать не нужно

- `app/infrastructure/firmware/gpio/` — драйверы GPIO/мультиплексора/сдвигового регистра и Wiegand-считывателя.
- `app/infrastructure/firmware/serial/` — низкоуровневое чтение QR/Serial.
- `app/infrastructure/backend/` — HTTP-клиент к серверу.

Изменения в этих модулях требуются только при смене железа или протокола.

---

## 11. Почему `TurnstileDevice`, `LGTUApplication` и `ScudEngine` разделены

Эти три компонента отвечают за разные уровни абстракции. Их разделение позволяет тестировать бизнес-логику без железа, менять GPIO-библиотеку или вообще запускать приложение в мок-режиме.

### 11.1. `TurnstileDevice` — логика устройства

- Реализует конечный автомат турникета: состояния, переходы по событиям, выбор асинхронной команды.
- Не работает с GPIO напрямую: знает только бизнес-имена пинов (`entry_relay`, `exit_relay`, …) через `ModuleResolver`.
- Получает доменные события (`AccessGranted`, `AlarmChanged`, `PassageDetected`, `DeviceCommand`) и возвращает `Command`.
- Его можно протестировать unit-тестами без Orange Pi.

### 11.2. `LGTUApplication` — прикладной слой

- Оркестратор: связывает домен и инфраструктуру.
- Превращает события железа (`ScudEvent`) в доменные события (`CardRead`, `QrRead`, `ButtonPressed`, `AlarmChanged`, `PassageDetected`).
- Передаёт доменные события `TurnstileDevice` и выполняет возвращённые `Command`.
- Тактически применяет команды через `ShiftRegisterActuator`.
- Не управляет GPIO напрямую — делает это через `_CommandRunner`, который применяет `OutputCommand` к актуатору.

### 11.3. `ScudEngine` — инфраструктурный слой

- Работа с реальным железом: GPIO, мультиплексор, сдвиговый регистр, Wiegand, Serial.
- Запускает потоки, предоставляет `event_queue` и метод `send_command()`.
- Не содержит бизнес-правил: он только читает датчики и выполняет команды.
- Можно заменить на `MockEngine` в тестах.

### 11.4. Поток событий между ними

```
[Hardware] → ScudEngine → ScudEvent(BUTTON_PRESSED / ALARM_CHANGED / INPUT_SIGNAL) → LGTUApplication
                                                       ↓
                                          ButtonPressed / AlarmChanged / PassageDetected
                                                       ↓
                                          _to_device_event() / TurnstileDevice.handle()
                                                       ↓
                                          Command
                                                       ↓
                                          _CommandRunner.apply() → ScudEngine.set_output_mask() → GPIO
```

Такое разделение соответствует **Clean Architecture**: домен не зависит от приложения и инфраструктуры, а инфраструктура зависит от адаптеров, реализующих нужные интерфейсы.
