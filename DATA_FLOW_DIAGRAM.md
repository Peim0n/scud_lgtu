# Блок-схема потоков данных и команд в системе СКУД

## Обзор архитектуры

Система состоит из следующих основных слоев:
- **Infrastructure Layer**: Работа с оборудованием (GPIO, Serial, Wiegand, Multiplexer, ShiftRegister)
- **Domain Layer**: Бизнес-логика (TurnstileState, AccessPolicy, PassageTracker)
- **Application Layer**: Оркестрация (LGTUApplication, Handlers, Services)

## Абстракция оборудования

### Входные пины (Multiplexer)
Для доменного и прикладного слоев входы через мультиплексор - это просто **входные пины** с именами из конфигурации (например, `button_entry`, `button_exit`, `alarm`, `sensor_entry`, `sensor_exit`).

**Только инфраструктурный слой знает о реализации:**
- `Multiplexer` - опрашивает адреса мультиплексора и читает входной пин
- `PinControllerThread` - координирует работу Multiplexer и ShiftRegister под общим локом
- `MuxEventMapper` - преобразует сырые состояния в `ScudEvent` (`BUTTON_PRESSED`, `ALARM_CHANGED`, `INPUT_SIGNAL`)
- `ScudEngine` - читает `mux_output_queue` и складывает готовые события в `event_queue`

**Для остального проекта:**
- `MuxEventMapper` - получает состояния входов как словарь `{input_name: state}`
- `LGTUApplication._convert_scud_event_to_domain()` - преобразует `ScudEvent` в доменные события
- Не знают о том, что входы реализованы через мультиплексор

### Выходные пины (ShiftRegister)
Для доменного и прикладного слоев выходы через сдвиговый регистр - это просто **выходные пины** с именами из конфигурации (например, `rel1`, `rel2`, `w1_green`, `w1_red`, `buz`).

**Только инфраструктурный слой знает о реализации:**
- `ShiftRegister` - записывает биты в сдвиговый регистр через SER_DATA/SER_CLK/SER_LATCH
- `PinControllerThread` - координирует работу Multiplexer и ShiftRegister под общим локом
- `ScudEngine` - преобразует имена пинов в битовые маски

**Для остального проекта:**
- `TurnstileState` - генерирует `OutputCommand(name="rel1", state=True)`
- `LGTUApplication` - собирает команды в словарь `{"rel1": True, "buz": True}`
- Не знают о том, что выходы реализованы через сдвиговый регистр

## Сценарий 1: Чтение карты через Wiegand считыватель

### Поток данных

```
[GPIO Hardware] 
    ↓ (сигналы D0/D1)
[WiegandReader.run()]
    ↓ (CardData в output_queue)
[ScudEngine._wiegand_queue_loop()]
    ↓ (ScudEvent type=CARD_READ в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (CardRead доменное событие)
[LGTUApplication._process_domain_event() / _to_device_event()]
    ↓ (CardRead)
[TurnstileDevice.handle()]
    ↓ (AccessDecision, AuthSession через AccessPolicy)
    ↓ (Command)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1. WeigandReader → ScudEngine
**Данные**: `CardData(card_data: int, raw_data: int, bit_sequence: str, is_valid: bool, error_message: str)`
**Очередь**: `output_queue` (Queue)
**Метод**: `WeigandReader._process_card()` → `output_queue.put_nowait(result)`

#### 2. ScudEngine → LGTUApplication
**Данные**: `ScudEvent(type=EventType.CARD_READ, source=EventSource.WIEGAND, payload={card_data, reader_label})`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._wiegand_queue_loop()` → `event_queue.put_nowait(ScudEvent)`

#### 3. LGTUApplication → _to_device_event
**Данные**: `CardRead(reader_id: str, credential: Credential, timestamp: float)`
**Метод**: `LGTUApplication._process_domain_event()` → `_to_device_event(CardRead)`

#### 4. _to_device_event → TurnstileDevice
**Данные**: `CardRead` доменное событие
**Метод**: `TurnstileDevice.handle(CardRead)` → `Command` или `None`

#### 5. TurnstileDevice → AccessPolicy
**Данные**: `Credential(token_type: TokenTypeEnum, value: str, encrypted: bool)`
**Метод**: `AccessPolicy.check_access(credential)` → `AccessDecision(allowed: bool, reason: str)`

#### 6. TurnstileDevice → _CommandRunner
**Данные**: `Command` / `OutputCommand(name: str, state: bool)`
**Метод**: 
- `TurnstileDevice.handle(CardRead)` → `Command`
- `_CommandRunner.apply(commands)` → `ShiftRegisterActuator.apply(OutputCommand)`

