# Техническое задание: Рефакторинг архитектуры мапинга устройств

## 1. Цель работы

Устранить DRY и KISS нарушения в проекте SCUD LGTU путем внедрения модульной архитектуры мапинга устройств с локальными именами в каждом модуле.

## 2. Текущие проблемы

### 2.1 DRY нарушения

- **Дублирование обработчиков карт и QR-кодов** (`card.py`, `qr.py`)
  - Идентичная структура, отличаются только префиксом токена
  - Рекомендация: Создать параметризованный обработчик с префиксом как параметром

- **Дублирование функций бипера** в `basic_business_logic.py` (строки 116-207)
  - Множество похожих функций: `beep()`, `w1_beep()`, `w2_beep()`, `pult_beep()`, `beep_custom()`, `beep_repeat()`
  - Все выполняют одно действие с разными параметрами
  - Рекомендация: Объединить в одну функцию `beep(buzzer: str, duration: float, count: int = 1, pause: float = 0)`

- **Дублирование обработки проходов** в `lgtu_controller.py` (строки 181-229)
  - Методы `handle_passage_in()` и `handle_passage_out()` идентичны, отличаются только направлением
  - Рекомендация: Объединить в `handle_passage(direction: str)`

- **Дублирование обработки кнопок** в `lgtu_controller.py` (строки 299-325)
  - Методы `handle_button_1()` и `handle_button_2()` идентичны, отличаются только именами реле/индикаторов
  - Рекомендация: Создать параметризованный метод `handle_button(button_id: str, relay: str, indicator: str)`

- **Хардкод имен пинов** в `turnstile.py` (строки 321-353)
  - Методы `close_async()` и `_close_after_timeout()` используют хардкод `"rel1"`, `"rel2"` вместо настроенных `_entry_relay`, `_exit_relay`
  - Рекомендация: Использовать атрибуты класса из `__init__`

- **Повторяющаяся логика поиска конфигурации** в обработчиках
  - Во всех обработчиках повторяется логика поиска конфигурации по label в словаре devices
  - Рекомендация: Вынести в утилитарную функцию `find_device_config(devices: dict, device_type: str, label: str)`

### 2.2 KISS нарушения

- **Слишком сложный TurnstileState** (451 строк)
  - Класс выполняет множество обязанностей: управление состоянием, асинхронные операции, тайминги, GPIO команды, совместимость со старым API
  - Рекомендация: Разделить на отдельные классы: `TurnstileStateMachine`, `TurnstileAsyncOperations`, `TurnstileConfig`

- **Сложный GpiodPinController** (721 строк)
  - Смешивает низкоуровневые операции GPIO, управление потоками, совместимость с OPZPinController
  - Рекомендация: Вынести `PinControllerThread` в отдельный файл, упростить основной класс

- **Монолитный LGTUController** (457 строк)
  - Один класс обрабатывает все типы событий, содержит бизнес-логику, управление GPIO, синхронизацию
  - Рекомендация: Разделить на отдельные контроллеры по типам событий (QRController, CardController, PassageController)

- **Сложная логика PassageDetector**
  - Детектор прохода имеет сложную логику отслеживания состояний датчиков с множеством условий
  - Рекомендация: Упростить используя конечный автомат с явными состояниями

- **Избыточное логирование** в `basic_business_logic.py`
  - Множество функций-обёрток для логирования (`log_info`, `log_error`), которые просто вызывают logger
  - Рекомендация: Использовать logger напрямую, убрать обёртки

- **Сложная конфигурация shift_register**
  - Логика загрузки пинов с инверсией и масками избыточна для текущего использования
  - Рекомендация: Упростить до прямой маппинг имя → пин

### 2.3 Проблемы конфигурации

- **Плоская структура конфига** без иерархии
- **Дублирование имен** на разных уровнях
- **Отсутствие явного мапинга** между модулями
- **Хардкод имен** в коде

## 3. Предлагаемое решение

### 3.1 Модульная архитектура конфигурации

Каждый модуль работает со своими локальными именами. Мапинг между модулями осуществляется через конфигурацию.

**Важно:** Секции конфига соответствуют классам в коде:
- `gpiod_controller` → класс `GpiodController` в `infrastructure/gpio/controller.py` (абстракция над gpiod)
- `shift_register` → класс `ShiftRegister` в `infrastructure/gpio/shift_register.py`
- `mux` → класс `Multiplexer` в `infrastructure/gpio/multiplexor.py`
- `business` → используется в бизнес-логике (handlers, services)
- `devices` → используется для конфигурации считывателей

