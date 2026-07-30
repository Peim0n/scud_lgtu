# ТЗ: Исправление нарушений Clean Architecture в SCUD LGTU

## Контекст

Проект `scud_lgtu` реализует СКУД для Orange Pi Zero LTS по принципам Clean Architecture
с четырьмя слоями: Domain, Application, Infrastructure, Interfaces. Архитектурный контракт
между слоями строится на портах (интерфейсах) и событиях.

**Принцип:** каждый слой зависит только от интерфейсов соседнего слоя, но не от его
внутренней реализации. Главное — правильно публиковать состояния через границы слоёв
через определённые контракты (порты и события).

**Фактически:** контракт между слоями нарушается в 21 месте. Это делает невозможной
замену инфраструктурных компонентов (например, `LocalAccessCache` → Redis, `EventStore` →
PostgreSQL, `ScudEngine` → mock) без изменения Domain и Application.

---

## Нарушение 1: LGTUApplication напрямую импортирует Infrastructure

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:30-35`

### Описание
`LGTUApplication` (слой Application) напрямую импортирует конкретные классы из Infrastructure:

```python
from scud_lgtu.infrastructure.core.engine import ScudEngine
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder
from scud_lgtu.infrastructure.persistence.event_store import EventStore, PassageEvent, EventType, EventSource
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.sound.player import SoundPlayer
```

### Последствия
- Application жёстко привязан к конкретным реализациям Infrastructure.
- Невозможно заменить `LocalAccessCache` на другой кэш, `EventStore` на БД,
  `BackendClient` на mock без изменения кода `LGTUApplication`.
- Нарушается Dependency Inversion Principle: Application зависит на конкретные классы,
  а не на абстракции (порты Domain).

### Требования к исправлению
1. `LGTUApplication` должен принимать в конструкторе только порты из
   `domain/access/ports/ports.py` и доменные сервисы, созданные в `bootstrap.py`.
2. Удалить прямые импорты Infrastructure-классов из `lgtu_application.py`.
3. Конструктор `LGTUApplication` должен принимать:
   - `event_source` — источник сырых событий (интерфейс с методом `get_event()`),
   - `access_repository: AccessRepository` — порт доступа,
   - `event_log: EventLog` — порт журнала,
   - `actuator: Actuator` — порт исполнительных механизмов,
   - `sound_output: SoundOutput` — порт звука,
   - `backend_gateway: BackendGateway` — порт бэкенда,
   - `turnstile: TurnstileState` — доменный FSM,
   - `access_policy: AccessPolicy` — доменный сервис,
   - `passage_tracker: PassageTracker` — доменный сервис,
   - `event_bus: EventBus` — шина событий Application,
   - `config: dict` — конфигурация (только для чтения устройств/таймингов),
   - `devices: dict` — мапинг устройств.
4. Все создания компонентов перенести в `bootstrap.py`.

### Критерии приёмки
- В `lgtu_application.py` нет ни одного `import from scud_lgtu.infrastructure.*`.
- `LGTUApplication` можно создать с mock-реализациями всех портов.
- `bootstrap.py` создаёт все компоненты и передаёт их в `LGTUApplication` через конструктор.

---

## Нарушение 2: LGTUApplication дублирует создание доменных компонентов

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:98-113`
`scud_lgtu/infrastructure/bootstrap/bootstrap.py` (вся функция `build_application`)

### Описание
`bootstrap.py` создаёт все компоненты: `TurnstileState`, `AccessPolicy`, `PassageTracker`,
`EventBus`, `AccessService`, `PassageService`, `SyncService`, а также адаптеры
(`AccessRepositoryAdapter`, `EventLogAdapter`, `SoundOutputAdapter`, `BackendGatewayAdapter`).

Однако `LGTUApplication.__init__` **не принимает** эти компоненты в конструкторе. Вместо
этого он принимает `engine`, `cache`, `store`, `backend`, `config`, `devices` — конкретные
инфраструктурные объекты — и **заново создаёт** свои собственные `TurnstileState`,
`AccessPolicy`, `PassageTracker`, `EventBus`, `AccessService`, `PassageService`,
`SyncService`.

В итоге:
- Компоненты и адаптеры из `bootstrap.py` **не используются** — они создаются, но
  передаются только как аргументы конструктора, которые `LGTUApplication` игнорирует
  при создании своих дубликатов.
- `LGTUApplication` создаёт `AccessPolicy(cache=cache)` где `cache` — это
  `LocalAccessCache` (инфраструктура), а не `AccessRepositoryAdapter` (адаптер порта).
- `LGTUApplication` создаёт `PassageService(store)` где `store` — это `EventStore`
  (инфраструктура), а не `EventLogAdapter` (адаптер порта).
- `LGTUApplication` создаёт `SyncService(backend, store)` где `backend` — это
  `BackendClient` (инфраструктура), а не `BackendGatewayAdapter` (адаптер порта).

### Последствия
- Адаптеры из `bootstrap.py` (`AccessRepositoryAdapter`, `EventLogAdapter`,
  `SoundOutputAdapter`, `BackendGatewayAdapter`) — мёртвый код.
- Дублирование логики создания компонентов в двух местах.
- При изменении конструктора `TurnstileState` нужно править и `bootstrap.py`, и
  `lgtu_application.py`.

### Требования к исправлению
1. Удалить создание доменных компонентов и сервисов из `LGTUApplication.__init__`.
2. Принимать все компоненты через конструктор (см. нарушение 1).
3. `bootstrap.py` — единственное место, где создаются и связываются все компоненты.
4. Удалить неиспользуемые параметры `engine`, `cache`, `store`, `backend` из конструктора
   `LGTUApplication` (заменить на порты + доменные сервисы).

### Критерии приёмки
- `LGTUApplication.__init__` не вызывает ни одного `TurnstileState(...)`,
  `AccessPolicy(...)`, `PassageTracker(...)`, `EventBus(...)`, `AccessService(...)`,
  `PassageService(...)`, `SyncService(...)`.
- Все компоненты создаются только в `bootstrap.py`.
- Адаптеры из `bootstrap.py` реально используются (передаются в доменные сервисы).

---

## Нарушение 3: AccessPolicy использует LocalAccessCache напрямую, а не через порт AccessRepository

### Файл
`scud_lgtu/domain/access/services/services.py:50-59`

### Описание
`AccessPolicy` — доменный сервис, который должен зависеть только от порта
`AccessRepository` (интерфейса). Вместо этого он принимает `cache` и вызывает
метод `cache.is_allowed(type, value)`, который является методом конкретного класса
`LocalAccessCache` из Infrastructure.

```python
class AccessPolicy:
    def __init__(self, cache):
        self._cache = cache

    def check(self, credential: Credential) -> AccessDecision:
        allowed, user_id = self._cache.is_allowed(
            credential.token_type.value,
            credential.value
        )
```

Порт `AccessRepository` определяет метод `is_allowed(credential: Credential) -> AccessDecision`,
но `AccessPolicy` вызывает `is_allowed(type: str, value: str) -> tuple[bool, int]` —
сигнатура `LocalAccessCache`, а не порта.

### Последствия
- Доменный слой знает о сигнатуре инфраструктурного класса.
- Невозможно заменить `LocalAccessCache` на другую реализацию с другой сигнатурой.
- `AccessRepositoryAdapter` (который правильно реализует порт) не используется
  доменным сервисом.

### Требования к исправлению
1. `AccessPolicy.__init__` должен принимать `repository: AccessRepository` (порт).
2. `AccessPolicy.check()` должен вызывать `repository.is_allowed(credential)`,
   который возвращает `AccessDecision`.
3. В `bootstrap.py` передавать `AccessRepositoryAdapter(cache)` в `AccessPolicy`,
   а не `LocalAccessCache` напрямую.