#### 7. LGTUApplication → ScudEngine (прикладной → инфраструктурный слой)
**Данные**: `dict[str, bool]` - мапинг имен пинов на состояния (абстракция выходных пинов)
**Метод**: `LGTUApplication._handle_output_commands()` → `ScudEngine.set_output_mask(output_states)`
**Примечание**: Прикладной слой работает с именами пинов, не зная о реализации через сдвиговый регистр

#### 8. ScudEngine → PinControllerThread (инфраструктурный слой)
**Данные**: `dict[str, bool]` - мапинг имен пинов на состояния
**Метод**: `ScudEngine.set_output_mask()` → `PinControllerThread.set_mask(masks)`
**Примечание**: ScudEngine преобразует имена пинов в битовые маски

#### 9. PinControllerThread → ShiftRegister (инфраструктурный слой)
**Данные**: `int` - битовая маска для сдвигового регистра (внутренняя реализация)
**Очередь**: `shift_queue` (Queue)
**Метод**: `PinControllerThread.set_mask()` → `shift_queue.put(new_state)`
**Примечание**: Только инфраструктурный слой знает о реализации через сдвиговый регистр

#### 10. ShiftRegister → GPIO Hardware (инфраструктурный слой)
**Данные**: GPIO сигналы на пинах SER_DATA, SER_CLK, SER_LATCH
**Метод**: `ShiftRegister._work_shift()` → `GpiodPinController.write_pin_nolock()`
**Примечание**: Только инфраструктурный слой знает о реализации через сдвиговый регистр

---

## Сценарий 2: Чтение QR кода через Serial считыватель

### Поток данных

```
[Serial Port Hardware]
    ↓ (данные с serial-порта)
[BackgroundSerialReader._read_loop()]
    ↓ (строка в queue)
[ScudEngine._serial_queue_loop()]
    ↓ (ScudEvent type=QR_READ в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (QR декодирование через QRDecoder)
    ↓ (QrRead доменное событие)
[LGTUApplication._process_domain_event()]
    ↓ (QrRead)
[TurnstileDevice.handle()]
    ↓ (AccessDecision, AuthSession через AccessPolicy)
    ↓ (Command)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1. BackgroundSerialReader → ScudEngine
**Данные**: `str` - строка из Serial порта (URL QR кода)
**Очередь**: `queue` (Queue)
**Метод**: `BackgroundSerialReader._read_loop()` → `queue.put(line)`

#### 2. ScudEngine → LGTUApplication
**Данные**: `ScudEvent(type=EventType.QR_READ, source=EventSource.SERIAL, payload={data, reader_label})`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._serial_queue_loop()` → `event_queue.put_nowait(ScudEvent)`

#### 3. LGTUApplication → QRDecoder
**Данные**: `str` - URL QR кода
**Метод**: `LGTUApplication._decode_qr_credential()` → `QRDecoder.decode_url(data)` → `Credential`

#### 4. LGTUApplication → _to_device_event
**Данные**: `QrRead(reader_id: str, credential: Credential, timestamp: float)`
**Метод**: `LGTUApplication._process_domain_event()` → `_to_device_event(QrRead)`

#### 5-10. Аналогично сценарию 1 (через AccessPolicy, TurnstileDevice, _CommandRunner)

---

## Сценарий 3: Нажатие кнопки через Multiplexer

### Поток данных

```
[GPIO Hardware - кнопки на мультиплексоре]
    ↓ (сигналы на адресных пинах и входе)
[Multiplexer.run()]
    ↓ (словарь состояний {input_name: state} в output_queue)
[PinControllerThread._mux_loop()]
    ↓ (словарь состояний в mux_queue)
[ScudEngine._mux_queue_loop()]
    ↓ (MuxEventMapper)
    ↓ (ScudEvent type=BUTTON_PRESSED в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (ButtonPressed доменное событие)
[LGTUApplication._process_domain_event()]
    ↓ (ButtonPressed)
[TurnstileDevice.handle()]
    ↓ (Command)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1. Multiplexer → PinControllerThread (инфраструктурный слой)
**Данные**: `dict[str, int]` - словарь состояний входов мультиплексора (внутренняя реализация)
**Очередь**: `output_queue` (Queue)
**Метод**: `Multiplexer._work_mux()` → `output_queue.put_nowait(buf)`
**Примечание**: Только инфраструктурный слой знает о реализации через мультиплексор

#### 2. PinControllerThread → ScudEngine (инфраструктурный слой)
**Данные**: `dict[str, int]` - словарь состояний входов мультиплексора (внутренняя реализация)
**Очередь**: `mux_output_queue` (Queue)
**Метод**: `Multiplexer` → `PinControllerThread.mux_output_queue.put_nowait(states)`
**Примечание**: Только инфраструктурный слой знает о реализации через мультиплексор

#### 3. ScudEngine → LGTUApplication (инфраструктурный → прикладной слой)
**Данные**: `ScudEvent(type=EventType.BUTTON_PRESSED, source=EventSource.MUX, payload={button_id, state})`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._start_signals()` → `MuxEventMapper.map_changes()` → `event_queue.put_nowait(ScudEvent)`
**Примечание**: На этом уровне происходит абстракция - доменный слой видит просто входные пины с именами