**Структура конфига:**

```yaml
# ── GPIO-контроллер (абстракция над gpiod) ──
# Мапинг логических имен пинов на реальные gpiod пины
gpiod_controller:
  pins:
    # Пины для сдвигового регистра
    shift_data: PA6
    shift_clk: PA19
    shift_latch: PA7
    
    # Пины для мультиплексора
    mux_a0: PA6
    mux_a1: PA11
    mux_a2: PA12
    mux_input: PL11
    
    # Пины для Wiegand-считывателей
    wiegand1_d0: PA10
    wiegand1_d1: PA2
    wiegand2_d0: PA3
    wiegand2_d1: PA18

# ── Аппаратные модули (инфраструктура) ──
# Секции конфигурации для классов инфраструктуры

# Секция shift_register: конфигурация для класса ShiftRegister
shift_register:
  ser_data: PA6
  ser_clk: PA19
  ser_latch: PA7
  reg_len: 16
  pins:
    beep1: {offset: 3, inverted: false}
    beep2: {offset: 11, inverted: false}
    main_beeper: {offset: 8, inverted: false}
    green1: {offset: 1, inverted: false}
    red1: {offset: 2, inverted: false}
    green2: {offset: 9, inverted: false}
    red2: {offset: 10, inverted: false}
    rel1: {offset: 14, inverted: false}
    rel2: {offset: 15, inverted: false}
    pult_buzz: {offset: 4, inverted: false}
    pult_l3: {offset: 5, inverted: false}
    pult_l2: {offset: 6, inverted: false}
    pult_l1: {offset: 7, inverted: false}
    od1: {offset: 12, inverted: false}
    od2: {offset: 13, inverted: false}

# Секция mux: конфигурация для класса Multiplexer
mux:
  addr_pins: [PA6, PA11, PA12]
  input_pin: PL11
  inputs:
    input_0: {addr: 0}
    button_3: {addr: 1}
    sensor_2: {addr: 2}
    input_3: {addr: 3}
    sensor_1: {addr: 4}
    button_1: {addr: 5}
    alarm: {addr: 6}
    button_2: {addr: 7}

# ── Бизнес-секция (приложение) ──
# Мапинг бизнес-имен на аппаратные секции
business:
  entry_beeper: "shift_register.beep1"
  exit_beeper: "shift_register.beep2"
  main_buzzer: "shift_register.main_beeper"
  inner_indicator_success: "shift_register.green1"
  inner_indicator_fail: "shift_register.red1"
  outer_indicator_success: "shift_register.green2"
  outer_indicator_fail: "shift_register.red2"
  entry_relay: "shift_register.rel1"
  exit_relay: "shift_register.rel2"
  entry_button: "mux.inputs.button_1"
  exit_button: "mux.inputs.button_2"
  alarm_input: "mux.inputs.alarm"
  entry_sensor: "mux.inputs.sensor_1"
  exit_sensor: "mux.inputs.sensor_2"
  # исторические имена для совместимости
  w1_beep: "shift_register.beep1"
  w2_beep: "shift_register.beep2"
  buz: "shift_register.main_beeper"
  w1_green: "shift_register.green1"
  w1_red: "shift_register.red1"
  w2_green: "shift_register.green2"
  w2_red: "shift_register.red2"
  rel1: "shift_register.rel1"
  rel2: "shift_register.rel2"

# ── Функциональные устройства ──
# Конфигурация устройств с ссылками на бизнес-секцию
devices:
  readers:
    entry_card_reader:
      beeper: "business.entry_beeper"
      indicator_success: "business.inner_indicator_success"
      indicator_fail: "business.inner_indicator_fail"
    exit_card_reader:
      beeper: "business.exit_beeper"
      indicator_success: "business.outer_indicator_success"
      indicator_fail: "business.outer_indicator_fail"
  buttons:
    entry_button:
      input: "business.entry_button"
      relay: "business.entry_relay"
    exit_button:
      input: "business.exit_button"
      relay: "business.exit_relay"
```

### 3.2 Класс ModuleResolver

**Файл:** `scud_lgtu/infrastructure/config/module_resolver.py`