### Критерии приёмки
- В `services.py` нет ссылок на `LocalAccessCache` или `is_allowed(type, value)`.
- `AccessPolicy` зависит только от `AccessRepository` (порта).
- `AccessRepositoryAdapter` используется как реализация порта.

---

## Нарушение 4: EventBus обращается к приватному полю TurnstileState

### Файл
`scud_lgtu/application/events/event_bus.py:104`

### Описание
`EventBus` проверяет состояние тревоги, обращаясь к приватному полю `_current_state`
доменного объекта `TurnstileState`:

```python
if self._turnstile and self._turnstile._current_state == "ALARM":
```

### Последствия
- Нарушение инкапсуляции: Application лезет во внутреннее состояние Domain.
- При переименовании `_current_state` (это приватное поле, которое может быть
  переименовано без обязательств по обратной совместимости) `EventBus` сломается.
- `TurnstileState` не контролирует, как его состояние читается извне.

### Требования к исправлению
1. Добавить в `TurnstileState` публичное свойство:
   ```python
   @property
   def current_state(self) -> str:
       return self._current_state
   ```
2. Или добавить метод:
   ```python
   def is_alarm_active(self) -> bool:
       return self._current_state == "ALARM"
   ```
3. `EventBus` должен использовать публичное свойство/метод вместо `_current_state`.

### Критерии приёмки
- В `event_bus.py` нет обращений к полям, начинающимся с `_`.
- `EventBus` использует `turnstile.is_alarm_active()` или `turnstile.current_state`.

---

## Нарушение 5: LGTUApplication.run() обращается к приватному полю engine._pct

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:384` (приблизительно)

### Описание
Главный цикл `LGTUApplication.run()` обращается к приватному полю `_pct` объекта
`ScudEngine` для вызова `set_mask()`:

```python
pct = self._engine._pct
if pct:
    pct.set_mask(output_states)
```

При этом у `ScudEngine` уже есть публичный метод `set_output_mask()`, который делает
то же самое.

### Последствия
- Нарушение инкапсуляции: Application лезет во внутреннее состояние Infrastructure.
- При рефакторинге `ScudEngine` (переименование `_pct`, изменение архитектуры
  внутренних потоков) `LGTUApplication` сломается.
- Дублирование логики: публичный метод `set_output_mask()` уже существует, но не
  используется.

### Требования к исправлению
1. Заменить обращение к `engine._pct.set_mask()` на `engine.set_output_mask()`.
2. Если `set_output_mask()` не покрывает нужный функционал — расширить публичный
   интерфейс `ScudEngine`, а не лезть в приватные поля.

### Критерии приёмки
- В `lgtu_application.py` нет обращений к полям `engine._*`.
- Используется `engine.set_output_mask()` или другой публичный метод.

---

## Нарушение 6: PassageService передаётся EventStore вместо EventLogAdapter

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:112`

### Описание
`PassageService` ожидает порт `EventLog` (с методом `append(passage: Passage)`),
но в `LGTUApplication.__init__` ему передаётся `EventStore` — конкретный класс
Infrastructure:

```python
self._passage_service = PassageService(store)  # store — EventStore, не EventLogAdapter
```

`EventStore.append()` принимает `PassageEvent` (инфраструктурная модель), а
`PassageService.log_passage()` передаёт `Passage` (доменная модель). Типы не совпадают.
Это работает только потому, что `Passage` и `PassageEvent` случайно совместимы по
атрибутам (оба имеют `direction`, `result`, `zone`, `duration`), но это хрупкая
связь, которая сломается при любом изменении одной из моделей.

### Последствия
- `EventLogAdapter` (который правильно конвертирует `Passage` → `PassageEvent`)
  не используется — мёртвый код.
- Передача `Passage` в `EventStore.append()` вместо `PassageEvent` — типобезопасность
  нарушена. При добавлении полей в `PassageEvent` (например, `event_id`, `stime`,
  `user_id`, `token_type`) данные будут потеряны.
- При замене `EventStore` на PostgreSQL-реализацию сигнатура `append()` изменится,
  и `PassageService` сломается.

### Требования к исправлению
1. В `bootstrap.py` создавать `EventLogAdapter(store)` и передавать его в
   `PassageService` (или в `LGTUApplication`, который передаст в `PassageService`).
2. `PassageService` должен принимать `EventLog` (порт), а не `EventStore`.
3. Убедиться, что `EventLogAdapter.append(passage: Passage)` корректно конвертирует
   `Passage` → `PassageEvent`.

### Критерии приёмки
- `PassageService` принимает `EventLog` (порт), а не `EventStore`.
- `EventLogAdapter` используется как реализация порта.
- В `PassageService` нет ссылок на `PassageEvent` или `EventStore`.

---

## Нарушение 7: SyncService передаётся BackendClient и EventStore вместо портов

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:113`

### Описание
`SyncService` по аннотациям типов принимает `BackendGateway` и `EventLog` (порты),
но реально получает `BackendClient` и `EventStore` — конкретные классы Infrastructure:

```python
self._sync_service = SyncService(backend, store, ...)
# backend — BackendClient, не BackendGatewayAdapter
# store — EventStore, не EventLogAdapter
```

### Последствия
- `BackendGatewayAdapter` (который правильно реализует порт `BackendGateway`)
  не используется — мёртвый код.
- `SyncService._sync()` вызывает `self._event_log.flush()` — возвращает
  `list[PassageEvent]` (инфраструктурная модель), а ожидает `list[Passage]`
  (доменная модель). Типы не совпадают.
- `SyncService._sync()` вызывает `self._backend.send_events(events)` — метод
  `BackendClient`, а не `BackendGatewayAdapter`. Сигнатуры могут отличаться.
- При замене `BackendClient` на mock с другой сигнатурой `SyncService` сломается.

### Требования к исправлению
1. В `bootstrap.py` создавать `BackendGatewayAdapter(backend_client)` и
   `EventLogAdapter(event_store)` и передавать их в `SyncService`.
2. `SyncService` должен принимать `BackendGateway` и `EventLog` (порты).
3. `SyncService._sync()` должен работать с `Passage` (доменная модель), а не с
   `PassageEvent` (инфраструктурная модель). `EventLogAdapter.flush()` возвращает
   `list[Passage]` — это правильный контракт.

### Критерии приёмки
- `SyncService` принимает `BackendGateway` и `EventLog` (порты).
- `BackendGatewayAdapter` и `EventLogAdapter` используются как реализации портов.
- В `SyncService` нет ссылок на `BackendClient` или `EventStore`.

---

## Нарушение 8: ShiftRegisterActuator — мёртвый код, порт Actuator не используется

### Файл
`scud_lgtu/infrastructure/gpio/actuator.py:15-26`

### Описание
`ShiftRegisterActuator` создан как адаптер, реализующий порт `Actuator` с методом
`apply(command: OutputCommand)`. Однако метод `apply()` пустой (`pass`):

```python
def apply(self, command: OutputCommand) -> None:
    if command.name not in self._pin_map:
        return
    pin_offset = self._pin_map[command.name]
    pass  # <-- ничего не делает
