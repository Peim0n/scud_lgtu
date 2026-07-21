# Архитектура LGTU Controller

LGTU Controller — это система контроля доступа (СКУД) для Orange Pi Zero LTS, построенная на принципах **Clean Architecture** с разделением на доменный, прикладной и инфраструктурный слои. Проект использует `gpiod` и `threading` для работы с GPIO, Wiegand-считывателями, последовательными портами, мультиплексорами и сдвиговыми регистрами.

## Общие принципы

- **Разделение слоёв**: доменный слой не зависит от инфраструктуры; инфраструктура адаптируется через порты (интерфейсы).
- **Событийная архитектура**: события от оборудования преобразуются в доменные события и обрабатываются через `EventBus`.
- **Потокобезопасность**: hardware-модули работают в отдельных потоках и передают данные через `queue.Queue`.
- **Офлайн-режим**: локальный кэш списка доступа позволяет работать при отсутствии связи с бэкендом.
- **Конфигурация через YAML**: `scud_lgtu/config.yml` задаёт пины, тайминги, устройства и параметры бэкенда.

## Структура слоёв

```
┌─────────────────────────────────────────────────────┐
│  Interfaces  │ run_lgtu_controller.py, interfaces/cli│
├─────────────────────────────────────────────────────┤
│ Application  │ LGTUApplication, handlers, services,  │
│              │ EventBus                              │
├─────────────────────────────────────────────────────┤
│    Domain    │ models, enums, events, turnstile,     │
│              │ access services, ports                │
├─────────────────────────────────────────────────────┤
│ Infrastructure│ ScudEngine, gpio, serial, cache,     │
│              │ persistence, backend, sound, threads  │
└─────────────────────────────────────────────────────┘
```

---

## 1. Доменный слой (`scud_lgtu/domain/`)

Содержит бизнес-логику и сущности, независимые от оборудования.

### 1.1. Общие компоненты (`scud_lgtu/domain/common/`)

| Модуль | Назначение |
|--------|------------|
| `enums/enums.py` | Перечисления: направление (`DirectionEnum`), тип токена (`TokenTypeEnum`), результат (`ResultEnum`), важность (`SeverityEnum`), тип события (`EventTypeEnum`) |
| `models/models.py` | Доменные модели: `Credential`, `AccessDecision`, `AuthSession`, `Passage`, `OutputCommand` |
| `events/events.py` | Доменные события: `CardRead`, `QrRead`, `MuxInputChanged`, `ButtonPressed`, `AlarmChanged`, `PassageDetected`, `OutputCommandsGenerated` |

### 1.2. Доступ (`scud_lgtu/domain/access/`)

| Модуль | Назначение |
|--------|------------|
| `ports/ports.py` | Порты (интерфейсы) для адаптеров: `AccessRepository`, `EventLog`, `BackendGateway`, `SoundOutput`, `Actuator`, `ConfigResolver` |
| `services/services.py` | Доменные сервисы: `AccessPolicy` (проверка доступа), `PassageTracker` (отслеживание проходов), `CredentialHasher` |

### 1.3. Турникет (`scud_lgtu/domain/turnstile/`)

| Модуль | Назначение |
|--------|------------|
| `services/turnstile.py` | Конечный автомат турникета `TurnstileState`: открытие/закрытие входа и выхода, тревога, таймауты, генерация `OutputCommand` |

---

## 2. Прикладной слой (`scud_lgtu/application/`)

Связывает инфраструктуру и доменную логику.

### 2.1. Оркестрация

| Модуль | Назначение |
|--------|------------|
| `orchestration/lgtu_application.py` | `LGTUApplication` — главный цикл приложения: чтение событий от `ScudEngine`, преобразование в доменные события, публикация в `EventBus` |

### 2.2. Шина событий

| Модуль | Назначение |
|--------|------------|
| `events/event_bus.py` | `EventBus` — асинхронная шина публикации/подписки на доменные события |

### 2.3. Обработчики событий (`scud_lgtu/application/handlers/`)