#### 4. LGTUApplication → _to_device_event
**Данные**: `ButtonPressed(button_name: str, action: str, timestamp: float)`
**Метод**: `LGTUApplication._process_domain_event()` → `_to_device_event(ButtonPressed)`

#### 5. _to_device_event → TurnstileDevice
**Данные**: `ButtonPressed` доменное событие
**Метод**: `TurnstileDevice.handle(ButtonPressed)` → `Command`

#### 6. TurnstileDevice → _CommandRunner
**Данные**: `Command` / `OutputCommand`
**Метод**: `_CommandRunner.apply(commands)` → `ShiftRegisterActuator.apply(OutputCommand)`

#### 7-9. Аналогично сценарию 1 (через ShiftRegisterActuator, ScudEngine, ShiftRegister)

---

## Сценарий 4: Детекция прохода через датчики

### Поток данных

```
[GPIO Hardware - датчики на мультиплексоре]
    ↓ (сигналы на адресных пинах и входе)
[Multiplexer.run()]
    ↓ (словарь состояний {input_name: state} в output_queue)
[PinControllerThread._mux_loop()]
    ↓ (словарь состояний в mux_queue)
[ScudEngine._start_signals()]
    ↓ (MuxEventMapper.map_changes())
    ↓ (ScudEvent type=INPUT_SIGNAL в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (PassageDetected доменное событие)
[LGTUApplication._process_domain_event()]
    ↓ (PassageDetected)
[TurnstileDevice.handle()]
    ↓ (Command)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1-3. Аналогично сценарию 3 (Multiplexer → ScudEngine)
**Примечание**: Инфраструктурный слой знает о реализации через мультиплексор, `MuxEventMapper` видит просто входные пины с именами

#### 4. ScudEngine → MuxEventMapper (инфраструктурный слой)
**Данные**: `dict[str, int]` - словарь состояний входов с именами (абстракция входных пинов)
**Метод**: `ScudEngine._start_signals()` → `MuxEventMapper.map_changes(prev, states)`
**Примечание**: `MuxEventMapper` работает с именами входов (`sensor_*`, `button_*`, `alarm`), не зная о реализации через мультиплексор

#### 5. MuxEventMapper → ScudEngine
**Данные**: `ScudEvent(type=EventType.INPUT_SIGNAL, source=EventSource.MUX, payload={zone, direction, duration})`
**Очередь**: `event_queue` (Queue)
**Метод**: `MuxEventMapper.map_changes()` → `event_queue.put_nowait(ScudEvent)`

#### 6. ScudEngine → LGTUApplication
**Данные**: `ScudEvent(type=EventType.INPUT_SIGNAL, ...)`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine.get_event_queue()` → `LGTUApplication._run()`

#### 7. LGTUApplication → _to_device_event
**Данные**: `PassageDetected(zone: str, direction: DirectionEnum, result: ResultEnum, timestamp: float)`
**Метод**: `LGTUApplication._process_domain_event()` → `_to_device_event(PassageDetected)`

#### 8. _to_device_event → TurnstileDevice
**Данные**: `PassageDetected` доменное событие
**Метод**: `TurnstileDevice.handle(PassageDetected)` → `Command`

#### 9. TurnstileDevice → _CommandRunner
**Данные**: `Command` / `OutputCommand`
**Метод**: `_CommandRunner.apply(commands)` → `ShiftRegisterActuator.apply(OutputCommand)`

#### 10. LGTUApplication → PassageService
**Данные**: `Passage(zone: str, direction: DirectionEnum, result: ResultEnum, timestamp: float)`
**Метод**: `PassageService.log_passage(passage)` → `EventStore.add_passage_event()`

#### 11-13. Аналогично сценарию 1 (через ShiftRegisterActuator, ScudEngine, ShiftRegister)
**Примечание**: Прикладной слой работает с именами пинов, инфраструктурный слой преобразует в битовые маски