```python
class ModuleResolver:
    """
    Резолвер модульных имен с локальными именами в каждом модуле.
    
    Каждый модуль работает со своими локальными именами.
    Мапинг между модулями - в конфиге через "module.local_name".
    """
    
    def __init__(self, config: dict):
        self._config = config
        self._current_module = None
        self._cache = {}
    
    def set_context(self, module_name: str):
        """Установить текущий модуль."""
        self._current_module = module_name
    
    def resolve(self, name: str) -> dict:
        """
        Разрешить имя до конфигурации.
        
        - Если имя содержит точку: "module.local_name" - явный мапинг
        - Если имя без точки: ищем в текущем модуле
        """
        if name in self._cache:
            return self._cache[name]
        
        if '.' in name:
            module, local_name = name.split('.', 1)
            config = self._get_module_config(module)
            if config and local_name in config:
                result = config[local_name]
                if isinstance(result, str):
                    result = self.resolve(result)
                self._cache[name] = result
                return result
        else:
            if self._current_module:
                config = self._get_module_config(self._current_module)
                if config and name in config:
                    result = config[name]
                    self._cache[name] = result
                    return result
        
        raise ValueError(f"Name not found: {name} (context: {self._current_module})")
    
    def _get_module_config(self, module_name: str) -> dict:
        """Получить конфигурацию секции."""
        return self._config.get(module_name, {})
```

### 3.3 Использование ModuleResolver

**Примеры использования:**

```python
# Инициализация
resolver = ModuleResolver(config)

# Установка контекста для аппаратного модуля
resolver.set_context("shift_register")
beep1_config = resolver.resolve("beep1")  # → {offset: 3, inverted: false}

# Установка контекста для бизнес-модуля
resolver.set_context("business")
entry_beeper = resolver.resolve("entry_beeper")  # → "shift_register.beep1" → {offset: 3, inverted: false}

# Явное указание модуля
beep1_config = resolver.resolve("shift_register.beep1")  # → {offset: 3, inverted: false}
```

### 3.4 Полный пример нового config.yml