| Модуль | Назначение |
|--------|------------|
| `credential.py` | Обработка `CardRead` и `QrRead`: проверка доступа, открытие турникета |
| `mux.py` | Обработка `MuxInputChanged`: преобразование в `ButtonPressed` или `AlarmChanged` |
| `button.py` | Обработка `ButtonPressed`: открытие входа/выхода по кнопкам |
| `alarm.py` | Обработка `AlarmChanged`: включение/выключение режима тревоги |
| `passage.py` | Обработка `PassageDetected`: журналирование, закрытие турникета |
| `common.py` | Вспомогательные функции для формирования ответов считывателям |

### 2.4. Сервисы приложения (`scud_lgtu/application/services/`)

| Модуль | Назначение |
|--------|------------|
| `access_service.py` | Сервис доступа (обёртка/расширение над `AccessPolicy`) |
| `passage_service.py` | `PassageService` — журналирование проходов через `EventLog` |
| `sync_service.py` | `SyncService` — периодическая синхронизация с бэкендом |

---

## 3. Инфраструктурный слой (`scud_lgtu/infrastructure/`)

Адаптеры оборудования и внешних систем.

### 3.1. Ядро

| Модуль | Назначение |
|--------|------------|
| `core/engine.py` | `ScudEngine` — главный оркестратор hardware: запуск потоков, мосты очередей, watchdog |

### 3.2. GPIO (`scud_lgtu/infrastructure/gpio/`)

| Модуль | Назначение |
|--------|------------|
| `controller.py` | `GpiodPinController` и `PinControllerThread`: управление пинами, мультиплексором и сдвиговым регистром |
| `multiplexor.py` | `Multiplexer` — опрос входов через адресный мультиплексор |
| `shift_register.py` | `ShiftRegister` — вывод битовой маски в сдвиговый регистр |
| `signal_reader.py` | Чтение сигналов с GPIO |
| `actuator.py` | `ShiftRegisterActuator` — адаптер `Actuator` для сдвигового регистра |

### 3.3. Serial / Wiegand (`scud_lgtu/infrastructure/serial/`)

| Модуль | Назначение |
|--------|------------|
| `reader.py` | `BackgroundSerialReader` — фоновое чтение из Serial-порта |
| `wiegand_reader.py` | `WiegandReader` — чтение карт по Wiegand-интерфейсу |
| `qr_codec.py` | `QRDecoder` — декодирование URL QR-кодов с проверкой подписи |

### 3.4. Кэш и хранение

| Модуль | Назначение |
|--------|------------|
| `cache/access_cache.py` | `LocalAccessCache` — локальный JSON-кэш списка доступа |
| `cache/repository.py` | `AccessRepositoryAdapter` — адаптер `AccessRepository` |
| `cache/identifier_hash.py` | Хеширование идентификаторов |
| `persistence/event_store.py` | `EventStore` и `ScudEvent`/`ScudCommand` — хранение и очереди событий |
| `persistence/event_log.py` | `EventLogAdapter` — адаптер журналирования |
| `persistence/passage_detector.py` | `PassageDetector` — детекция прохода по двум датчикам |

### 3.5. Бэкенд и звук

| Модуль | Назначение |
|--------|------------|
| `backend/client.py` | `BackendClient` — HTTP-клиент для синхронизации |
| `backend/sync_scheduler.py` | `SyncScheduler` — планировщик синхронизации (устаревший/альтернативный) |
| `sound/player.py` | `SoundPlayer` — воспроизведение звуковых файлов |
| `sound/__init__.py` | `SoundOutputAdapter` — адаптер звукового выхода |

### 3.6. Конфигурация и загрузка

| Модуль | Назначение |
|--------|------------|
| `config/config_loader.py` | Загрузка `config.yml` |
| `config/module_resolver.py` | `ModuleResolver` — разрешение имён пинов/таймингов по конфигурации |

### 3.7. Прошивка и вспомогательные модули

| Модуль | Назначение |
|--------|------------|
| `firmware/device_abstraction.py` | Абстракция устройства |
| `firmware/gpio_adapter.py` | Адаптер GPIO для прошивки |
| `firmware/serial_adapter.py` | Адаптер Serial |
| `firmware/wiegand_adapter.py` | Адаптер Wiegand |
| `keys/__init__.py` | Публичные ключи для проверки QR |
| `threads/registry.py` | Реестр hardware-потоков |

---

## 4. Точки входа (`scud_lgtu/interfaces/`, корневые скрипты)

