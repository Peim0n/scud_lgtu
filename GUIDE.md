# Полный гайд по проекту LGTU Controller

Этот документ — подробное руководство по коду проекта СКУД (система контроля доступа) для Orange Pi Zero LTS. Я пишу это как опытный Python/C# программист для человека без опыта работы, который хочет понять, как всё работает.

**Для кого этот гайд**: Для новичка в программировании, который хочет понять проект с нуля. Я буду объяснять не только что где находится, но и как работает Python-код, сравнивая с понятными концепциями.

---

## Часть 1: Основы Python для понимания проекта

Если вы знаете C# или другой язык программирования, Python покажется вам простым. Но если вы новичок — давайте разберём основы.

### 1.1 Переменные и типы данных

В Python не нужно объявлять тип переменной — он определяется автоматически.

```python
# В C#:
int x = 5;
string name = "test";

# В Python:
x = 5
name = "test"
```

Основные типы:
- `int` — целые числа (1, 42, -5)
- `float` — дробные числа (3.14, 0.5)
- `str` — строки ("hello", 'world')
- `bool` — логические значения (True, False)
- `list` — список (аналог массива в C#, но динамический)
- `dict` — словарь (аналог Dictionary в C#)

```python
# Список
numbers = [1, 2, 3, 4, 5]
print(numbers[0])  # Вывод: 1

# Словарь
person = {"name": "Ivan", "age": 25}
print(person["name"])  # Вывод: Ivan
```

### 1.2 Функции

Функция в Python — это блок кода, который можно вызывать многократно.

```python
def my_function(x, y):
    return x + y

result = my_function(5, 3)  # result = 8
```

- `def` — ключевое слово для определения функции
- `return` — возвращает значение из функции
- Отступы (4 пробела) важны — они определяют блок кода

### 1.3 Классы и объекты

В Python всё — объекты. Класс — это шаблон для создания объектов.

```python
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    def say_hello(self):
        print(f"Привет, меня зовут {self.name}")

# Создание объекта
person = Person("Ivan", 25)
person.say_hello()  # Вывод: Привет, меня зовут Ivan
```

- `__init__` — конструктор (аналог конструктора в C#)
- `self` — ссылка на сам объект (аналог `this` в C#)
- Атрибуты — переменные, принадлежащие объекту (`self.name`)
- Методы — функции, принадлежащие объекту (`say_hello`)

### 1.4 Декораторы

Декоратор — это функция, которая оборачивает другую функцию. В проекте часто используется `@property`.

```python
class Person:
    def __init__(self, name):
        self._name = name  # _name — "приватный" атрибут (по договорённости)

    @property
    def name(self):
        return self._name

person = Person("Ivan")
print(person.name)  # Не нужно person.name()
```

`@property` превращает метод в свойство, которое можно вызывать без скобок.

### 1.5 Dataclass

`@dataclass` автоматически генерирует методы `__init__`, `__repr__` и др. Это удобно для классов, которые хранят только данные.

```python
from dataclasses import dataclass

@dataclass
class Person:
    name: str
    age: int

# Вместо:
# def __init__(self, name, age):
#     self.name = name
#     self.age = age

person = Person("Ivan", 25)
print(person)  # Person(name='Ivan', age=25)
```

### 1.6 Типизация

Python поддерживает подсказки типов (но не проверяет их в runtime — это только для IDE и статических анализаторов).

```python
def my_function(x: int, y: str) -> bool:
    return len(y) > x
```

- `x: int` — параметр `x` должен быть типа `int`
- `-> bool` — функция возвращает `bool`

### 1.7 Async/await

Асинхронное программирование для параллельного выполнения. В проекте это используется для команд турникета.

```python
import asyncio

async def my_async_function():
    await asyncio.sleep(1)  # Асинхронная задержка на 1 секунду
    return "done"

async def main():
    result = await my_async_function()
    print(result)

asyncio.run(main())
```

- `async def` — асинхронная функция
- `await` — ждать завершения асинхронной операции
- `asyncio.run()` — запустить асинхронный код

### 1.8 Enum

Перечисление — набор именованных констант.

```python
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

print(Color.RED)  # Color.RED
print(Color.RED.value)  # 1
```

### 1.9 Абстрактные классы

Класс, который нельзя создать напрямую, только наследовать. В проекте это используется для `AccessDevice`.

```python
from abc import ABC, abstractmethod

class Animal(ABC):
    @abstractmethod
    def make_sound(self):
        pass

class Dog(Animal):
    def make_sound(self):
        return "Гав"

# animal = Animal()  # Ошибка! Нельзя создать абстрактный класс
dog = Dog()  # OK
print(dog.make_sound())  # Гав
```

### 1.10 Импорты

```python
# Импорт модуля
import os

# Импорт конкретного класса
from datetime import datetime

# Импорт с псевдонимом
import asyncio as aio

# Импорт из подпакета
from scud_lgtu.domain.events import AccessGranted
```

### 1.11 Исключения

Обработка ошибок в Python.

```python
try:
    result = 10 / 0
except ZeroDivisionError:
    print("Деление на ноль!")
except Exception as e:
    print(f"Ошибка: {e}")
finally:
    print("Выполняется всегда")
```

### 1.12 f-strings

Форматирование строк в Python 3.6+.

```python
name = "Ivan"
age = 25
print(f"Меня зовут {name}, мне {age} лет")
```

### 1.13 List comprehension

Генерация списков в одну строку.

```python
numbers = [1, 2, 3, 4, 5]
squared = [x * x for x in numbers]  # [1, 4, 9, 16, 25]
```

### 1.14 Lambda

Анонимные функции.

```python
square = lambda x: x * x
print(square(5))  # 25
```

---

## Часть 2: Архитектура проекта

### 2.1 Что такое Clean Architecture?

Clean Architecture — это паттерн, который разделяет код на слои по ответственности. Это как разделение ответственности в C# (DAL, BLL, UI), но более строгое.

### 2.2 Зачем нужна Clean Architecture?

- **Независимость от фреймворков**: бизнес-логика не зависит от конкретных библиотек
- **Тестируемость**: можно тестировать бизнес-логику без железа
- **Масштабируемость**: легко добавлять новые устройства
- **Поддерживаемость**: изменения в одном слое не ломают другие

### 2.3 Три слоя в проекте

#### Domain Layer (доменный слой)
- **Что это**: Бизнес-логика, независимая от оборудования
- **Где**: `scud_lgtu/domain/`
- **Что там**: Сущности, события, политики доступа, базовые классы устройств
- **Пример**: Проверка доступа, состояния турникета, типы токенов
- **Зачем**: Чтобы бизнес-логика не зависела от GPIO, I2C и т.д.

#### Application Layer (прикладной слой)
- **Что это**: Оркестрация, связывает домен с инфраструктурой
- **Где**: `scud_lgtu/application/`
- **Что там**: LGTUApplication, сервисы, команды
- **Пример**: Преобразование событий от оборудования в доменные события
- **Зачем**: Чтобы бизнес-логика не знала о железе, а железо не знало о бизнес-логике

#### Infrastructure Layer (инфраструктурный слой)
- **Что это**: Работа с оборудованием
- **Где**: `scud_lgtu/infrastructure/`
- **Что там**: GPIO, Wiegand, Serial, ShiftRegister, конфигурация, кэш
- **Пример**: Чтение GPIO, отправка данных в сдвиговый регистр
- **Зачем**: Чтобы бизнес-логика не зависела от конкретного железа

### 2.4 Правило зависимости

```
Domain ← Application ← Infrastructure
```

- Domain не зависит ни от кого
- Application зависит от Domain
- Infrastructure зависит от Application и Domain

Это значит, что:
- Domain можно тестировать без Application и Infrastructure
- Application можно тестировать без Infrastructure
- Infrastructure можно менять без изменения Domain и Application

---

## Часть 3: Структура проекта

```
scud_lgtu/
├── application/              # Прикладной слой
│   ├── lgtu_application.py  # Главный оркестратор
│   ├── commands.py          # Команды для ScudEngine
│   └── services/            # Сервисы (синхронизация с бэкендом)
├── domain/                  # Доменный слой
│   ├── access_device.py     # Базовый класс для устройств доступа
│   ├── access.py            # Политика доступа
│   ├── enums.py             # Перечисления (Direction, TokenType, Result)
│   ├── events.py            # Доменные события
│   └── models.py            # Модели данных (OutputCommand)
├── infrastructure/          # Инфраструктурный слой
│   ├── backend/             # Адаптер бэкенда
│   ├── cache/               # Адаптер кэша
│   ├── config/              # Конфигурация (ModuleResolver)
│   ├── devices/turnstile/   # Устройство турникета
│   │   ├── turnstile_device.py  # FSM турникета
│   │   └── commands.py          # Асинхронные команды
│   ├── firmware/            # Работа с железом
│   │   ├── gpio/            # GPIO, Wiegand, ShiftRegister
│   │   └── serial/          # Serial порты
│   ├── persistence/         # Хранение событий
│   └── engine.py            # Главный движок (ScudEngine)
├── interfaces/             # Интерфейсы (CLI)
│   └── cli.py               # Командная строка
├── tests/                   # Тесты
├── config.yml               # Конфигурация
└── run_lgtu_controller.py   # Точка входа
```

---

## Часть 4: Конфигурация

### 4.1 Файл конфигурации: `config.yml`

Это YAML-файл, который описывает всё оборудование и настройки проекта. YAML — это формат для конфигураций, похожий на JSON, но более читаемый.

### 4.2 Основные секции конфигурации

```yaml
gpiod_controller:        # Настройки GPIO контроллера
  chip: "/dev/gpiochip0"
  pins: {...}

shift_register:          # Настройки сдвигового регистра
  ser_data: "PA6"
  ser_clk: "PA19"
  ser_latch: "PA7"
  reg_len: 16
  pins: {...}             # Мапинг имён в offset'ы

wiegand:                 # Настройки считывателей Wiegand
  readers:
    - id: "entry_reader"
      d0: "PA10"
      d1: "PA11"
      format: 26

serial:                  # Настройки Serial портов
  ports:
    - id: "qr_decoder"
      port: "/dev/ttyS0"
      baudrate: 115200

devices:                 # Устройства доступа
  turnstile:             # Турникет
    entry_relay: "rel1"
    exit_relay: "rel2"
    main_buzzer: "buz"
    entry_green: "led1"
    entry_red: "led2"
    exit_green: "led3"
    exit_red: "led4"

timings:                 # Тайминги
  business:
    auth_timeout_s: 5.0
    indicator_duration_s: 2.0
  turnstile:
    relay_open_duration_s: 7.0
    button_timer_duration_s: 7.0

backend:                 # Настройки бэкенда
  url: "http://backend:8000"
  sync_interval_s: 60

logging:                 # Настройки логирования
  level: "INFO"
  file: "/var/log/scud_lgtu.log"
```

### 4.3 Как изменить конфигурацию

#### Добавить новый пин GPIO

```yaml
gpiod_controller:
  chip: "/dev/gpiochip0"
  pins:
    my_pin: "PA12"
```

#### Добавить новый выход в сдвиговый регистр

```yaml
shift_register:
  ser_data: "PA6"
  ser_clk: "PA19"
  ser_latch: "PA7"
  reg_len: 16
  pins:
    my_relay:
      offset: 5        # Номер бита в регистре (0-15)
      inverted: false  # Инвертировать сигнал
```

#### Добавить новый считыватель Wiegand

```yaml
wiegand:
  readers:
    - id: "my_reader"
      d0: "PA13"
      d1: "PA14"
      format: 34
```

#### Изменить тайминги

```yaml
timings:
  turnstile:
    relay_open_duration_s: 10.0  # Время открытия реле
```

---

## Часть 5: Domain Layer (доменный слой)

### 5.1 `domain/access_device.py` — Базовый класс для устройств

Это базовый класс для всех устройств доступа (турникет, калитка, дверь).

```python
from abc import ABC, abstractmethod
from typing import Optional, Any

class AccessDevice(ABC):
    """Базовый класс для устройств контроля доступа."""

    def __init__(self, device_id: str, timings: dict, resolver: Any):
        self._device_id = device_id
        self._resolver = resolver
        self._locked = False
        self._load_config(timings)

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    @abstractmethod
    def current_state_label(self) -> str:
        """Текущее состояние FSM устройства."""
        pass

    @property
    @abstractmethod
    def is_alarm_active(self) -> bool:
        """Активна ли пожарная тревога."""
        pass

    @property
    def locked(self) -> bool:
        """Заблокировано ли устройство админом."""
        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
        self._locked = value

    @abstractmethod
    def handle(self, event) -> Optional[Any]:
        """Обработать доменное событие и вернуть команду."""
        pass
```

**Разбор кода:**
- `ABC` — абстрактный базовый класс, нельзя создать напрямую
- `@abstractmethod` — метод должен быть реализован в наследниках
- `@property` — свойство, вызывается без скобок
- `@locked.setter` — сеттер для свойства

**Как использовать:**

```python
class MyDevice(AccessDevice):
    def __init__(self, timings: dict, resolver: Any):
        super().__init__(device_id="my_device", timings=timings, resolver=resolver)
        self._mode = "closed"

    @property
    def current_state_label(self) -> str:
        return self._mode

    @property
    def is_alarm_active(self) -> bool:
        return self._alarm

    def handle(self, event) -> Optional[Command]:
        # Обработка событий
        pass
```

### 5.2 `domain/access.py` — Политика доступа

Определяет, кому разрешён проход.

```python
@dataclass
class AccessDecision:
    allowed: bool
    reason: str

class AccessPolicy:
    def check_access(self, credential: Credential) -> AccessDecision:
        # Проверка доступа
        if credential.token in self._access_cache:
            return AccessDecision(allowed=True, reason="access_granted")
        return AccessDecision(allowed=False, reason="not_found")
```

**Разбор кода:**
- `@dataclass` — автоматически генерирует `__init__` и другие методы
- `AccessDecision` — результат проверки доступа

### 5.3 `domain/events.py` — Доменные события

События, которые используются в системе.

```python
@dataclass
class AccessGranted:
    token: str
    user_id: int
    direction: str

@dataclass
class AccessDenied:
    token: str
    reason: str
    direction: str

@dataclass
class DeviceCommand:
    command: str

@dataclass
class AlarmChanged:
    active: bool

@dataclass
class PassageDetected:
    direction: str
```

**Разбор кода:**
- `@dataclass` — упрощает создание классов для хранения данных
- События — это просто данные, которые передаются между слоями

### 5.4 `domain/enums.py` — Перечисления

```python
from enum import Enum

class DirectionEnum(str, Enum):
    IN = "in"
    OUT = "out"

class TokenTypeEnum(str, Enum):
    PHONE = "phone"
    MAXID = "maxid"
    CARDID = "cardid"
    # ...

class ResultEnum(str, Enum):
    PASS = "pass"
    TIMEOUT = "timeout"
    DENIED = "denied"
    # ...
```

**Разбор кода:**
- `Enum` — перечисление, набор именованных констант
- `str` — наследование от str, чтобы можно было использовать как строки

### 5.5 `domain/models.py` — Модели данных

```python
@dataclass
class OutputCommand:
    name: str
    state: bool

@dataclass
class Credential:
    token_type: TokenTypeEnum
    value: str
    encrypted: bool = False
```

**Разбор кода:**
- `OutputCommand` — команда для выхода (имя пина, состояние)
- `Credential` — данные для проверки доступа

---

## Часть 6: Application Layer (прикладной слой)

### 6.1 `application/lgtu_application.py` — Главный оркестратор

Это главный класс, который связывает всё вместе.

```python
class LGTUApplication:
    def __init__(self, config: dict, engine: ScudEngine):
        self._config = config
        self._engine = engine
        self._access_policy = AccessPolicy(config)
        self._turnstile_device = TurnstileDevice(config, resolver)
        self._command_runner = _CommandRunner(engine)

    def run(self) -> None:
        """Главный цикл обработки событий."""
        while not self._stop_event.is_set():
            event = self._engine.get_event_queue().get(timeout=0.1)
            self._handle_hardware_event(event)

    def _handle_hardware_event(self, event: ScudEvent) -> None:
        """Обработка события от оборудования."""
        if event.type == EventType.CARD_READ:
            self._handle_card_read(event)
        elif event.type == EventType.BUTTON_PRESSED:
            self._handle_button_pressed(event)
        # ...

    def _handle_card_read(self, event: ScudEvent) -> None:
        """Обработка считывания карты."""
        credential = Credential(...)
        decision = self._access_policy.check_access(credential)

        if decision.allowed:
            domain_event = AccessGranted(...)
        else:
            domain_event = AccessDenied(...)

        command = self._turnstile_device.handle(domain_event)
        if command:
            self._command_runner.run(command)
```

**Разбор кода:**
- `LGTUApplication` — главный оркестратор
- `run()` — главный цикл, получает события из очереди
- `_handle_hardware_event()` — обрабатывает события от оборудования
- `_handle_card_read()` — обрабатывает считывание карты
- `_command_runner` — выполняет команды

### 6.2 `application/commands.py` — Команды для ScudEngine

Команды, которые бизнес-логика отправляет в инфраструктурный слой.

```python
from enum import Enum

class CommandTarget(str, Enum):
    SHIFT = "shift"
    GPIO = "gpio"
    OUTPUT = "output"
    ENGINE = "engine"

class CommandAction(str, Enum):
    SET_MASK = "set_mask"
    WRITE_PIN = "write_pin"
    # ...

@dataclass
class ScudCommand:
    target: CommandTarget
    action: CommandAction
    payload: dict
```

**Разбор кода:**
- `CommandTarget` — цель команды (какой модуль обрабатывает)
- `CommandAction` — действие команды
- `ScudCommand` — сама команда

### 6.3 `application/services/sync_service.py` — Синхронизация с бэкендом

Периодически синхронизирует события и список доступа с бэкендом.

```python
class SyncService:
    def __init__(self, backend_adapter, event_store):
        self._backend = backend_adapter
        self._event_store = event_store

    def sync_passage_events(self) -> None:
        """Синхронизировать события прохода с бэкендом."""
        events = self._event_store.get_unsent_events()
        for event in events:
            self._backend.send_event(event)
        self._event_store.mark_events_sent(events)
```

**Разбор кода:**
- `SyncService` — сервис синхронизации
- `sync_passage_events()` — отправляет события на бэкенд

---

## Часть 7: Infrastructure Layer (инфраструктурный слой)

### 7.1 `infrastructure/engine.py` — ScudEngine

Главный движок, который запускает все hardware-модули как потоки.

```python
class ScudEngine:
    def __init__(self, config: dict):
        self._config = config
        self._event_queue = Queue()
        self._command_queue = Queue()
        self._stop_event = Event()
        self._threads = []

    def start(self) -> None:
        """Запустить все потоки."""
        # Запуск GPIO контроллера
        self._gpiod_thread = threading.Thread(target=self._gpiod_controller.run)
        self._gpiod_thread.start()

        # Запуск Wiegand считывателей
        for reader in self._wiegand_readers:
            thread = threading.Thread(target=reader.run)
            thread.start()
            self._threads.append(thread)

        # ...

    def stop(self) -> None:
        """Остановить все потоки."""
        self._stop_event.set()
        for thread in self._threads:
            thread.join()

    def send_command(self, command: ScudCommand) -> None:
        """Отправить команду в очередь команд."""
        self._command_queue.put(command)
```

**Разбор кода:**
- `ScudEngine` — главный движок
- `start()` — запускает все потоки
- `stop()` — останавливает все потоки
- `send_command()` — отправляет команду в очередь
- `Queue` — потокобезопасная очередь
- `Event` — событие для остановки потоков
- `threading.Thread` — поток выполнения

### 7.2 `infrastructure/firmware/gpio/controller.py` — GpiodPinController

Абстракция над GPIO через libgpiod.

```python
class GpiodPinController:
    def __init__(self, chip_path: str):
        self._chip = gpiod.Chip(chip_path)
        self._lines = {}
        self._lock = threading.Lock()

    def read_pin(self, pin_name: str) -> bool:
        """Прочитать пин."""
        with self._lock:
            line = self._get_line(pin_name)
            return line.get_value()

    def write_pin(self, pin_name: str, value: bool) -> None:
        """Записать в пин."""
        with self._lock:
            line = self._get_line(pin_name)
            line.set_value(value)

    def write_pin_nolock(self, pin_name: str, value: bool) -> None:
        """Записать в пин без блокировки (если уже захвачен lock)."""
        line = self._get_line(pin_name)
        line.set_value(value)
```

**Разбор кода:**
- `GpiodPinController` — абстракция над GPIO
- `read_pin()` — прочитать пин
- `write_pin()` — записать в пин
- `write_pin_nolock()` — записать без блокировки (для оптимизации)
- `threading.Lock` — блокировка для потокобезопасности

### 7.3 `infrastructure/firmware/gpio/wiegand_reader.py` — WiegandReader

Поток для считывания карт по протоколу Wiegand.

```python
class WiegandReader:
    def __init__(self, d0_pin: str, d1_pin: str, format: int, queue: Queue):
        self._d0_pin = d0_pin
        self._d1_pin = d1_pin
        self._format = format
        self._queue = queue
        self._bits = []
        self._last_bit_time = 0

    def run(self) -> None:
        """Главный цикл считывания."""
        while not self._stop_event.is_set():
            # Ожидание изменения на пинах
            if self._wait_for_bit():
                self._process_bit()
                self._check_timeout()

    def _wait_for_bit(self) -> bool:
        """Ожидание изменения на пинах."""
        # Использование select для ожидания
        # ...

    def _process_bit(self) -> None:
        """Обработка бита."""
        # Добавление бита в буфер
        # ...

    def _check_timeout(self) -> None:
        """Проверка таймаута для завершения карты."""
        # Если прошло достаточно времени без битов — карта готова
        # ...
```

**Разбор кода:**
- `WiegandReader` — поток для считывания карт
- `run()` — главный цикл
- `_wait_for_bit()` — ожидание изменения на пинах
- `_process_bit()` — обработка бита
- `_check_timeout()` — проверка таймаута

### 7.4 `infrastructure/firmware/gpio/shift_register.py` — ShiftRegister

Поток для записи данных в сдвиговый регистр.

```python
class ShiftRegister:
    def __init__(self, controller: GpiodPinController, input_queue: Queue, lock: Lock):
        self._controller = controller
        self._input_queue = input_queue
        self._lock = lock
        self._ser_data_pin = "PA6"
        self._ser_clk_pin = "PA19"
        self._ser_latch_pin = "PA7"
        self._n = 16

    def run(self) -> None:
        """Главный цикл записи."""
        while not self._stop_event.is_set():
            try:
                value = self._input_queue.get(timeout=0.1)
                with self._lock:
                    self._work_shift(value)
            except Empty:
                continue

    def _work_shift(self, value: int) -> None:
        """Записать значение в сдвиговый регистр."""
        wp = self._controller.write_pin_nolock
        for i in range(self._n - 1, -1, -1):
            bit = (value >> i) & 1
            wp(self._ser_data_pin, bit)
            wp(self._ser_clk_pin, 0)
            wp(self._ser_clk_pin, 1)
            wp(self._ser_clk_pin, 0)
        # Защёлка
        wp(self._ser_latch_pin, 0)
        wp(self._ser_latch_pin, 1)
        wp(self._ser_latch_pin, 0)
```

**Разбор кода:**
- `ShiftRegister` — поток для записи в сдвиговый регистр
- `run()` — главный цикл
- `_work_shift()` — запись значения в регистр
- Сдвиговый регистр работает по принципу: для каждого бита устанавливаем DATA, импульс CLK, после всех битов — импульс LATCH

### 7.5 `infrastructure/devices/turnstile/turnstile_device.py` — TurnstileDevice

FSM турникета. Наследуется от `AccessDevice`.

```python
class TurnstileDevice(AccessDevice):
    def __init__(self, auth_timeout: float, timings: dict, resolver: Any):
        super().__init__(device_id="turnstile", timings=timings, resolver=resolver)
        self._mode = "idle"
        self._alarm = False
        self.current_token: Optional[str] = None
        self.current_user_id: Optional[int] = None
        self._auth_timeout = auth_timeout

    def _load_io_mappings(self) -> None:
        """Загрузить имена выходов турникета."""
        self._resolver.set_context("turnstile")
        self.entry_relay = self._resolver.resolve("entry_relay")
        self.exit_relay = self._resolver.resolve("exit_relay")
        # ...

    def handle(self, event) -> Optional[Command]:
        """Обработать доменное событие и вернуть команду."""
        if isinstance(event, AccessGranted):
            return self._on_access_granted(event)
        if isinstance(event, AccessDenied):
            return self._on_access_denied(event)
        if isinstance(event, DeviceCommand):
            return self._on_device_command(event)
        # ...

    def _on_access_granted(self, event: AccessGranted) -> Command:
        """Обработка доступа разрешён."""
        self.current_token = event.token
        self.current_user_id = event.user_id
        if event.direction == "entry":
            self._mode = "entry_open"
            return OpenEntryCommand(self, self._relay_timeout)
        self._mode = "exit_open"
        return OpenExitCommand(self, self._relay_timeout)
```

**Разбор кода:**
- `TurnstileDevice` — FSM турникета
- `handle()` — обрабатывает события и возвращает команды
- `_on_access_granted()` — обрабатывает доступ разрешён
- `_mode` — текущее состояние (idle, entry_open, exit_open и т.д.)

### 7.6 `infrastructure/devices/turnstile/commands.py` — Асинхронные команды

Команды, которые выполняются турникетом.

```python
class OpenEntryCommand(_RelayCommand):
    meta = CommandMeta(name="open_entry", conflicts=("open_exit",))

    async def run(self, executor) -> None:
        await executor.apply([
            OutputCommand(name=self._device.entry_relay, state=True),
            OutputCommand(name=self._device.entry_green, state=True),
            OutputCommand(name=self._device.entry_red, state=False),
        ])
        await asyncio.sleep(self._relay_timeout)
        await executor.apply([
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
        ])

class CloseCommand(_RelayCommand):
    meta = CommandMeta(name="close")

    async def run(self, executor) -> None:
        await executor.apply([
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
        ])
```

**Разбор кода:**
- `OpenEntryCommand` — открыть вход
- `CloseCommand` — закрыть
- `async def run()` — асинхронный метод выполнения
- `await executor.apply()` — применить команды к выходам
- `await asyncio.sleep()` — асинхронная задержка

### 7.7 `infrastructure/config/module_resolver.py` — ModuleResolver

Резолвер имён для конфигурации.

```python
class ModuleResolver:
    def __init__(self, config: dict):
        self._config = config
        self._context = None

    def set_context(self, context: str) -> None:
        """Установить контекст (например, 'turnstile')."""
        self._context = context

    def resolve(self, name: str) -> str:
        """Разрешить имя в значение из конфигурации."""
        if self._context:
            path = f"{self._context}.{name}"
            return self._get_value(path)
        return self._get_value(name)

    def _get_value(self, path: str) -> str:
        """Получить значение по пути."""
        parts = path.split(".")
        value = self._config
        for part in parts:
            value = value[part]
        return value
```

**Разбор кода:**
- `ModuleResolver` — резолвер имён
- `set_context()` — установить контекст
- `resolve()` — разрешить имя в значение
- `_get_value()` — получить значение по пути

### 7.8 `infrastructure/persistence/event_store.py` — Хранение событий

In-memory хранилище событий прохода.

```python
@dataclass
class ScudEvent:
    type: EventType
    source: EventSource
    payload: dict
    timestamp: datetime

class EventStore:
    def __init__(self):
        self._events: list[ScudEvent] = []

    def append(self, event: ScudEvent) -> None:
        """Добавить событие."""
        self._events.append(event)

    def get_unsent_events(self) -> list[ScudEvent]:
        """Получить неотправленные события."""
        return [e for e in self._events if not e.sent]

    def mark_events_sent(self, events: list[ScudEvent]) -> None:
        """Пометить события как отправленные."""
        for event in events:
            event.sent = True
```

**Разбор кода:**
- `ScudEvent` — событие
- `EventStore` — хранилище событий
- `append()` — добавить событие
- `get_unsent_events()` — получить неотправленные
- `mark_events_sent()` — пометить как отправленные

---

## Часть 8: Как работает турникет

### 8.1 Полный цикл прохода

#### Шаг 1: Карта считывается (WiegandReader)

```python
# WiegandReader.run()
while not self._stop_event.is_set():
    if self._wait_for_bit():
        self._process_bit()
        self._check_timeout()
```

1. WiegandReader ждёт изменения на пинах D0/D1
2. При изменении — добавляет бит в буфер
3. При таймауте — декодирует карту и отправляет событие в очередь

#### Шаг 2: Событие обрабатывается (LGTUApplication)

```python
# LGTUApplication._handle_hardware_event()
if event.type == EventType.CARD_READ:
    self._handle_card_read(event)
```

1. LGTUApplication получает событие из очереди
2. Преобразует в доменное событие `CardRead`
3. Проверяет доступ через `AccessPolicy`

#### Шаг 3: Доступ проверяется (AccessPolicy)

```python
# AccessPolicy.check_access()
if credential.token in self._access_cache:
    return AccessDecision(allowed=True, reason="access_granted")
return AccessDecision(allowed=False, reason="not_found")
```

1. AccessPolicy ищет токен в локальном кэше
2. Возвращает `AccessDecision(allowed=True/False)`

#### Шаг 4: Событие отправляется в устройство (TurnstileDevice)

```python
# LGTUApplication._handle_card_read()
if decision.allowed:
    domain_event = AccessGranted(...)
else:
    domain_event = AccessDenied(...)

command = self._turnstile_device.handle(domain_event)
```

1. LGTUApplication создаёт `AccessGranted` или `AccessDenied`
2. Отправляет в `TurnstileDevice.handle()`

#### Шаг 5: FSM обрабатывает событие (TurnstileDevice)

```python
# TurnstileDevice._on_access_granted()
if event.direction == "entry":
    self._mode = "entry_open"
    return OpenEntryCommand(self, self._relay_timeout)
```

1. TurnstileDevice меняет состояние (например, idle -> entry_open)
2. Возвращает команду (например, `OpenEntryCommand`)

#### Шаг 6: Команда выполняется (_CommandRunner)

```python
# _CommandRunner.run()
async def run(self, command: Command) -> None:
    await command.run(self._executor)
```

1. _CommandRunner запускает асинхронную команду
2. Команда включает реле через ShiftRegister
3. После таймаута выключает реле

#### Шаг 7: Проход обнаружен (PassageDetected)

```python
# TurnstileDevice._on_passage_detected()
self._mode = "idle"
self.current_token = None
self.current_user_id = None
return CloseCommand(self)
```

1. Датчик прохода срабатывает
2. TurnstileDevice получает `PassageDetected`
3. Возвращается в состояние idle

### 8.2 Диаграмма состояний

```
         AccessGranted (entry)
    idle ───────────────────────> entry_open
         │                         │
         │ AccessGranted (exit)    │ PassageDetected
         ▼                         ▼
    exit_open <────────────────────┘
         │
         │ unlock_entry
         ▼
    unlocked_entry ──────> idle (close)
         │
         │ unlock_exit
         ▼
    unlocked_exit ───────> idle (close)
         │
         │ lock
         ▼
    blocked ───────────────> idle (unlock)
         │
         │ AlarmChanged(active=True)
         ▼
    alarm ─────────────────> idle (AlarmChanged(active=False))
```

**Состояния:**
- `idle` — нормально закрыт
- `entry_open` — разовый вход
- `exit_open` — разовый выход
- `unlocked_entry` — разблокирован на вход
- `unlocked_exit` — разблокирован на выход
- `blocked` — заблокирован админом
- `alarm` — пожарная тревога

---

## Часть 9: Как добавить новое устройство

Например, добавить калитку (gate).

### Шаг 1: Создать класс устройства

```python
# infrastructure/devices/gate/gate_device.py
from scud_lgtu.domain.access_device import AccessDevice
from scud_lgtu.domain.events import AccessGranted, DeviceCommand
from scud_lgtu.infrastructure.devices.gate.commands import OpenGateCommand, CloseGateCommand

class GateDevice(AccessDevice):
    def __init__(self, timings: dict, resolver: Any):
        super().__init__(device_id="gate", timings=timings, resolver=resolver)
        self._mode = "closed"

    @property
    def current_state_label(self) -> str:
        return self._mode

    @property
    def is_alarm_active(self) -> bool:
        return self._alarm

    def handle(self, event) -> Optional[Command]:
        if isinstance(event, AccessGranted):
            self._mode = "open"
            return OpenGateCommand(self, self._relay_timeout)
        if isinstance(event, DeviceCommand):
            if event.command == "close":
                self._mode = "closed"
                return CloseGateCommand(self)
        return None

    def _load_io_mappings(self) -> None:
        self._resolver.set_context("gate")
        self.gate_relay = self._resolver.resolve("gate_relay")
```

### Шаг 2: Создать команды

```python
# infrastructure/devices/gate/commands.py
class OpenGateCommand(_RelayCommand):
    meta = CommandMeta(name="open_gate")

    async def run(self, executor) -> None:
        await executor.apply([
            OutputCommand(name=self._device.gate_relay, state=True),
        ])
        await asyncio.sleep(self._relay_timeout)
        await executor.apply([
            OutputCommand(name=self._device.gate_relay, state=False),
        ])

class CloseGateCommand(_RelayCommand):
    meta = CommandMeta(name="close_gate")

    async def run(self, executor) -> None:
        await executor.apply([
            OutputCommand(name=self._device.gate_relay, state=False),
        ])
```

### Шаг 3: Добавить конфигурацию

```yaml
# config.yml
devices:
  gate:
    gate_relay: "rel5"

timings:
  gate:
    relay_open_duration_s: 10.0
```

### Шаг 4: Интегрировать в приложение

```python
# application/lgtu_application.py
from scud_lgtu.infrastructure.devices.gate.gate_device import GateDevice

class LGTUApplication:
    def __init__(self, ...):
        # ...
        self.gate_device = GateDevice(timings, resolver)

    def _handle_access_granted(self, event: AccessGranted) -> None:
        if event.device_id == "gate":
            command = self.gate_device.handle(event)
        else:
            command = self.turnstile_device.handle(event)
        # ...
```

---

## Часть 10: Как изменить бизнес-логику

### 10.1 Изменить логику доступа

Откройте `domain/access.py` и измените метод `check_access()`:

```python
def check_access(self, credential: Credential) -> AccessDecision:
    # Добавить проверку по группам
    if credential.user_id in ADMIN_GROUP:
        return AccessDecision(allowed=True, reason="admin")

    # Добавить временные ограничения
    if not self._is_working_hours():
        return AccessDecision(allowed=False, reason="outside_hours")

    # ... остальная логика
```

### 10.2 Изменить FSM турникета

Откройте `infrastructure/devices/turnstile/turnstile_device.py` и измените нужный метод:

```python
def _on_device_command(self, event: DeviceCommand) -> Optional[Command]:
    # Добавить новую команду
    if event.command == "my_command":
        self._mode = "my_state"
        return MyCommand(self)
    # ... остальная логика
```

### 10.3 Изменить тайминги

Откройте `config.yml` и измените нужные тайминги:

```yaml
timings:
  turnstile:
    relay_open_duration_s: 10.0  # Увеличить время открытия
  business:
    auth_timeout_s: 3.0         # Уменьшить таймаут авторизации
```

---

## Часть 11: Запуск и тестирование

### 11.1 Запуск приложения

```bash
python run_lgtu_controller.py
```

### 11.2 Запуск CLI

```bash
python -m scud_lgtu.interfaces.cli
```

### 11.3 Запуск тестов

```bash
pytest
```

### 11.4 Запуск конкретного теста

```bash
pytest tests/test_turnstile_fsm.py::TestIdleTransitions::test_access_granted_entry
```

### 11.5 Запуск с отладкой

```bash
pytest -vv -s tests/test_turnstile_fsm.py
```

---

## Часть 12: Где что искать

| Задача | Файл |
|--------|------|
| Изменить FSM турникета | `infrastructure/devices/turnstile/turnstile_device.py` |
| Изменить логику доступа | `domain/access.py` |
| Добавить новую команду | `infrastructure/devices/turnstile/commands.py` |
| Изменить конфигурацию | `config.yml` |
| Добавить новый считыватель | `config.yml` (секция `wiegand`) |
| Добавить новый выход | `config.yml` (секция `shift_register.pins`) |
| Изменить обработку событий | `application/lgtu_application.py` |
| Добавить новое устройство | Создать класс в `infrastructure/devices/` |
| Изменить логирование | `config.yml` (секция `logging`) |
| Изменить синхронизацию с бэкендом | `application/services/sync_service.py` |

---

## Часть 13: Частые задачи

### 13.1 Как изменить время открытия турникета?

```yaml
# config.yml
timings:
  turnstile:
    relay_open_duration_s: 10.0  # Секунды
```

### 13.2 Как добавить новый тип токена?

```python
# domain/enums.py
class TokenTypeEnum(str, Enum):
    MY_TOKEN = "my_token"
    # ... остальные типы
```

### 13.3 Как изменить логику при тревоге?

```python
# infrastructure/devices/turnstile/turnstile_device.py
def _on_alarm_changed(self, event: AlarmChanged) -> Optional[Command]:
    if event.active:
        # Своя логика при тревоге
        self._alarm = True
        self._mode = "alarm"
        return AlarmCommand(self)
    # ...
```

### 13.4 Как добавить новый админский режим?

```python
# infrastructure/devices/turnstile/turnstile_device.py
def _on_device_command(self, event: DeviceCommand) -> Optional[Command]:
    if event.command == "my_mode":
        self._mode = "my_mode"
        return MyModeCommand(self)
    # ...
```

### 13.5 Как изменить логирование?

```yaml
# config.yml
logging:
  level: "DEBUG"  # DEBUG, INFO, WARNING, ERROR
  file: "/var/log/scud_lgtu.log"
```

---

## Часть 14: Резюме

### 14.1 Ключевые моменты

- **Domain Layer** — бизнес-логика, независимая от железа
- **Application Layer** — оркестрация, связывает домен с инфраструктурой
- **Infrastructure Layer** — работа с оборудованием
- **Config** — всё оборудование настраивается через `config.yml`
- **Устройства** — наследуются от `AccessDevice`
- **FSM** — в `turnstile_device.py`
- **Команды** — в `commands.py`
- **Тесты** — в `tests/`

### 14.2 Правило изменения

Если нужно что-то изменить, сначала определи, какой слой затронут:
- Бизнес-логика → Domain Layer
- Оркестрация → Application Layer
- Железо → Infrastructure Layer
- Конфигурация → config.yml

### 14.3 Python-конструкции, которые нужно знать

- Классы и объекты
- Декораторы (@property, @dataclass)
- Async/await
- Enum
- Абстрактные классы
- Типизация
- Исключения
- f-strings
- List comprehension
- Lambda

---

## Часть 15: Полезные ресурсы

### 15.1 Документация Python

- [Официальная документация Python](https://docs.python.org/3/)
- [Python для начинающих](https://pythonworld.ru/samouchitel-python.html)

### 15.2 Документация проекта

- `ARCHITECTURE.md` — архитектура проекта
- `DATA_FLOW_DIAGRAM.md` — диаграммы потоков данных
- `DEPLOYMENT.md` — инструкция по развёртыванию

### 15.3 Инструменты

- `pytest` — тестирование
- `pylint` — анализ кода
- `black` — форматирование кода

---

## Заключение

Этот гайд должен дать вам полное понимание проекта. Если что-то непонятно — спрашивайте. Главное — помните, что проект разделён на слои, и изменения нужно вносить в правильный слой.

Удачи!