```

Команды выходов идут минуя порт `Actuator`, через прямой путь:
`_handle_output_commands` → `engine.set_output_mask()` → `pct.set_mask()` →
`ShiftRegister.set_mask()`.

### Последствия
- Порт `Actuator` определён в Domain, но фактически не используется.
- `TurnstileState` генерирует `OutputCommand`-ы, но они не идут через порт `Actuator`.
- Вместо этого `LGTUApplication._handle_output_commands()` перехватывает событие
  `OutputCommandsGenerated` и напрямую вызывает `engine.set_output_mask()`.
- Нарушается контракт: Domain генерирует команды, но Application отправляет их
  минуя порт, напрямую в Infrastructure.
- `ShiftRegisterActuator` — мёртвый код, который вводит в заблуждение.

### Требования к исправлению
1. Реализовать метод `ShiftRegisterActuator.apply(command: OutputCommand)`:
   преобразовывать `command.name` + `command.state` в маску сдвигового регистра
   и отправлять через `engine.set_output_mask()`.
2. В `bootstrap.py` создавать `ShiftRegisterActuator(engine, pin_map)` и передавать
   его в `TurnstileState` (или в `LGTUApplication`) как реализацию порта `Actuator`.
3. `TurnstileState` должен использовать `Actuator.apply()` для отправки команд
   на оборудование, а не публиковать `OutputCommandsGenerated` в `EventBus`.
4. Если `OutputCommandsGenerated` остаётся как событие для логирования/мониторинга,
   то `Actuator` всё равно должен быть основным каналом доставки команд.
5. Удалить прямой путь `_handle_output_commands → engine.set_output_mask()` или
   оставить его только как fallback.

### Критерии приёмки
- `ShiftRegisterActuator.apply()` реализован и работает (не `pass`).
- `TurnstileState` использует порт `Actuator` для отправки команд.
- Порт `Actuator` используется в production-коде (не только в тестах).

---

## Нарушение 9: handle_credential_common обращается к приватному полю _indicator_duration

### Файл
`scud_lgtu/application/handlers/common.py:79` (приблизительно)

### Описание
Handler `handle_credential_common` обращается к приватному полю `_indicator_duration`
доменного объекта `TurnstileState`:

```python
asyncio.create_task(
    turnstile.set_indicator_async(
        event_bus, indicator_success, True,
        turnstile._indicator_duration  # <-- приватное поле
    )
)
```

### Последствия
- Нарушение инкапсуляции: Application-хендлер лезет во внутреннее состояние Domain.
- При переименовании `_indicator_duration` или изменении способа хранения таймингов
  хендлер сломается.
- `TurnstileState` не контролирует доступ к своим таймингам извне.

### Требования к исправлению
1. Добавить в `TurnstileState` публичное свойство:
   ```python
   @property
   def indicator_duration(self) -> float:
       return self._indicator_duration
   ```
2. Или передавать `indicator_duration` как параметр по умолчанию в
   `set_indicator_async()`, чтобы хендлер не нуждался в чтении приватного поля.
3. Handler должен использовать публичное свойство, а не `_indicator_duration`.

### Критерии приёмки
- В `common.py` нет обращений к полям `turnstile._*`.
- Handler использует `turnstile.indicator_duration` или значение по умолчанию
  в сигнатуре `set_indicator_async()`.

---

## Нарушение 10: ScudEngine создаёт железо и firmware-классы напрямую, минуя конфиг

### Файлы
`scud_lgtu/infrastructure/core/engine.py:31-37`
`scud_lgtu/infrastructure/core/engine.py:265-298, 308-319, 346-360, 413-449`

### Описание
`ScudEngine` импортирует и жёстко конструирует конкретные hardware/firmware компоненты:

```python
from scud_lgtu.infrastructure.gpio.controller import GpiodPinController, PinControllerThread
from scud_lgtu.infrastructure.gpio.wiegand_reader import WeigandReader
from scud_lgtu.infrastructure.serial.reader import BackgroundSerialReader
from scud_lgtu.infrastructure.persistence.passage_detector import PassageDetector
...
self._ctrl = GpiodPinController()
self._pct = PinControllerThread(...)
reader = BackgroundSerialReader(...)
WeigandReader.start(...)
detector = PassageDetector(...)
```

### Последствия
- GPIO-контроллер, Wiegand/Serial считыватели, детекторы проходов нельзя заменить из конфига.
- Для запуска на моках требуется monkey-patching (`run_lgtu_controller_mock.py`), а не смена имени класса в `config.yml`.
- Firmware-адаптеры (`GpiodAdapter`, `WiegandAdapter`, `SerialAdapter`) реализуют порты, но не используются — ScudEngine напрямую использует низкоуровневые драйверы.
- Нарушает требование: любой hardware/firmware модуль должен быть каскадно объявлен в конфиге и взаимозаменяемым.

### Требования к исправлению
1. В `config.yml` добавить секции `hardware`/`firmware` с указанием имплементаций (`class` или `type`) для каждого компонента:
   - `gpio_controller`
   - `pin_controller_thread`
   - `serial_reader`
   - `wiegand_reader`
   - `passage_detector`
2. Создать в `infrastructure/config` или `infrastructure/bootstrap` фабрику `resolve_class` / `create_from_config`, которая по `class`/`type` инстанцирует модуль с его собственной конфигурацией из `ModuleResolver`.
3. `ScudEngine` должен принимать готовые драйверы/адаптеры в конструкторе (или получать фабрику) и не импортировать конкретные hardware-классы.

### Критерии приёмки
- В `engine.py` нет импортов `GpiodPinController`, `PinControllerThread`, `WeigandReader`, `BackgroundSerialReader`, `PassageDetector`.
- Замена `Gpio`/`Serial`/`Wiegand`/`PassageDetector` реализации возможна только правкой `config.yml` без правки кода `ScudEngine`.
- `GpiodAdapter`, `SerialAdapter`, `WiegandAdapter` используются как единственная точка входа для firmware.

---

## Нарушение 11: Bootstrap создаёт software-компоненты по конкретным импортам, а не из конфига

### Файл
`scud_lgtu/infrastructure/bootstrap/bootstrap.py:15-36`

### Описание
`bootstrap.py` импортирует и вызывает конструкторы всех software-компонентов напрямую:

```python
from scud_lgtu.infrastructure.core.engine import ScudEngine
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.sound.player import SoundPlayer
...
engine = ScudEngine(config, timings=timings)
cache = LocalAccessCache(path=cache_path)
store = EventStore()
backend = BackendClient()
```

Несмотря на наличие `ModuleResolver`, он используется только для разрешения имён устройств, а не для выбора класса компонента.

### Последствия
- Невозможно заменить `LocalAccessCache` → `RedisAccessCache`, `EventStore` → `PostgreSQLEventStore`, `BackendClient` → `MockBackendClient`, `SoundPlayer` → `DummySoundPlayer` без правки `bootstrap.py`.
- Смена software-реализации требует изменения импортов и кода, а не только конфига.
- `ModuleResolver` реализует `ConfigResolver` порта, но само создание объектов не проходит через конфигурационную декларацию.

### Требования к исправлению
1. В `config.yml` каждому software-модулю задать `class` (или `type`/`driver`):
   ```yaml
   software:
     engine:
       class: scud_lgtu.infrastructure.core.engine.ScudEngine
     cache:
       class: scud_lgtu.infrastructure.cache.access_cache.LocalAccessCache
       path: ...
     event_store:
       class: scud_lgtu.infrastructure.persistence.event_store.EventStore
     backend:
       class: scud_lgtu.infrastructure.backend.client.BackendClient
     sound:
       class: scud_lgtu.infrastructure.sound.player.SoundPlayer
   ```
2. Реализовать универсальную фабрику `create_software_component(config, module_name, default_args)` на основе `ModuleResolver`/импорта по строковому пути.
3. `bootstrap.py` должен читать секцию `software` из конфига и создавать инфраструктурные объекты через фабрику, сохраняя адаптеры (`AccessRepositoryAdapter`, `EventLogAdapter`, `SoundOutputAdapter`, `BackendGatewayAdapter`, `ShiftRegisterActuator`) как единственные связующие модули.
4. Все зависимости между software-компонентами (кеш-хранилище-бэкенд) должны быть разрешены каскадно: имя зависимости → `ModuleResolver.resolve("software.store")` → объект.

### Критерии приёмки
- В `bootstrap.py` не более одного места с `import` конкретного software-класса.
- Смена реализации любого software-модуля работает через изменение `class` в `config.yml`.
- В `bootstrap.py` нет прямого `ScudEngine(...)`, `LocalAccessCache(...)`, `EventStore(...)`, `BackendClient(...)`, `SoundPlayer(...)`.

---

## Нарушение 12: LGTUApplication создаёт QRDecoder и SoundPlayer напрямую

### Файл
`scud_lgtu/application/orchestration/lgtu_application.py:91-96, 107`

### Описание
`LGTUApplication.__init__` самостоятельно создаёт:

```python
self._qr_decoder = QRDecoder(keys_dir=keys_dir)
...
self._sound_player = SoundPlayer()
```

`QRDecoder` импортирован из `infrastructure.serial.qr_codec`, `SoundPlayer` — из `infrastructure.sound.player`. При этом `bootstrap.py` уже создаёт `SoundPlayer` для `SoundOutputAdapter`, но `LGTUApplication` игнорирует его и создаёт свой собственный экземпляр.

### Последствия
- `LGTUApplication` зависит от конкретных инфраструктурных классов.
- Нельзя заменить QR-кодек или звуковой плеер из конфига.
- `SoundPlayer` создаётся дважды: в `bootstrap.py` и в `LGTUApplication.__init__`.
- `keys_dir` захардкожен в `__init__`: `config.get("qr_keys_dir", "scud_lgtu/infrastructure/keys")`.

### Требования к исправлению
1. `QRDecoder` и `SoundOutput` (или `SoundPlayer`) должны создаваться в `bootstrap.py` через фабрику по конфигу.
2. `LGTUApplication` должен принимать `qr_decoder` и `sound_output` как параметры конструктора (порты/адаптеры), а не создавать их.
3. `LGTUApplication` не должен иметь импортов `QRDecoder` и `SoundPlayer`.

### Критерии приёмки
- В `lgtu_application.py` нет импортов `QRDecoder` и `SoundPlayer`.
- `lgtu_application.py` не вызывает `QRDecoder(...)` и `SoundPlayer(...)`.
- QR/звуковая подсистема подменяется через `config.yml`.

---

## Нарушение 13: Запуск с mock требует monkey-patching, а не конфиг

### Файлы
`run_lgtu_controller_mock.py:80-87`
`run_lgtu_controller_mock_interactive.py:269-272`

### Описание
Скрипты запуска с mock-оборудованием делают `patch` конкретных классов внутри `scud_lgtu.infrastructure...`:

```python
with patch('scud_lgtu.infrastructure.gpio.controller.GpiodPinController', ...):
    with patch('scud_lgtu.infrastructure.gpio.controller.PinControllerThread', ...):
        ...