---

## Сценарий 5: Режим тревоги (пожарная тревога)

### Поток данных

```
[GPIO Hardware - тревога на мультиплексоре]
    ↓ (сигнал тревоги на входе мультиплексора)
[Multiplexer.run()]
    ↓ (словарь состояний {alarm: state} в output_queue)
[PinControllerThread._mux_loop()]
    ↓ (словарь состояний в mux_queue)
[ScudEngine._start_signals()]
    ↓ (MuxEventMapper.map_changes())
    ↓ (ScudEvent type=ALARM_CHANGED в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (AlarmChanged доменное событие)
[LGTUApplication._process_domain_event()]
    ↓ (AlarmChanged)
[TurnstileDevice.handle()]
    ↓ (Command)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1-3. Аналогично сценарию 3 (Multiplexer → ScudEngine)
**Примечание**: Инфраструктурный слой знает о реализации через мультиплексор, `MuxEventMapper` видит `alarm` как обычный вход

#### 4. ScudEngine → LGTUApplication
**Данные**: `ScudEvent(type=EventType.ALARM_CHANGED, source=EventSource.MUX, payload={active})`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._start_signals()` → `MuxEventMapper.map_changes()` → `event_queue.put_nowait(ScudEvent)`

#### 5. LGTUApplication → _to_device_event
**Данные**: `AlarmChanged(active: bool, timestamp: float)`
**Метод**: `LGTUApplication._process_domain_event()` → `_to_device_event(AlarmChanged)`

#### 6. _to_device_event → TurnstileDevice
**Данные**: `AlarmChanged` доменное событие
**Метод**: `TurnstileDevice.handle(AlarmChanged)` → `Command`

#### 7. TurnstileDevice → _CommandRunner
**Данные**: `Command` / `OutputCommand`
**Метод**:
- При тревоге: `TurnstileDevice._on_alarm_changed()` → `AlarmCommand`
- При сбросе: `TurnstileDevice._on_alarm_changed()` → `ClearAlarmCommand`
**Примечание**: `TurnstileDevice` работает с именами пинов, не зная о реализации через сдвиговый регистр

#### 8-10. Аналогично сценарию 1 (через ShiftRegisterActuator, ScudEngine, ShiftRegister)
**Примечание**: Инфраструктурный слой преобразует имена пинов в битовые маски для сдвигового регистра

---

## Сценарий 6: Периодический тик TurnstileState

### Поток данных

```
[LGTUApplication._tick_loop()]
    ↓ (периодический вызов)
[TurnstileDevice.tick(now)]
    ↓ (Command при таймаутах)
[LGTUApplication._CommandRunner]
    ↓ (OutputCommand)
[ShiftRegisterActuator.apply()]
    ↓ (маска пинов)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1. LGTUApplication → TurnstileDevice
**Данные**: `float` - текущее время
**Метод**: `LGTUApplication._tick_loop()` → `TurnstileDevice.tick(now)`

#### 2. TurnstileDevice → _CommandRunner (прикладной слой)
**Данные**: `OutputCommand(name: str, state: bool)` при таймаутах:
- Автоматическое закрытие после таймаута
- Автоматическое выключение бипера
- Периодический бипер при тревоге
**Метод**: `TurnstileDevice.tick()` → `Command` / `OutputCommand` → `_CommandRunner.apply(commands)`
**Примечание**: `TurnstileDevice` работает с именами пинов, не зная о реализации через сдвиговый регистр

#### 3-5. Аналогично сценарию 1 (через ShiftRegisterActuator, ScudEngine, ShiftRegister)
**Примечание**: Прикладной слой работает с именами пинов, инфраструктурный слой преобразует в битовые маски

---

## Сценарий 7: Синхронизация с бэкендом

### Поток данных

```
[SyncService.tick(now)]
    ↓ (периодический вызов)
[SyncService._sync()]
    ↓ (BackendGateway.get_access_list())
    ↓ (LocalAccessCache.update())
    ↓ (BackendGateway.send_events())
    ↓ (EventStore.get_unsent_events())
    ↓ (EventStore.mark_events_sent())