| Файл | Назначение |
|------|------------|
| `interfaces/cli.py` | Командный интерфейс для управления и диагностики |
| `run_lgtu_controller.py` | Запуск реального контроллера |
| `run_lgtu_controller_mock.py` | Запуск в режиме мок-оборудования |
| `run_lgtu_controller_mock_interactive.py` | Интерактивный мок-контроллер |
| `run_mock_devices.py` | Эмуляция hardware-устройств |
| `run_mock_devices_interactive.py` | Интерактивный эмулятор устройств |

---

## 5. Поток данных

### 5.1. Чтение карты Wiegand

```
[WiegandReader] → ScudEvent(CARD_READ) → LGTUApplication → CardRead → EventBus
                                                                     ↓
                                                         handle_credential → AccessPolicy
                                                                     ↓
                                              TurnstileState.open_* → OutputCommandsGenerated
                                                                     ↓
                                              EventBus → LGTUApplication → ScudEngine → ShiftRegister
```

### 5.2. Чтение QR через Serial

```
[BackgroundSerialReader] → ScudEvent(SERIAL_DATA) → LGTUApplication (QRDecoder) → QrRead → EventBus
```

### 5.3. Кнопки и тревога

```
[Multiplexer] → ScudEvent(MUX_CHANGED) → MuxInputChanged → handle_mux_input_changed
                                                ↓
                              ButtonPressed / AlarmChanged → handle_button / handle_alarm
```

### 5.4. Датчики прохода

