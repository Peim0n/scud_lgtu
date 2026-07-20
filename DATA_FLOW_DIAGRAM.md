# Блок-схема потоков данных и команд в системе СКУД

## Обзор архитектуры

Система состоит из следующих основных слоев:
- **Infrastructure Layer**: Работа с оборудованием (GPIO, Serial, Wiegand, Multiplexer, ShiftRegister)
- **Domain Layer**: Бизнес-логика (TurnstileState, AccessPolicy, PassageTracker)
- **Application Layer**: Оркестрация (LGTUApplication, Handlers, Services)

## Абстракция оборудования

### Входные пины (Multiplexer)
Для доменного и прикладного слоев входы через мультиплексор - это просто **входные пины** с именами из конфигурации (например, `button_entry`, `button_exit`, `alarm`, `sensor_inner`, `sensor_outer`).

**Только инфраструктурный слой знает о реализации:**
- `Multiplexer` - опрашивает адреса мультиплексора и читает входной пин
- `PinControllerThread` - координирует работу Multiplexer и ShiftRegister под общим локом
- `ScudEngine` - преобразует состояния мультиплексора в доменные события

**Для остального проекта:**
- `PassageDetector` - получает состояния входов как словарь `{input_name: state}`
- `handle_mux_input_changed` - получает изменения входов как доменные события
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
[WeigandReader.run()]
    ↓ (CardData в output_queue)