```

### Последствия
- Mock-режим возможен только за счёт вмешательства во внутреннее устройство пакета.
- Замена железа/ПО на моки требует отдельного скрипта, а не смены конфигурации.
- Подтверждает, что hardware/firmware/software модули не объявлены в конфиге и не взаимозаменяемы.

### Требования к исправлению
1. После внедрения конфиг-ориентированной фабрики (нарушение 10–11) убрать `patch` из `run_lgtu_controller_mock.py`.
2. Создать `config.mock.yml` (или секцию `mode: mock` в `config.yml`), в которой заданы mock-имплементации:
   ```yaml
   mode: mock
   hardware:
     gpio_controller: scud_lgtu.tests.mocks.mock_gpio.MockGPIOController
     ...
   ```
3. `run_lgtu_controller_mock.py` должен отличаться от `run_lgtu_controller.py` только путём к конфигу (или только флагом `--mode mock`).

### Критерии приёмки
- В `run_lgtu_controller_mock.py` нет `unittest.mock.patch`.
- Mock-запуск работает через `config.yml` с mock-классами.
- Production и mock используют один и тот же `build_application(config_path)`.

---

## Нарушение 14: Legacy-контроллер `LGTUController` создаёт инфраструктуру внутри `ScudEngine`

### Файл
`scud_lgtu/infrastructure/core/engine.py:509-532`
`scud_lgtu/application/controllers/lgtu_controller.py:1-50`

### Описание
Метод `ScudEngine.run_lgtu_controller()` и класс `LGTUController` создают `LocalAccessCache`, `BackendClient`, `EventStore` прямо внутри engine/application:

```python
cache = LocalAccessCache(path=cache_path)
store = EventStore()
backend = BackendClient()
controller = LGTUController(engine=self, cache=cache, store=store, backend_client=backend, config=self._cfg)
```

Кроме того, `LGTUController` импортирует `ScudEvent`, `EventType`, `EventSource` и `QRDecoder` из `infrastructure`.

### Последствия
- Дублирует создание компонентов, уже сделанное в `bootstrap.py`.
- `ScudEngine` (infrastructure) смешивается с application-контроллером.
- В `LGTUController` нельзя подменить `cache`/`store`/`backend`/`qr_decoder` из конфига.
- Нарушает принцип единственной точки сборки — `bootstrap.py`.

### Требования к исправлению
1. Удалить `ScudEngine.run_lgtu_controller()` или перенести всю сборку в `bootstrap.py`.
2. `LGTUController` (если остаётся legacy) должен принимать уже готовые порты/адаптеры, а не создавать `LocalAccessCache`, `BackendClient`, `EventStore` самостоятельно.
3. `LGTUController` не должен импортировать `EventType`, `EventSource`, `ScudEvent`, `QRDecoder` из `infrastructure`.
4. Вся инициализация должна происходить в `bootstrap.py` через каскадную декларацию из `config.yml`.

### Критерии приёмки
- В `engine.py` нет метода `run_lgtu_controller()` или он не создаёт инфраструктуру.
- `LGTUController` не импортирует `LocalAccessCache`, `BackendClient`, `EventStore`, `QRDecoder`.
- `LGTUController` собирается в `bootstrap.py` как все остальные компоненты.

---

## Нарушение 15: config.yml содержит дублирующиеся и устаревшие секции

### Файл
`scud_lgtu/config.yml`

### Описание
В `config.yml` одни и те же данные описаны несколько раз, а устаревшие секции не удалены:

- Две секции `devices` (старая и «новая») с повторяющимися считывателями, кнопками и сенсорами.
- `timings` и `timings_old` — две копии таймингов.
- `serial` и `serial_timings` — устаревшее дублирование.
- Секция `business` + секция `config` + `shift_register.pins` + `mux.inputs` дублируют мапинги пинов и входов.
- `shift_register`/`mux` описывают пины и входы, а `config.shift_pins`/`config.mux_inputs` повторяют их ещё раз.

### Последствия
- Конфиг не является «простым и функциональным» — он перегружен дублями и legacy-секциями.
- Изменение в одном месте может не примениться, потому что код читает другое.
- `ModuleResolver` получает противоречивые источники истины.
- Тесты `test_config.py` проверяют устаревшие секции, замедляя рефакторинг.

### Требования к исправлению
1. Удалить `timings_old`, `serial_timings`, секцию `config`, и одну из секций `devices`.
2. Оставить **один** каскадный мапинг `mappings`, где бизнес-имена ссылаются на `module.local_name`:
   ```yaml
   mappings:
     entry_relay: shift_register.rel1
     inner_indicator_success: shift_register.w1_green
     entry_button: multiplexer.button_1
   ```
3. Все тайминги собрать в единственной секции `timings`.
4. `ModuleResolver` должен разрешать `business.name` → конкретный объект/пин из целевого модуля.
5. Удалить legacy-ключи из `config.yml`, на которые больше не ссылается production-код.

### Критерии приёмки
- В `config.yml` ровно одна секция `timings`, одна секция мапингов (`mappings`), одна `devices` (или она заменена на `mappings`/`readers`/`passage`).
- Нет `timings_old`, `serial_timings`, `config`.
- `pytest scud_lgtu/tests/test_config.py` проходит на новой структуре.

---

## Нарушение 16: Бизнес-имена пинов зашиты в TurnstileState, basic_business_logic и pin_map

### Файлы
`scud_lgtu/domain/turnstile/services/turnstile.py:117-123`
`scud_lgtu/application/business/basic_business_logic.py:68-111`
`scud_lgtu/infrastructure/gpio/pin_map.py:7-17`

### Описание
В коде прописаны строковые имена пинов вместо чтения их из конфига:

```python
# turnstile.py
self._entry_relay = "entry_relay"
self._exit_relay = "exit_relay"
self._main_buzzer = "main_buzzer"
self._entry_green = "inner_indicator_success"
...