```
[Multiplexer] → PassageDetector → ScudEvent(INPUT_SIGNAL) → PassageDetected
                                              ↓
                          handle_passage_detected → PassageService + TurnstileState.close
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

Основной файл — `scud_lgtu/config.yml`. Пример ключевых секций:

- `gpiod` — пины GPIO: `mux_a0`, `mux_a1`, `mux_a2`, `mux_input`, `shift_data`, `shift_clk`, `shift_latch`.
- `mux.inputs` — имена входов мультиплексора (`button_entry`, `button_exit`, `alarm`, `sensor_inner`, `sensor_outer`).
- `shift_register.pins` — имена выходов сдвигового регистра (`rel1`, `rel2`, `w1_green`, `w1_red`, `w2_green`, `w2_red`, `buz`, `w1_beep`, `w2_beep`).
- `timings` — таймауты прохода, Wiegand, синхронизации, очередей.
- `backend` — URL, endpoints, авторизация.
- `sound` — директория звуков и команда плеера.

---

## 8. Тестирование

| Файл/папка | Назначение |
|------------|------------|
| `tests/test_bootstrap.py` | Проверка сборки приложения и DI |
| `tests/test_config.py` | Проверка загрузки и валидации конфигурации |
| `tests/mocks/` | Моки: `MockEngine`, `MockGPIO`, `MockSerial`, `MockWiegand` |

---

## 9. Соглашения по коду

- **Docstrings**: оформлены на русском языке в формате reStructuredText (Sphinx) с секциями `Parameters`, `Returns`, `Example`.
- **Импорты**: группируются в порядке: стандартная библиотека, сторонние пакеты, внутренние модули `scud_lgtu`.
- **Типизация**: используется `typing` (`Optional`, `Any`, `dict`, `list` и т.д.), требуется Python 3.10+.
- **Стилистика**: проект ориентирован на `ruff` для линтинга и форматирования.

---

## 10. Как и где менять бизнес-логику приложения

Бизнес-логика — это всё, что определяет *поведение* СКУД: когда открывать турникет, на какое время, что делать при тревоге, как обрабатывать проходы и т.д. Она сосредоточена в **доменном** и **прикладном** слоях. Инфраструктурный слой (GPIO, сеть, звук) трогать обычно не нужно.

### 10.1. Основные точки изменений

| Что меняешь | Где править | Что именно |
|-------------|-------------|------------|
| **Время открытия турникета** после карты/QR | `scud_lgtu/config.yml` → `timings.relay_open_duration_s` | Время в секундах, пока реле остаётся открытым |
| **Время открытия турникета** после отжатия кнопки | `scud_lgtu/config.yml` → `timings.button_timer_duration_s` | Время до автоматического закрытия после отпускания кнопки |
| **Логика открытия/закрытия, индикация, тревога** | `scud_lgtu/domain/turnstile/services/turnstile.py` | Класс `TurnstileState`: методы `open_entry`, `open_exit`, `close`, `set_alarm`, `clear_alarm`, `tick` |
| **Правила доступа** (кто проходит, кто нет) | `scud_lgtu/domain/access/services/services.py` | Класс `AccessPolicy`, метод `check`. Источник данных — `AccessRepository` (`cache/repository.py`) |
| **Реакция на кнопки** | `scud_lgtu/application/handlers/button.py` + `scud_lgtu/config.yml` → `devices.buttons` | Сопоставление `label` → `action` (`open_entry`, `open_exit`, `close`) |
| **Реакция на тревогу** | `scud_lgtu/application/handlers/alarm.py` | Вызов `turnstile.set_alarm()` / `clear_alarm()` и публикация команд |
| **Обработка проходов** (логирование, закрытие после прохода) | `scud_lgtu/application/handlers/passage.py` | `handle_passage_detected` |
| **Преобразование событий оборудования в доменные** | `scud_lgtu/application/orchestration/lgtu_application.py` | Метод `_convert_scud_event_to_domain` |
| **Добавить новое событие** | `scud_lgtu/domain/common/events/events.py` + `scud_lgtu/application/handlers/` + `LGTUApplication._register_handlers` | Определить dataclass события, обработчик, зарегистрировать подписку |
| **Тайминги, мапинги пинов, устройства** | `scud_lgtu/config.yml` | Секции `timings`, `mappings`, `devices`, `mux`, `shift_register` |

### 10.2. Принцип: доменный слой не зависит от инфраструктуры

- `TurnstileState` и `AccessPolicy` **не импортируют** GPIO, HTTP, базы данных.
- Вместо этого они работают с моделями (`Passage`, `Credential`, `OutputCommand`) и портами (`AccessRepository`, `EventLog`).
- Если нужно изменить, *как* включается реле (инверсия, длительность импульса), править надо в инфраструктуре (`ShiftRegister`, `GpiodPinController`).
- Если нужно изменить, *когда* включается реле (по какому событию, на сколько), править в домене/приложении.

### 10.3. Типовые сценарии

#### Изменить действие кнопки

1. Открыть `scud_lgtu/config.yml`.
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
4. Если нужно новое действие (например, блокировка), расширить `scud_lgtu/application/handlers/button.py` и добавить метод в `TurnstileState`.

#### Изменить поведение при тревоге

1. Открыть `scud_lgtu/domain/turnstile/services/turnstile.py`.
2. Найти методы `set_alarm()` и `clear_alarm()`.
3. Изменить список `OutputCommand`, который они возвращают:

   ```python
   OutputCommand(name=self._exit_relay, state=True),   # открыть выход
   OutputCommand(name=self._main_buzzer, state=True),  # включить бипер
   OutputCommand(name=self._exit_red, state=True),     # красный индикатор
   ```

4. При необходимости добавить новые бизнес-имена в `mappings` конфига.

#### Изменить время автозакрытия после карты

1. Открыть `scud_lgtu/config.yml`.
2. Изменить:

   ```yaml
   timings:
     relay_open_duration_s: 3.0
   ```

3. `TurnstileState._load_from_resolver()` подхватит значение автоматически.

#### Добавить новый обработчик события

1. Определить событие в `scud_lgtu/domain/common/events/events.py`:

   ```python
   @dataclass
   class MyEvent:
       payload: str
   ```

2. Создать обработчик в `scud_lgtu/application/handlers/my_handler.py`:

   ```python
   def handle_my_event(event: MyEvent, turnstile, event_bus):
       ...
   ```

3. Зарегистрировать в `scud_lgtu/application/orchestration/lgtu_application.py`:

   ```python
   self._event_bus.subscribe("MyEvent", lambda e: handle_my_event(e, self._turnstile, self._event_bus))
   ```

4. Убедиться, что событие публикуется где-то в `_convert_scud_event_to_domain` или другом обработчике.

### 10.4. Что трогать не нужно

- `scud_lgtu/infrastructure/gpio/` — драйверы GPIO/мультиплексора/сдвигового регистра.
- `scud_lgtu/infrastructure/serial/` и `wiegand_reader.py` — низкоуровневое чтение карт/QR.
- `scud_lgtu/infrastructure/backend/` — HTTP-клиент к серверу.

Изменения в этих модулях требуются только при смене железа или протокола.