```yaml
# ── GPIO-контроллер (абстракция над gpiod) ──
# Мапинг логических имен пинов на реальные gpiod пины
gpiod_controller:
  pins:
    # Пины для сдвигового регистра
    shift_data: PA6
    shift_clk: PA19
    shift_latch: PA7
    
    # Пины для мультиплексора
    mux_a0: PA6
    mux_a1: PA11
    mux_a2: PA12
    mux_input: PL11
    
    # Пины для Wiegand-считывателей
    wiegand1_d0: PA10
    wiegand1_d1: PA2
    wiegand2_d0: PA3
    wiegand2_d1: PA18

# ── Аппаратные модули (инфраструктура) ──

# Секция shift_register: конфигурация для класса ShiftRegister
shift_register:
  ser_data: "gpiod_controller.shift_data"
  ser_clk: "gpiod_controller.shift_clk"
  ser_latch: "gpiod_controller.shift_latch"
  reg_len: 16
  pins:
    beep1: {offset: 3, inverted: false}
    beep2: {offset: 11, inverted: false}
    main_beeper: {offset: 8, inverted: false}
    green1: {offset: 1, inverted: false}
    red1: {offset: 2, inverted: false}
    green2: {offset: 9, inverted: false}
    red2: {offset: 10, inverted: false}
    rel1: {offset: 14, inverted: false}
    rel2: {offset: 15, inverted: false}
    pult_buzz: {offset: 4, inverted: false}
    pult_l3: {offset: 5, inverted: false}
    pult_l2: {offset: 6, inverted: false}
    pult_l1: {offset: 7, inverted: false}
    od1: {offset: 12, inverted: false}
    od2: {offset: 13, inverted: false}
  timings:
    shift_queue_maxsize: 50

# Секция mux: конфигурация для класса Multiplexer
mux:
  addr_pins:
    A0: "gpiod_controller.mux_a0"
    A1: "gpiod_controller.mux_a1"
    A2: "gpiod_controller.mux_a2"
  input_pin: "gpiod_controller.mux_input"
  inputs:
    input_0: {addr: 0}
    button_3: {addr: 1}
    sensor_2: {addr: 2}
    input_3: {addr: 3}
    sensor_1: {addr: 4}
    button_1: {addr: 5}
    alarm: {addr: 6}
    button_2: {addr: 7}
  timings:
    mux_poll_interval_s: 0.05
    mux_addr_settle_s: 0.0003
    mux_queue_maxsize: 100

# ── Бизнес-секция (приложение) ──
# Мапинг бизнес-имен на аппаратные секции
business:
  # Биперы
  entry_beeper: "shift_register.beep1"
  exit_beeper: "shift_register.beep2"
  main_buzzer: "shift_register.main_beeper"
  
  # Индикаторы
  inner_indicator_success: "shift_register.green1"
  inner_indicator_fail: "shift_register.red1"
  outer_indicator_success: "shift_register.green2"
  outer_indicator_fail: "shift_register.red2"
  
  # Реле
  entry_relay: "shift_register.rel1"
  exit_relay: "shift_register.rel2"
  
  # Кнопки и датчики (через мультиплексор)
  entry_button: "mux.button_1"
  exit_button: "mux.button_2"
  alarm_input: "mux.alarm"
  entry_sensor: "mux.sensor_1"
  exit_sensor: "mux.sensor_2"
  
  timings:
    auth_timeout_s: 5.0
    relay_open_duration_s: 2.0
    indicator_duration_s: 2.0
    beep_signal_duration_s: 0.05
    beep_signal_pause_s: 0.1
    deny_beep_duration_s: 0.1
    deny_beep_pause_s: 0.1
    deny_beep_count: 3
    open_beep_duration_s: 0.1
    alarm_beep_on_duration_s: 0.5
    alarm_beep_off_duration_s: 0.5
    button_timer_duration_s: 2.0
    passage_timeout_s: 2.0
    passage_blockage_timeout_s: 5.0
    sensor_debounce_s: 0.5
    sensor_event_timeout_s: 0.1

# ── Wiegand-считыватели ──
wiegand:
  - label: Wiegand-1
    d0: "gpiod_controller.wiegand1_d0"
    d1: "gpiod_controller.wiegand1_d1"
    type: era_mf_64_hash
    encrypted: false

  - label: Wiegand-2
    d0: "gpiod_controller.wiegand2_d0"
    d1: "gpiod_controller.wiegand2_d1"
    type: era_mf_64_hash
    encrypted: false
  timings:
    wiegand_bit_timeout_s: 0.025
    wiegand_wait_timeout_s: 0.005
    wiegand_ignore_after_valid_s: 0.05

# ── Серийные порты ──
serial:
  - label: Serial-1
    port: /dev/ttyS1
    baud: 115200

  - label: Serial-2
    port: /dev/ttyS2
    baud: 115200
  timings:
    serial_queue_timeout_s: 0.2
    serial_retry_delay_s: 1.0

# ── Функциональные устройства ──
# Конфигурация считывателей
devices:
  # Считыватели (Wiegand и Serial/QR)
  readers:
    entry_card_reader:
      label: "Wiegand-1"
      type: "wiegand"
      direction: "entry"

    exit_card_reader:
      label: "Wiegand-2"
      type: "wiegand"
      direction: "exit"

    entry_qr_reader:
      label: "Serial-1"
      type: "serial"
      direction: "entry"

    exit_qr_reader:
      label: "Serial-2"
      type: "serial"
      direction: "exit"

# ── Параметры доступа ──
access:
  static_key: "0123456789abcdef0123456789abcdef"
  dynamic_key: "fedcba9876543210fedcba9876543210"

# ── Общие системные тайминги ──
timings:
  watchdog_check_interval_s: 2.0
  watchdog_stop_timeout_s: 2.0
  backend_sync_interval_s: 600
  event_queue_timeout_s: 0.2
  command_queue_timeout_s: 0.2
  thread_join_timeout_s: 5.0
  event_queue_maxsize: 1000
  command_queue_maxsize: 100
  sound_queue_maxsize: 20

# ── Логирование ──
logging:
  level: INFO
  format: "%(asctime)s %(name)s [%(levelname)s] %(message)s"
  loggers:
    asyncio: WARNING
    scud_lgtu.application.lgtu_application: INFO
    scud_lgtu.application.handlers: INFO
    scud_lgtu.infrastructure.gpio.shift_register: WARNING
    scud_lgtu.infrastructure.gpio.multiplexor: WARNING
    scud_lgtu.domain.turnstile: INFO

# ── Тестовый HTTP API ──
api:
  enabled: true
  host: "0.0.0.0"
  port: 8080
```