# basic_business_logic.py
set_shift_pins(engine, {"rel1": True})
set_shift_pins(engine, {f"{reader}_green": True})

# pin_map.py
DEFAULT_PIN_MAP = {
    "rel1": 0,
    "rel2": 1,
    "w1_green": 2,
    ...
}
```

При этом в `config.yml` уже есть секция `business`, которая должна была бы задавать эти мапинги, но код не использует её.

### Последствия
- Смена реле/индикатора/бипера требует правки кода, а не конфига.
- `business`/`mappings` секции конфига фактически мёртвые.
- `TurnstileState` знает не только о бизнес-именах, но и о том, что они разрешаются в физические пины где-то в другом месте.

### Требования к исправлению
1. `TurnstileState` должен получать мапинг бизнес-имён пинов из `ConfigResolver`/`ModuleResolver`.
2. `TurnstileState.open_entry/open_exit/close` должны генерировать `OutputCommand(name="entry_relay", ...)` и позволять резолверу разрешать это в `shift_register.rel1`.
3. `basic_business_logic.py` должен быть удалён или полностью переписан на доменные порты (`Actuator`) и конфиг-резолвер.
4. `pin_map.py` должен загружать мапинг из `config.yml`, не иметь `DEFAULT_PIN_MAP`.

### Критерии приёмки
- В `turnstile.py`, `basic_business_logic.py`, `pin_map.py` нет литералов `rel1`, `rel2`, `w1_green`, `w1_red`, `w2_green`, `w2_red`, `buz`, `w1_beep`, `w2_beep`.
- Все имена пинов берутся из конфига.
- Изменение `mappings.entry_relay` в `config.yml` меняет поведение без правки кода.

---

## Нарушение 17: Legacy-файлы basic_business_logic.py и cli.py импортируют Infrastructure и лезут в приватные поля

### Файлы
`scud_lgtu/application/business/basic_business_logic.py:10-71`
`scud_lgtu/interfaces/cli.py:19-37`

### Описание
`basic_business_logic.py` импортирует `ScudEvent`, `EventType`, `PassageEvent`, `QRDecoder` из `infrastructure` и напрямую обращается к `engine._pct`:

```python
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, ...
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder
...
def set_shift_pins(engine, masks: dict[str, bool]) -> None:
    if engine._pct is not None:
        engine._pct.set_mask(masks)
```

`interfaces/cli.py` импортирует `LocalAccessCache`, `QRDecoder` из `infrastructure` и обращается к `application._engine` / `application._cache`:

```python
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder
...
self.application = build_application(self.config_path)
self.application._engine.start()
self.cache = self.application._cache
```

Кроме того, в `cli.py` используется `self.engine` (не определён), что делает `send_command` нерабочим.

### Последствия
- Legacy-код не даёт заменить `QRDecoder`, кэш, движок через конфиг.
- CLI и business logic зависят от приватных полей `Application`/`Engine`.
- `basic_business_logic.py` дублирует функции `TurnstileState`/`handlers`, но делает это напрямую через `engine._pct`.

### Требования к исправлению
1. `basic_business_logic.py`:
   - удалить или переписать на доменные события/порты (`Actuator`, `AccessRepository`);
   - убрать импорты `ScudEvent`, `EventType`, `PassageEvent`, `QRDecoder` из `infrastructure`;
   - не обращаться к `engine._pct`.
2. `interfaces/cli.py`:
   - не импортировать `LocalAccessCache`, `QRDecoder` из `infrastructure`;
   - использовать публичные методы `LGTUApplication` (например, `app.engine_start()`, `app.get_cache_view()`) или получать порты/адаптеры из `bootstrap.py`;
   - исправить `self.engine` → `self.application._engine` (или на публичное свойство).

### Критерии приёмки
- В `basic_business_logic.py` и `cli.py` нет `import from scud_lgtu.infrastructure.*`.
- Нет обращений к `._engine`, `._cache`, `._pct`.
- `basic_business_logic.py` либо удалён, либо работает только через `Actuator`/`EventBus`.

---

## Нарушение 18: В Infrastructure-классах захардкожены тайминги, пины, пути, URL и команды

### Файлы
`scud_lgtu/infrastructure/gpio/wiegand_reader.py:92-95`
`scud_lgtu/infrastructure/serial/reader.py:67`
`scud_lgtu/infrastructure/gpio/multiplexor.py:34,80-81`
`scud_lgtu/infrastructure/gpio/controller.py:59-82`
`scud_lgtu/infrastructure/gpio/shift_register.py:97-100`
`scud_lgtu/infrastructure/gpio/signal_reader.py:83-88`
`scud_lgtu/infrastructure/sound/player.py:31`
`scud_lgtu/infrastructure/backend/client.py:28`
`scud_lgtu/infrastructure/serial/qr_codec.py:116`
`scud_lgtu/infrastructure/bootstrap/bootstrap.py:88`

### Описание
Конкретные железные реализации содержат дефолтные значения пинов, портов, таймаутов, URL, путей и команд:

```python
# wiegand_reader.py
DEFAULT_BIT_TIMEOUT: float = 0.025
DEFAULT_WAIT_TIMEOUT: float = 0.005
d0: int = 11
d1: int = 12
chip_path: str = "/dev/gpiochip0"
wiegand_type: int = 26

# reader.py
port: str = "/dev/ttyUSB0"
baudrate: int = 115200
timeout: float = 0.05
retry_delay: float = 1.0

# multiplexor.py
_DEFAULT_ADDR_SETTLE_S: float = 0.0005
poll_interval: float = 0.02

# controller.py
PIN_MAP: Dict = {"PA0": ("/dev/gpiochip0", 0), ...}

# shift_register.py
self._ser_data_pin = config.get("ser_data", "PA6")
self._ser_clk_pin = config.get("ser_clk", "PA19")
self._n = config.get("reg_len", 16)

# signal_reader.py
chip_path: str = "/dev/gpiochip0"
debounce_time: float = 0.5
event_timeout: float = 0.1

# sound/player.py
sound_dir: str = "sounds"
player_cmd: str = "aplay"

# backend/client.py
base_url: str = "https://api.pass.lipetsk.ru"

# qr_codec.py
keys_dir: str = "key"