[ScudEngine._wiegand_queue_loop()]
    ↓ (ScudEvent type=CARD_READ в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (CardRead доменное событие)
[EventBus.publish(CardRead)]
    ↓ (CardRead)
[handle_card_read()]
    ↓ (AuthSession, AccessDecision)
[AccessPolicy.check_access()]
    ↓ (AccessDecision)
[handle_card_read() - логика доступа]
    ↓ (OutputCommandsGenerated или deny_beep_sequence)
[TurnstileState.open_entry_async() / deny_beep_sequence()]
    ↓ (OutputCommandsGenerated)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
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

#### 3. LGTUApplication → EventBus
**Данные**: `CardRead(reader_id: str, credential: Credential, timestamp: float)`
**Метод**: `LGTUApplication._convert_scud_event_to_domain()` → `EventBus.publish(CardRead)`

#### 4. EventBus → handle_card_read
**Данные**: `CardRead` доменное событие
**Метод**: `EventBus.subscribe("CardRead", lambda e: handle_card_read(...))`

#### 5. handle_card_read → AccessPolicy
**Данные**: `Credential(token_type: TokenTypeEnum, value: str, encrypted: bool)`
**Метод**: `AccessPolicy.check_access(credential)` → `AccessDecision(allowed: bool, reason: str)`

#### 6. handle_card_read → TurnstileState
**Данные**: `OutputCommand(name: str, state: bool)`
**Метод**: 
- При успехе: `TurnstileState.open_entry_async(event_bus)` → `OutputCommandsGenerated`
- При отказе: `TurnstileState.deny_beep_sequence(event_bus)` → `OutputCommandsGenerated`

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
    ↓ (串口数据)
[BackgroundSerialReader._read_loop()]
    ↓ (строка в queue)
[ScudEngine._serial_queue_loop()]
    ↓ (ScudEvent type=QR_READ в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (QR декодирование через QRDecoder)
    ↓ (QrRead доменное событие)
[EventBus.publish(QrRead)]
    ↓ (QrRead)
[handle_qr_read()]
    ↓ (AuthSession, AccessDecision)
[AccessPolicy.check_access()]
    ↓ (AccessDecision)
[handle_qr_read() - логика доступа]
    ↓ (OutputCommandsGenerated или deny_beep_sequence)
[TurnstileState.open_entry_async() / deny_beep_sequence()]
    ↓ (OutputCommandsGenerated)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
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

#### 4. LGTUApplication → EventBus
**Данные**: `QrRead(reader_id: str, credential: Credential, timestamp: float)`
**Метод**: `LGTUApplication._convert_scud_event_to_domain()` → `EventBus.publish(QrRead)`

#### 5-10. Аналогично сценарию 1 (через AccessPolicy, TurnstileState, ShiftRegister)
**Примечание**: Прикладной слой работает с именами пинов, инфраструктурный слой преобразует в битовые маски

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
    ↓ (ScudEvent type=MUX_CHANGED в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (MuxInputChanged доменное событие)
[EventBus.publish(MuxInputChanged)]
    ↓ (MuxInputChanged)
[handle_mux_input_changed()]
    ↓ (ButtonPressed доменное событие)
[EventBus.publish(ButtonPressed)]
    ↓ (ButtonPressed)
[handle_button_pressed()]
    ↓ (OutputCommandsGenerated)
[TurnstileState.open_entry_async() / open_exit_async()]
    ↓ (OutputCommandsGenerated)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
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
**Очередь**: `mux_queue` (Queue)
**Метод**: `PinControllerThread._mux_loop()` → `mux_queue.put_nowait(states)`
**Примечание**: Только инфраструктурный слой знает о реализации через мультиплексор

#### 3. ScudEngine → LGTUApplication (инфраструктурный → прикладной слой)
**Данные**: `ScudEvent(type=EventType.MUX_CHANGED, source=EventSource.MUX, payload={states})`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._mux_queue_loop()` → `event_queue.put_nowait(ScudEvent)`
**Примечание**: На этом уровне происходит абстракция - доменный слой видит просто входные пины с именами

#### 4. LGTUApplication → EventBus
**Данные**: `MuxInputChanged(input_name: str, state: bool, timestamp: float)`
**Метод**: `LGTUApplication._convert_scud_event_to_domain()` → `EventBus.publish(MuxInputChanged)`

#### 5. EventBus → handle_mux_input_changed
**Данные**: `MuxInputChanged` доменное событие
**Метод**: `EventBus.subscribe("MuxInputChanged", lambda e: handle_mux_input_changed(...))`

#### 6. handle_mux_input_changed → EventBus
**Данные**: `ButtonPressed(button_name: str, action: str, timestamp: float)`
**Метод**: `handle_mux_input_changed()` → `EventBus.publish(ButtonPressed)`

#### 7. EventBus → handle_button_pressed
**Данные**: `ButtonPressed` доменное событие
**Метод**: `EventBus.subscribe("ButtonPressed", lambda e: handle_button_pressed(...))`

#### 8. handle_button_pressed → TurnstileState
**Данные**: `OutputCommand(name: str, state: bool)`
**Метод**: `TurnstileState.open_entry_async(event_bus)` или `open_exit_async(event_bus)`

#### 9-12. Аналогично сценарию 1 (через OutputCommandsGenerated, ShiftRegister)

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
[ScudEngine._mux_queue_loop()]
    ↓ (словари состояний в PassageDetector.on_mux_state())
[PassageDetector.on_mux_state()]
    ↓ (детекция прохода по двум датчикам)
    ↓ (ScudEvent type=INPUT_SIGNAL в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (PassageDetected доменное событие)
[EventBus.publish(PassageDetected)]
    ↓ (PassageDetected)
[handle_passage_detected()]
    ↓ (PassageService.log_passage())
    ↓ (EventStore.add_passage_event())
    ↓ (TurnstileState.close())
    ↓ (OutputCommandsGenerated)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
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
**Примечание**: Инфраструктурный слой знает о реализации через мультиплексор, PassageDetector видит просто входные пины с именами

#### 4. ScudEngine → PassageDetector (инфраструктурный → прикладной слой)
**Данные**: `dict[str, int]` - словарь состояний входов с именами (абстракция входных пинов)
**Метод**: `ScudEngine._mux_queue_loop()` → `PassageDetector.on_mux_state(states, timestamp)`
**Примечание**: PassageDetector работает с именами входов (sensor_inner, sensor_outer), не зная о реализации через мультиплексор

#### 5. PassageDetector → ScudEngine
**Данные**: `ScudEvent(type=EventType.INPUT_SIGNAL, source=EventSource.SIGNAL, payload={zone, direction, duration})`
**Очередь**: `event_queue` (Queue)
**Метод**: `PassageDetector._emit()` → `event_queue.put_nowait(ScudEvent)`

#### 6. ScudEngine → LGTUApplication
**Данные**: `ScudEvent(type=EventType.INPUT_SIGNAL, ...)`
**Очередь**: `event_queue` (Queue)
**Метод**: `ScudEngine._event_loop()` → `event_queue.get()`

#### 7. LGTUApplication → EventBus
**Данные**: `PassageDetected(zone: str, direction: DirectionEnum, result: ResultEnum, timestamp: float)`
**Метод**: `LGTUApplication._convert_scud_event_to_domain()` → `EventBus.publish(PassageDetected)`

#### 8. EventBus → handle_passage_detected
**Данные**: `PassageDetected` доменное событие
**Метод**: `EventBus.subscribe("PassageDetected", lambda e: handle_passage_detected(...))`

#### 9. handle_passage_detected → PassageService
**Данные**: `Passage(zone: str, direction: DirectionEnum, result: ResultEnum, timestamp: float)`
**Метод**: `PassageService.log_passage(passage)` → `EventStore.add_passage_event()`

#### 10. handle_passage_detected → TurnstileState
**Данные**: `OutputCommand(name: str, state: bool)`
**Метод**: `TurnstileState.close()` → `OutputCommandsGenerated`

#### 11-14. Аналогично сценарию 1 (через OutputCommandsGenerated, ShiftRegister)
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
[ScudEngine._mux_queue_loop()]
    ↓ (ScudEvent type=MUX_CHANGED в event_queue)
[ScudEngine._event_loop()]
    ↓ (ScudEvent)
[LGTUApplication._convert_scud_event_to_domain()]
    ↓ (MuxInputChanged доменное событие)
[EventBus.publish(MuxInputChanged)]
    ↓ (MuxInputChanged)
[handle_mux_input_changed()]
    ↓ (AlarmChanged доменное событие)
[EventBus.publish(AlarmChanged)]
    ↓ (AlarmChanged)
[handle_alarm_changed()]
    ↓ (TurnstileState.set_alarm() или clear_alarm())
    ↓ (OutputCommandsGenerated)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1-5. Аналогично сценарию 3 (Multiplexer → handle_mux_input_changed)
**Примечание**: Инфраструктурный слой знает о реализации через мультиплексор, доменный слой видит просто входные пины с именами

#### 6. handle_mux_input_changed → EventBus (прикладной слой)
**Данные**: `AlarmChanged(active: bool, timestamp: float)`
**Метод**: `handle_mux_input_changed()` → `EventBus.publish(AlarmChanged)`

#### 7. EventBus → handle_alarm_changed (прикладной слой)
**Данные**: `AlarmChanged` доменное событие
**Метод**: `EventBus.subscribe("AlarmChanged", lambda e: handle_alarm_changed(...))`

#### 8. handle_alarm_changed → TurnstileState (прикладной слой)
**Данные**: `OutputCommand(name: str, state: bool)` - абстракция выходных пинов
**Метод**:
- При тревоге: `TurnstileState.set_alarm()` → `OutputCommandsGenerated`
- При сбросе: `TurnstileState.clear_alarm()` → `OutputCommandsGenerated`
**Примечание**: TurnstileState работает с именами пинов, не зная о реализации через сдвиговый регистр

#### 9-12. Аналогично сценарию 1 (через OutputCommandsGenerated, ShiftRegister)
**Примечание**: Инфраструктурный слой преобразует имена пинов в битовые маски для сдвигового регистра

---

## Сценарий 6: Периодический тик TurnstileState

### Поток данных

```
[ScudEngine._event_loop()]
    ↓ (периодический вызов)
[TurnstileState.tick(now)]
    ↓ (OutputCommandsGenerated при таймаутах)
[EventBus.publish(OutputCommandsGenerated)]
    ↓ (OutputCommandsGenerated)
[LGTUApplication._handle_output_commands()]
    ↓ (output_states dict)
[ScudEngine.set_output_mask()]
    ↓ (masks dict)
[PinControllerThread.set_mask()]
    ↓ (int value в shift_queue)
[ShiftRegister.run()]
    ↓ (GPIO сигналы SER_DATA/SER_CLK/SER_LATCH)
[Shift Register Hardware]
```

### Подробное описание команд

#### 1. ScudEngine → TurnstileState
**Данные**: `float` - текущее время
**Метод**: `ScudEngine._event_loop()` → `TurnstileState.tick(now)`

#### 2. TurnstileState → EventBus (прикладной слой)
**Данные**: `OutputCommand(name: str, state: bool)` при таймаутах:
- Автоматическое закрытие после таймаута
- Автоматическое выключение бипера
- Периодический бипер при тревоге
**Метод**: `TurnstileState.tick()` → `EventBus.publish(OutputCommandsGenerated)`
**Примечание**: TurnstileState работает с именами пинов, не зная о реализации через сдвиговый регистр

#### 3-6. Аналогично сценарию 1 (через OutputCommandsGenerated, ShiftRegister)
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
| `output_queue` (Mux) | `dict[str, int]` | `Multiplexer` | `PinControllerThread._mux_loop` | PinControllerThread | Инфраструктурный |
| `mux_queue` | `dict[str, int]` | `PinControllerThread._mux_loop` | `ScudEngine._mux_queue_loop` | ScudEngine | Инфраструктурный |
| `shift_queue` | `int` | `PinControllerThread.set_mask` | `ShiftRegister.run` | PinControllerThread | Инфраструктурный |
| `event_queue` | `ScudEvent` | Все модули | `ScudEngine._event_loop` | ScudEngine | Инфраструктурный → Прикладной |

---

## Сводная таблица доменных событий

| Событие | Производитель | Потребитель | Параметры |
|---------|--------------|-------------|-----------|
| `CardRead` | `LGTUApplication._convert_scud_event_to_domain` | `handle_card_read` | `reader_id, credential, timestamp` |
| `QrRead` | `LGTUApplication._convert_scud_event_to_domain` | `handle_qr_read` | `reader_id, credential, timestamp` |
| `MuxInputChanged` | `LGTUApplication._convert_scud_event_to_domain` | `handle_mux_input_changed` | `input_name, state, timestamp` |
| `ButtonPressed` | `handle_mux_input_changed` | `handle_button_pressed` | `button_name, action, timestamp` |
| `AlarmChanged` | `handle_mux_input_changed` | `handle_alarm_changed` | `active, timestamp` |
| `PassageDetected` | `LGTUApplication._convert_scud_event_to_domain` | `handle_passage_detected` | `zone, direction, result, timestamp` |
| `OutputCommandsGenerated` | `TurnstileState` | `LGTUApplication._handle_output_commands` | `commands: List[OutputCommand]` |

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