### 3.5 Рефакторинг обработчиков

**Объединить `card.py` и `qr.py` в один файл:**

```python
# scud_lgtu/application/handlers/credential.py
async def handle_credential(event, turnstile, access_policy, passage_tracker, event_bus, session, devices: dict, token_prefix: str) -> None:
    """
    Общий обработчик для учётных данных.
    
    Parameters
    ----------
    token_prefix : str
        Префикс токена ("cardid" или "maxid")
    """
    session = AuthSession(
        token=f"{token_prefix}:{event.credential.value}",
        direction=DirectionEnum.IN,
        user_id=None
    )
    await handle_credential_common(event, turnstile, access_policy, passage_tracker, event_bus, session, devices)
```

### 3.6 Рефакторинг функций бипера

**Объединить в одну функцию:**

```python
# scud_lgtu/application/basic_business_logic.py
def beep(engine, buzzer: str = "buz", duration: float = 0.05, count: int = 1, pause: float = 0.0) -> None:
    """
    Универсальная функция бипера.
    
    Parameters
    ----------
    buzzer : str
        Имя бипера (buz, w1_beep, w2_beep, pult_buzz)
    duration : float
        Длительность одного сигнала
    count : int
        Количество сигналов
    pause : float
        Пауза между сигналами
    """
    for i in range(count):
        set_shift_pins(engine, {buzzer: True})
        time.sleep(duration)
        set_shift_pins(engine, {buzzer: False})
        if i < count - 1 and pause > 0:
            time.sleep(pause)
```

### 3.7 Рефакторинг TurnstileState

**Разделить на классы:**

```python
# scud_lgtu/domain/turnstile_state_machine.py
class TurnstileStateMachine:
    """Конечный автомат турникета (только состояния)."""
    def __init__(self):
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
    
    def can_open(self, direction: DirectionEnum) -> bool:
        # логика проверки возможности открытия
    
    def open_entry(self) -> None:
        # логика открытия входа
    
    def open_exit(self) -> None:
        # логика открытия выхода
    
    def close(self) -> None:
        # логика закрытия

# scud_lgtu/domain/turnstile_async_ops.py
class TurnstileAsyncOperations:
    """Асинхронные операции турникета."""
    def __init__(self, state_machine: TurnstileStateMachine, resolver: ModuleResolver):
        self._state = state_machine
        self._resolver = resolver
    
    async def open_entry_async(self, event_bus, start_timer: bool = True) -> None:
        # асинхронное открытие входа
    
    async def open_exit_async(self, event_bus, start_timer: bool = True) -> None:
        # асинхронное открытие выхода
    
    async def close_async(self, event_bus) -> None:
        # асинхронное закрытие

# scud_lgtu/domain/turnstile.py
class TurnstileState:
    """Фасад, объединяющий все компоненты турникета."""
    def __init__(self, resolver: ModuleResolver, timings: dict = None):
        self._state_machine = TurnstileStateMachine()
        self._async_ops = TurnstileAsyncOperations(self._state_machine, resolver)
        self._config = TurnstileConfig(resolver, timings)
```

### 3.8 Утилитарная функция поиска конфигурации

```python
# scud_lgtu/application/utils/config_helper.py
def find_device_config(devices: dict, device_type: str, label: str) -> dict:
    """
    Найти конфигурацию устройства по label.
    
    Parameters
    ----------
    devices : dict
        Словарь устройств из конфига
    device_type : str
        Тип устройства (readers, buttons, sensors)
    label : str
        Имя устройства для поиска
    
    Returns
    -------
    dict
        Конфигурация устройства или None
    """
    devices_of_type = devices.get(device_type, {})
    for device_name, device_config in devices_of_type.items():
        if device_config.get("label") == label:
            return device_config
    return None
```

## 4. План реализации

### Этап 1: Подготовка конфигурации (1 день)
1. Создать новую структуру конфига с модулями
2. Разделить на аппаратные модули (shift_register, mux) и бизнес-модуль (business)
3. Создать секцию devices для функциональных устройств
4. Сохранить старую структуру для обратной совместимости
5. Заполнить новые секции данными из старой
6. Добавить валидацию конфига