# bootstrap.py
cache_path = os.path.join(..., "infrastructure", "cache", "local_access.json")
```

### Последствия
- Смена платы (Orange Pi → другая) или окружения требует правки кода, а не конфига.
- Дефолты конфликтуют с `config.yml` (например, `ShiftRegister` берёт `ser_data` из `config`, но с дефолтом `PA6`).
- Production-значения (`api.pass.lipetsk.ru`, `sounds`, `aplay`) зашиты в классах.

### Требования к исправлению
1. Убрать все магические числа/строки-дефолты из `infrastructure/*`. Все значения должны приходить из `config.yml` или через конструктор из bootstrap.
2. `PIN_MAP` должен загружаться из `gpiod_controller.pins` в `config.yml` (или chip mappings), а не быть модульной константой.
3. `QRDecoder.keys_dir`, `BackendClient.base_url`, `SoundPlayer.sound_dir/player_cmd`, `LocalAccessCache.path` должны читаться из конфига.
4. `WiegandReader`/`BackgroundSerialReader`/`Multiplexer`/`InputSignalReader`/`PassageDetector` не должны иметь default-значений таймаутов и пинов в сигнатурах.
5. В `config.yml` должны быть секции `hardware`/`firmware` с параметрами, которые фабрика передаёт в конструкторы.

### Критерии приёмки
- В `infrastructure` не осталось `= 0.025`, `= 0.005`, `= "/dev/ttyUSB0"`, `= 115200`, `= "PA6"`, `= "aplay"`, `= "https://api.pass.lipetsk.ru"` и т.п.
- `PIN_MAP` удалён из `controller.py` или стал пустым дефолтом, загружаемым из конфига.
- Все дефолтные значения задаются в `config.yml`.

---

## Нарушение 19: Application/Domain используют fallback-дефолты и зашитые имена

### Файлы
`scud_lgtu/application/handlers/common.py:56-57, 79`
`scud_lgtu/application/handlers/button.py:67`
`scud_lgtu/application/services/sync_service.py:25`
`scud_lgtu/application/orchestration/lgtu_application.py:100-113`
`scud_lgtu/domain/turnstile/services/turnstile.py:59, 106-140`

### Описание
Во всех слоях встречаются `config.get(..., default)` с магическими числами/именами:

```python
# common.py
indicator_success = reader_config.get("indicator_success", "w1_green")
indicator_fail = reader_config.get("indicator_fail", "w1_red")

# button.py
open_duration = button_config.get("open_duration", 2.0)

# sync_service.py
sync_interval: float = 60.0

# lgtu_application.py
auth_timeout = timings.get("auth_timeout_s", 5.0)
sync_interval = timings.get("backend_sync_interval_s", 60.0)

# turnstile.py
auth_timeout: float = 5.0
self._beep_duration = ...get(..., 0.1)
self._deny_beep_count = ...get(..., 3)
```

### Последствия
- Конфиг не является единственным источником истины — код имеет свои дефолты.
- При отсутствии ключа в `config.yml` система ведёт себя иначе, чем ожидает оператор.
- Зашитые имена `w1_green`/`w1_red` дублируют мапинг и делают его бесполезным.

### Требования к исправлению
1. Все `get(key, default)` с числами/именами должны иметь дефолты, вынесенные в `config.yml` (или не иметь дефолтов вовсе).
2. `TurnstileState`, `button.py`, `common.py` должны брать тайминги и имена пинов из `ConfigResolver` без fallback-строк.
3. `SyncService`/`LGTUApplication` должны получать `sync_interval`, `auth_timeout` уже разрешёнными из `timings`.
4. Запретить `default` аргументы, содержащие тайминги/имена пинов, в `infrastructure`/`application`/`domain` (только общие `None`/пустые структуры).

### Критерии приёмки
- В `application`/`domain` нет `get("..._s", <number>)`, `get("..._name", "w1_green")` и т.п.
- Все тайминги и бизнес-имена берутся из `config.yml` через `ConfigResolver`/`ModuleResolver`.

---

## Нарушение 20: Тесты привязаны к инфраструктуре и приватным полям

### Файлы
`scud_lgtu/tests/test_bootstrap.py:18-26`
`scud_lgtu/tests/test_lgtu_controller.py:4-68`
`scud_lgtu/tests/test_config.py:20-57`

### Описание
Тесты импортируют `ScudEvent`, `EventType`, `EventSource` из `infrastructure`, проверяют `app._engine`, `app._config`, `controller._active_relay`, `controller._active_indicator`, фиксируют наличие устаревших секций `gpiod_controller`, `shift_register` и т.д.:

```python
# test_bootstrap.py
assert hasattr(app, '_engine')
assert app._config is not None

# test_lgtu_controller.py
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource
with patch('scud_lgtu.application.controllers.lgtu_controller.QRDecoder', ...)
assert controller._active_relay == "rel1"
assert controller._active_indicator == "w1_green"

# test_config.py
assert "gpiod_controller" in config
assert "shift_register" in config
assert shift_config["reg_len"] == 16
```

### Последствия
- Рефакторинг `config.yml` или `LGTUApplication` ломает тесты.
- Тесты закрепляют текущие нарушения (private fields, hardcoded pin names) вместо поведения.
- Mock-зависимости создаются вручную, а не из конфига.

### Требования к исправлению
1. `test_bootstrap.py` должен проверять публичный интерфейс `LGTUApplication` (например, `app.start()`, `app.stop()`), а не `hasattr(app, '_engine')` / `app._config`.
2. `test_lgtu_controller.py` должен либо удалиться вместе с `LGTUController`, либо работать с mock портами, а не импортировать `ScudEvent`/`EventType` и проверять `_active_relay`.
3. `test_config.py` должен проверять целевую структуру `config.yml` (`timings`, `modules`, `mappings`) после рефакторинга `config.yml`.
4. Тесты не должны импортировать `infrastructure` за исключением `bootstrap`/`config` для интеграционных тестов.

### Критерии приёмки
- В `tests/` нет `._engine`, `._config`, `._active_relay`, `._active_indicator`.
- Тесты не импортируют `ScudEvent`, `EventType`, `EventSource` из `infrastructure`.
- `test_config.py` проходит на целевой структуре `config.yml`.

---

## Нарушение 21: Корневые скрипты и standalone-утилиты импортируют Infrastructure и лезут в приватные поля

### Файлы
`run_lgtu_controller.py:31-39`
`run_lgtu_controller_mock.py:22-99`
`run_lgtu_controller_mock_interactive.py:269-284`
`run_mock_devices.py:22-73`
`run_mock_devices_interactive.py:15-63`
`test_device.py:109-348`
`test_hardware.py:12-388`
`generate_qr.py:14-27`
`inject_events.py:15-124`

### Описание
Скрипты верхнего уровня (запуск, mock, тестирование, генерация QR, инъекция событий) напрямую импортируют `infrastructure` и обращаются к приватным полям `Application`/`Engine`:

```python
# run_lgtu_controller.py
application._engine.start()
application._engine.stop()

# run_lgtu_controller_mock.py / run_lgtu_controller_mock_interactive.py
from scud_lgtu.infrastructure.gpio.controller import GpiodPinController
from scud_lgtu.infrastructure.serial.reader import BackgroundSerialReader
from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController
with patch('scud_lgtu.infrastructure.gpio.controller.GpiodPinController', ...)

# run_mock_devices.py / run_mock_devices_interactive.py
from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController
from scud_lgtu.infrastructure.config import load
port = serial_cfg.get("port", "/dev/ttyUSB0")
baud = serial_cfg.get("baud", 9600)
d0 = wiegand_cfg.get("d0", "PA0")
d1 = wiegand_cfg.get("d1", "PA1")

# test_device.py
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
turnstile._current_state = turnstile._current_state.__class__.ENTRY_OPEN
actual_state = turnstile._current_state.value

# generate_qr.py
from scud_lgtu.infrastructure.serial.qr_codec import encode_qr
keys_dir = "scud_lgtu/key"
key_id = int(sys.argv[2]) if len(sys.argv) > 2 else 13

# inject_events.py
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource
"reader": "serial_Serial-1"
"reader": "wiegand_Wiegand-1"
"https://pass.lipetsk.ru/test"
```

### Последствия
- Запуск, mock-режим и тестирование зависят от внутренней структуры `Application`/`Engine`.
- `run_lgtu_controller.py` не может запустить mock-версию без правки кода.
- `generate_qr`/`inject_events` привязаны к `infrastructure` и конкретным именам ридеров.

### Требования к исправлению
1. `run_lgtu_controller.py` — использовать публичные `application.start()`/`application.stop()` (или `bootstrap` фабрику) без `._engine`.
2. `run_lgtu_controller_mock.py` и `run_lgtu_controller_mock_interactive.py` — заменить `unittest.mock.patch`/`MagicMock` на `config.mock.yml`/`mode: mock` после появления фабрики.
3. `run_mock_devices.py`/`run_mock_devices_interactive.py` — должны использовать mock-адаптеры, объявленные в конфиге, а не импортировать `infrastructure`/`tests.mocks` напрямую; убрать дефолты `"/dev/ttyUSB0"`, `9600`, `"PA0"`, `"PA1"`.
4. `test_device.py`/`test_hardware.py` — либо удалить/переписать как интеграционные тесты через `bootstrap.py` и порты, либо убрать обращения к `._current_state` и импорты `infrastructure`.
5. `generate_qr.py`/`inject_events.py` — использовать `QRDecoder`/`encode_qr` через публичный интерфейс (например, `interfaces.qr` adapter) и брать `keys_dir`/имена ридеров из конфига.

### Критерии приёмки
- В корневых скриптах нет `._engine`, `._current_state`, `._config`.
- Mock-запуск работает через `config.mock.yml`, а не `unittest.mock.patch`.
- `generate_qr.py` и `inject_events.py` не импортируют `scud_lgtu.infrastructure.persistence.event_store`.

## Сводная таблица нарушений

| # | Файл | Слои | Тип нарушения | Критичность |
|---|------|------|---------------|-------------|
| 1 | `lgtu_application.py:30-35` | Application → Infrastructure | Прямой импорт конкретных классов | Высокая |
| 2 | `lgtu_application.py:98-113` | Application + Bootstrap | Дублирование создания компонентов | Высокая |
| 3 | `services.py:50-59` | Domain → Infrastructure | Доменный сервис зависит от конкретного класса | Высокая |
| 4 | `event_bus.py:104` | Application → Domain | Чтение приватного поля `_current_state` | Средняя |
| 5 | `lgtu_application.py:384` | Application → Infrastructure | Чтение приватного поля `_pct` | Средняя |
| 6 | `lgtu_application.py:112` | Application → Infrastructure | Передача EventStore вместо EventLogAdapter | Высокая |
| 7 | `lgtu_application.py:113` | Application → Infrastructure | Передача BackendClient вместо BackendGatewayAdapter | Высокая |
| 8 | `actuator.py:15-26` | Infrastructure → Domain | Порт Actuator не реализован (мёртвый код) | Средняя |
| 9 | `common.py:79` | Application → Domain | Чтение приватного поля `_indicator_duration` | Низкая |
| 10 | `engine.py:31-37` | Infrastructure (hardware/firmware) | Жёстко заданы hardware-классы | Высокая |
| 11 | `bootstrap.py:15-36` | Bootstrap | Software-компоненты не из конфига | Высокая |
| 12 | `lgtu_application.py:91-96, 107` | Application → Infrastructure | Создание QRDecoder/SoundPlayer внутри приложения | Средняя |
| 13 | `run_lgtu_controller_mock.py:80-87` | Interfaces | Mock через monkey-patching | Средняя |
| 14 | `engine.py:509-532` / `lgtu_controller.py:1-50` | Infrastructure + Application | Legacy-контроллер собирает инфраструктуру | Средняя |
| 15 | `config.yml` | Config | Дублирование и устаревшие секции в конфиге | Высокая |
| 16 | `turnstile.py`, `basic_business_logic.py`, `pin_map.py` | Domain/Application → Config | Зашитые бизнес-имена пинов | Средняя |
| 17 | `basic_business_logic.py`, `cli.py` | Application/Interfaces → Infrastructure | Legacy-код лезет в приватные поля/импорты Infrastructure | Средняя |
| 18 | `wiegand_reader.py`, `reader.py`, `multiplexor.py`, `controller.py`, `shift_register.py`, `signal_reader.py`, `player.py`, `client.py`, `qr_codec.py`, `bootstrap.py` | Infrastructure | Хардкод таймингов, пинов, путей, URL, команд | Высокая |
| 19 | `common.py`, `button.py`, `sync_service.py`, `lgtu_application.py`, `turnstile.py` | Application/Domain/Config | Fallback-дефолты и зашитые имена | Средняя |
| 20 | `tests/test_bootstrap.py`, `tests/test_lgtu_controller.py`, `tests/test_config.py` | Tests | Тесты зависят от Infrastructure и приватных полей | Низкая |
| 21 | `run_*.py`, `test_device.py`, `test_hardware.py`, `generate_qr.py`, `inject_events.py` | Interfaces/Scripts | Корневые скрипты импортируют Infrastructure и лезут в приватные поля | Низкая |

---

## Порядок исправления

Рекомендуется исправлять нарушения в следующем порядке (от фундаментальных к косметическим):

1. **Нарушение 3** — `AccessPolicy` зависит от `LocalAccessCache` вместо порта
   (Domain — фундамент, правится первым).
2. **Нарушение 8** — реализовать `ShiftRegisterActuator` (порт `Actuator`).
3. **Нарушение 15** — почистить `config.yml` от дублей и legacy-секций.
   Невозможно строить фабрику на нечистом конфиге.
4. **Нарушение 10 + 11** — внедрить конфиг-ориентированную фабрику для hardware,
   firmware и software компонентов. Это фундамент для всех остальных замен.
5. **Нарушение 16** — вынести бизнес-имена пинов в единый каскадный мапинг `config.yml`.
6. **Нарушение 1 + 2 + 12 + 14** — рефакторинг `LGTUApplication`, `bootstrap.py`
   и legacy-контроллера (убрать прямые импорты, принимать порты, убрать дублирование).
7. **Нарушение 6 + 7** — передавать адаптеры вместо конкретных классов
   (естественно следует из исправления 1+2).
8. **Нарушение 13** — перевести mock-запуск на конфигурацию после появления фабрики.
9. **Нарушение 17** — удалить/отрефакторить `basic_business_logic.py` и привести `cli.py`
   к публичным методам `LGTUApplication`.
10. **Нарушение 18** — вынести из `infrastructure` все хардкод-константы
    (тайминги, пины, пути, URL, команды) в `config.yml`.
11. **Нарушение 19** — убрать fallback-дефолты и зашитые имена из `application`/`domain`.
12. **Нарушение 20** — переписать тесты на порты и публичный интерфейс.
13. **Нарушение 21** — привести корневые скрипты (`run_*.py`, `test_device.py`,
    `generate_qr.py`, `inject_events.py`) к публичным методам и конфигу, убрать `patch`.
14. **Нарушение 4** — публичное свойство `current_state` / `is_alarm_active()`.
15. **Нарушение 5** — использовать `engine.set_output_mask()` вместо `engine._pct`.
16. **Нарушение 9** — публичное свойство `indicator_duration`.

---

## Ожидаемый результат

После исправления всех 21 нарушения:

- **Domain** не содержит ни одного импорта из `infrastructure` или `application`.
- **Application** (`LGTUApplication`, handlers, services, `LGTUController`, CLI) не содержит ни одного
  импорта из `infrastructure` (кроме `bootstrap.py` и фабрик).
- **Infrastructure** реализует порты Domain через адаптеры.
- **bootstrap.py** и фабрика `infrastructure.config`/`infrastructure.bootstrap` — единственные места,
  где создаются конкретные классы Infrastructure и связываются с Domain/Application через порты.
- `config.yml` — простой и функциональный: одна секция таймингов, один каскадный мапинг
  (`mappings`) и одна декларация модулей (`modules`/`hardware`). Нет дублей `devices`, `timings_old`,
  `serial_timings`, `config`.
- Все software-, hardware- и firmware-модули (engine, cache, store, backend, sound,
  QR-декодер, GPIO, Wiegand, Serial, passage detector) объявляются каскадно в `config.yml`
  через поле `class`/`type` и создаются фабрикой, без жёстких импортов в коде.
- В `infrastructure` нет хардкод-дефолтов: тайминги, пины, порты, URL, пути к файлам, звуковые
  команды берутся только из конфига.
- В `application`/`domain` нет fallback-дефолтов для таймингов и имён пинов — всё через
  `ConfigResolver`/`ModuleResolver`.
- Все адаптеры (`AccessRepositoryAdapter`, `EventLogAdapter`, `SoundOutputAdapter`,
  `BackendGatewayAdapter`, `ShiftRegisterActuator`, `GpiodAdapter`, `WiegandAdapter`,
  `SerialAdapter`) используются в production-коде.
- Ни один слой не обращается к приватным полям (`_`) объектов другого слоя.
- Тесты проверяют публичные интерфейсы и порты, не импортируют `infrastructure` (кроме
  `bootstrap`/`config` для интеграционных тестов) и не лезут в приватные поля.
- Корневые скрипты (`run_*.py`, `test_device.py`, `generate_qr.py`, `inject_events.py`)
  не импортируют `infrastructure` напрямую, не используют `unittest.mock.patch`,
  не обращаются к `._engine`/`._current_state`.
- Замена любой Infrastructure-реализации (cache, store, backend, engine, GPIO, Wiegand,
  Serial) возможна изменением `config.yml` без правок Domain, Application и `bootstrap.py`.
- Mock-запуск работает через `config.mock.yml`/`mode: mock`, без `unittest.mock.patch`.

---

## Приложение: целевая структура config.yml (simple & functional)

Ниже — пример конфигурации, которая одновременно проста (нет дублей, один источник истины) и
функциональна (любой модуль заменяется через `class`/`type`):

```yaml
logging:
  level: INFO
  format: "%(asctime)s %(name)s [%(levelname)s] %(message)s"

timings:
  auth_timeout_s: 5.0
  relay_open_duration_s: 2.0
  indicator_duration_s: 2.0
  deny_beep_duration_s: 0.1
  deny_beep_pause_s: 0.1
  deny_beep_count: 3
  backend_sync_interval_s: 600

modules:
  # Software-модули (заменяемые)
  engine: scud_lgtu.infrastructure.core.engine.ScudEngine
  cache:
    class: scud_lgtu.infrastructure.cache.access_cache.LocalAccessCache
    path: "infrastructure/cache/local_access.json"
  store: scud_lgtu.infrastructure.persistence.event_store.EventStore
  backend: scud_lgtu.infrastructure.backend.client.BackendClient
  sound:
    class: scud_lgtu.infrastructure.sound.player.SoundPlayer
    sound_dir: "sounds"
    player_cmd: "aplay"
  qr_decoder: scud_lgtu.infrastructure.serial.qr_codec.QRDecoder

hardware:
  # Hardware/firmware-модули (заменяемые)
  gpio_controller: scud_lgtu.infrastructure.gpio.controller.GpiodPinController
  pin_controller_thread: scud_lgtu.infrastructure.gpio.controller.PinControllerThread
  shift_register: scud_lgtu.infrastructure.gpio.shift_register.ShiftRegister
  multiplexer: scud_lgtu.infrastructure.gpio.multiplexor.Multiplexer
  wiegand_reader: scud_lgtu.infrastructure.gpio.wiegand_reader.WeigandReader
  serial_reader: scud_lgtu.infrastructure.serial.reader.BackgroundSerialReader
  passage_detector: scud_lgtu.infrastructure.persistence.passage_detector.PassageDetector

gpiod_controller:
  pins:
    shift_data: PA6
    shift_clk: PA19
    shift_latch: PA7
    mux_a0: PA6
    mux_a1: PA11
    mux_a2: PA12
    mux_input: PL11
    wiegand1_d0: PA10
    wiegand1_d1: PA2
    wiegand2_d0: PA3
    wiegand2_d1: PA18

shift_register:
  reg_len: 16
  pins:
    rel1: {pin: 14, inverted: false}
    rel2: {pin: 15, inverted: false}
    w1_green: {pin: 1, inverted: false}
    w1_red: {pin: 2, inverted: false}
    w2_green: {pin: 9, inverted: false}
    w2_red: {pin: 10, inverted: false}
    buz: {pin: 8, inverted: false}
    w1_beep: {pin: 3, inverted: false}
    w2_beep: {pin: 11, inverted: false}

multiplexer:
  inputs:
    button_1: {addr: 5}
    button_2: {addr: 7}
    button_3: {addr: 1}
    sensor_1: {addr: 4}
    sensor_2: {addr: 2}
    alarm: {addr: 6}

# Единственный каскадный мапинг бизнес-имён на аппаратные
mappings:
  entry_relay: shift_register.rel1
  exit_relay: shift_register.rel2
  inner_indicator_success: shift_register.w1_green
  inner_indicator_fail: shift_register.w1_red
  outer_indicator_success: shift_register.w2_green
  outer_indicator_fail: shift_register.w2_red
  main_buzzer: shift_register.buz
  entry_beeper: shift_register.w1_beep
  exit_beeper: shift_register.w2_beep
  entry_button: multiplexer.button_1
  exit_button: multiplexer.button_2
  alarm_input: multiplexer.alarm
  entry_sensor: multiplexer.sensor_1
  exit_sensor: multiplexer.sensor_2

readers:
  entry_card_reader:
    type: wiegand
    label: Wiegand-1
    beeper: entry_beeper
    indicator_success: inner_indicator_success
    indicator_fail: inner_indicator_fail
  exit_card_reader:
    type: wiegand
    label: Wiegand-2
    beeper: exit_beeper
    indicator_success: outer_indicator_success
    indicator_fail: outer_indicator_fail
  entry_qr_reader:
    type: serial
    label: Serial-1
    beeper: entry_beeper
    indicator_success: inner_indicator_success
    indicator_fail: inner_indicator_fail
  exit_qr_reader:
    type: serial
    label: Serial-2
    beeper: exit_beeper
    indicator_success: outer_indicator_success
    indicator_fail: outer_indicator_fail

passage:
  zones:
    - label: zone1
      inner: entry_sensor
      outer: exit_sensor

buttons:
  entry_button:
    input: entry_button
    relay: entry_relay
    open_duration: 2.0
  exit_button:
    input: exit_button
    relay: exit_relay
    open_duration: 2.0
```

### Правила целевого конфига

- **Один `timings`**. Все задержки, таймауты и периоды — в одной секции.
- **Один `mappings`**. Бизнес-имена (`entry_relay`) ссылаются на `module.local_name`
  (`shift_register.rel1`). `ModuleResolver` разрешает ссылку до конкретного объекта/пина.
- **Один `modules` + `hardware`**. Каждый заменяемый software/hardware/firmware компонент
  объявлен строкой `class` (или `type` → короткий alias) и собирается фабрикой.
- **Нет дублей**. `shift_register.pins` уже определяет бит пина; `mappings` только
  переименовывает его для бизнес-логики. `multiplexer.inputs` — единственное место
  для входов.
- **Mock-режим** — это тот же конфиг, в котором `hardware.*.class` заменены на mock-классы:
  ```yaml
  hardware:
    gpio_controller: scud_lgtu.tests.mocks.mock_gpio.MockGPIOController
    ...
  ```
- **Domain/Application** знают только `mappings` и `readers`/`passage`/`buttons`.
  Infrastructure знает `gpiod_controller`, `shift_register`, `multiplexer`.