```

### Подробное описание команд

#### 1. SyncService → BackendGateway
**Данные**: HTTP запросы GET/POST
**Метод**: `SyncService._sync()` → `BackendGateway.get_access_list()` / `send_events()`

#### 2. SyncService → LocalAccessCache
**Данные**: `dict[str, dict]` - список доступа
**Метод**: `LocalAccessCache.update(access_list)`

#### 3. SyncService → EventStore
**Данные**: `list[PassageEvent]` - неотправленные события
**Метод**: `EventStore.get_unsent_events()` / `mark_events_sent()`

---

## Сводная таблица очередей

| Очередь | Тип данных | Производитель | Потребитель | Расположение | Слой |
|---------|-----------|--------------|-------------|-------------|------|
| `output_queue` (Wiegand) | `CardData` | `WeigandReader` | `ScudEngine._wiegand_queue_loop` | ScudEngine | Инфраструктурный |
| `queue` (Serial) | `str` | `BackgroundSerialReader` | `ScudEngine._serial_queue_loop` | ScudEngine | Инфраструктурный |
| `output_queue` (Mux) | `dict[str, int]` | `Multiplexer` | `PinControllerThread.mux_output_queue` | PinControllerThread | Инфраструктурный |
| `mux_output_queue` | `dict[str, int]` | `PinControllerThread` | `ScudEngine._start_signals()` | ScudEngine | Инфраструктурный |
| `shift_queue` | `int` | `PinControllerThread.set_mask` | `ShiftRegister.run` | PinControllerThread | Инфраструктурный |
| `event_queue` | `ScudEvent` | `ScudEngine` | `LGTUApplication._run()` | LGTUApplication | Инфраструктурный → Прикладной |

---

## Сводная таблица доменных событий

| Событие | Производитель | Потребитель | Параметры |
|---------|--------------|-------------|-----------|
| `CardRead` | `LGTUApplication._convert_scud_event_to_domain` | `TurnstileDevice.handle()` | `reader_id, credential, timestamp` |
| `QrRead` | `LGTUApplication._convert_scud_event_to_domain` | `TurnstileDevice.handle()` | `reader_id, credential, timestamp` |
| `ButtonPressed` | `MuxEventMapper` / `LGTUApplication._convert_scud_event_to_domain` | `TurnstileDevice.handle()` | `button_id, state` |
| `AlarmChanged` | `MuxEventMapper` / `LGTUApplication._convert_scud_event_to_domain` | `TurnstileDevice.handle()` | `active` |
| `PassageDetected` | `LGTUApplication._convert_scud_event_to_domain` | `TurnstileDevice.handle()` | `zone, direction, duration, timestamp` |

---

## Сводная таблица OutputCommand

| Имя пина | Описание | Используется в |
|----------|----------|----------------|
| `rel1` | Реле входа | `open_entry`, `close`, `set_alarm`, `clear_alarm`, `block` |
| `rel2` | Реле выхода | `open_exit`, `close`, `set_alarm`, `clear_alarm`, `block` |
| `w1_green` | Индикатор входа (зелёный) | `open_entry`, `close` |
| `w1_red` | Индикатор входа (красный) | `open_entry`, `set_alarm`, `clear_alarm`, `block`, `unblock` |
| `w2_green` | Индикатор выхода (зелёный) | `open_exit`, `close` |
| `w2_red` | Индикатор выхода (красный) | `open_exit`, `set_alarm`, `clear_alarm`, `block`, `unblock` |
| `buz` | Основной бипер | `open_entry`, `open_exit`, `deny_beep_sequence`, `set_alarm`, `clear_alarm`, `tick` |
| `w1_beep` | Бипер считывателя входа | `handle_card_read`, `handle_qr_read` (индикаторы) |
| `w2_beep` | Бипер считывателя выхода | `handle_card_read`, `handle_qr_read` (индикаторы) |

---

## Временные диаграммы

### Wiegand чтение карты
```
GPIO: D0=_____-_____-_____ D1=_____-____-_____
WeigandReader: accumulate bits (26 total)
WeigandReader: CardData -> output_queue
ScudEngine: CardData -> ScudEvent -> event_queue
LGTUApplication: ScudEvent -> CardRead -> EventBus
handle_card_read: CardRead -> AccessDecision
TurnstileState: AccessDecision -> OutputCommandsGenerated
ShiftRegister: OutputCommandsGenerated -> GPIO
```

### Multiplexer опрос
```
GPIO: Addr pins cycle 0-7, read input each
Multiplexer: set_addr -> settle -> read (under lock)
Multiplexer: dict -> output_queue (delta-filtered)
PinControllerThread: dict -> mux_queue
ScudEngine: dict -> PassageDetector / handle_mux
```

### ShiftRegister запись
```
TurnstileState: OutputCommandsGenerated
LGTUApplication: commands -> output_states dict
ScudEngine: dict -> masks dict
PinControllerThread: masks -> int mask
ShiftRegister: int -> SER_DATA/SER_CLK/SER_LATCH sequence
GPIO: 16 bits shifted out, LATCH pulsed
```