### Этап 2: Реализация ModuleResolver (1 день)
1. Создать файл `scud_lgtu/infrastructure/config/module_resolver.py`
2. Реализовать класс `ModuleResolver`
3. Добавить unit-тесты
4. Интегрировать в `config.py`

### Этап 3: Рефакторинг ShiftRegister (2 дня)
1. Обновить `__init__` для работы с `ModuleResolver`
2. Заменить хардкод имен на локальные имена из конфига
3. Обновить метод `set_mask` для работы с локальными именами
4. Добавить тесты

### Этап 4: Рефакторинг TurnstileState (3 дня)
1. Разделить на `TurnstileStateMachine`, `TurnstileAsyncOperations`, `TurnstileConfig`
2. Интегрировать `ModuleResolver`
3. Убрать хардкод имен пинов
4. Обновить все вызовы в коде
5. Добавить тесты

### Этап 5: Рефакторинг обработчиков (2 дня)
1. Объединить `card.py` и `qr.py` в `credential.py`
2. Создать параметризованный обработчик
3. Обновить вызовы в `lgtu_application.py`
4. Добавить утилитарную функцию `find_device_config`
5. Обновить все обработчики для использования новой функции
6. Добавить тесты

### Этап 6: Рефакторинг basic_business_logic (2 дня)
1. Объединить функции бипера в одну
2. Убрать функции-обёртки для логирования
3. Объединить обработку проходов
4. Объединить обработку кнопок
5. Обновить все вызовы в коде
6. Добавить тесты

### Этап 7: Рефакторинг LGTUController (3 дня)
1. Разделить на отдельные контроллеры (QRController, CardController, PassageController)
2. Интегрировать `ModuleResolver`
3. Убрать дублирование логики
4. Добавить тесты

### Этап 8: Очистка (1 день)
1. Удалить старые файлы (`card.py`, `qr.py`)
2. Удалить дублирующиеся секции из конфига
3. Обновить документацию
4. Обновить README

### Этап 9: Тестирование (2 дня)
1. Запустить все unit-тесты
2. Запустить интеграционные тесты
3. Проверить на реальном оборудовании
4. Нагрузочное тестирование

## 5. Критерии приемки

1. **Все DRY нарушения устранены**
   - Нет дублирующего кода
   - Общие функции вынесены в утилиты
   - Параметризованные обработчики вместо дубликатов

2. **Все KISS нарушения устранены**
   - Классы имеют единую ответственность
   - Методы не превышают 50 строк
   - Понятные имена без сокращений

3. **Модульная архитектура работает**
   - `ModuleResolver` корректно разрешает имена
   - Каждый модуль работает со своими локальными именами
   - Мапинг между модулями в конфиге
   - Аппаратные модули (shift_register, mux) отделены от бизнес-логики (business)
   - Нет хардкода имен модулей в коде

4. **Обратная совместимость**
   - Старые имена из конфига работают (алиасы)
   - API не сломан для внешних систем
   - Миграция данных не требуется

5. **Тестовое покрытие**
   - Unit-тесты для всех новых классов
   - Интеграционные тесты для модульного резолвера
   - Покрытие > 80%

6. **Документация**
   - Обновлен README
   - Добавлены примеры конфигурации
   - Документация API для новых классов

## 6. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|------|------------|---------|-----------|
| Слом обратной совместимости | Средняя | Высокое | Алиасы в конфиге, поэтапная миграция |
| Ошибки в резолвинге имен | Средняя | Высокое | Unit-тесты, валидация конфига |
| Регрессия в функциональности | Низкая | Среднее | Интеграционные тесты, тестирование на железе |
| Увеличение сложности конфига | Низкая | Низкое | Документация, примеры, валидация |

## 7. Сроки реализации

- Этап 1: 1 день
- Этап 2: 1 день
- Этап 3: 2 дня
- Этап 4: 3 дня
- Этап 5: 2 дня
- Этап 6: 2 дня
- Этап 7: 3 дня
- Этап 8: 1 день
- Этап 9: 2 дня

**Итого:** 17 дней (3.4 недели)

## 8. Необходимые ресурсы

- Разработчик: 1 человек
- Тестовое оборудование: Orange Pi Zero с полным комплектом
- Code review: 1 час на каждый этап
- Документация: 4 часа

---

**Документ утвержден:** _____________________

**Дата:** _____________________
