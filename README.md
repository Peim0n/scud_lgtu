# LGTU Controller - СКУД для Orange Pi Zero LTS

Система контроля доступа на базе gpiod + threading для Orange Pi Zero LTS с чистой архитектурой.

## Архитектура проекта

Проект реализует чистую архитектуру (Clean Architecture) с разделением на слои:

### Доменный слой (`app/domain/`)
Содержит основную бизнес-логику и не зависит от инфраструктуры:
- `enums.py` - перечисления (направление, тип токена, результат, важность, тип события)
- `models.py` - доменные модели (Credential, AccessDecision, AuthSession, Passage, OutputCommand)
- `events.py` - события домена (QrRead, CardRead, PassageDetected, AlarmChanged, ButtonPressed, AccessGranted, AccessDenied, DeviceCommand)
- `access.py` - доменные сервисы (AccessPolicy, PassageTracker)
- `access_device.py` - базовый класс устройства доступа (AccessDevice)

### Слой приложения (`app/application/`)
Оркестрация бизнес-логики:
- `lgtu_application.py` - основное приложение LGTU (LGTUApplication, _CommandRunner)
- `commands.py` - команды приложения (CommandAction, CommandTarget, ScudCommand)
- `services/` - сервисы приложения:
  - `sync_service.py` - синхронизация событий и списка доступа с бэкендом
  - `passage_service.py` - журналирование проходов
  - `key_sync_service.py` - синхронизация ключей QR-кодов (in-memory)
  - `accesspoint_inventory_service.py` - инвентаризация точки доступа

### Инфраструктурный слой (`app/infrastructure/`)
Адаптеры внешних систем:
- `engine.py` - ScudEngine: оркестратор hardware (потоки, очереди, watchdog)
- `bootstrap.py` - сборка приложения и внедрение зависимостей
- `firmware/gpio/` - управление GPIO:
  - `controller.py` - GpiodPinController, PinControllerThread
  - `multiplexor.py` - Multiplexer, MuxEventMapper
  - `shift_register.py` - ShiftRegister
  - `signal_reader.py` - чтение сигналов GPIO
  - `actuator.py` - ShiftRegisterActuator (OutputCommand -> сдвиговый регистр)
  - `wiegand_reader.py` - WiegandReader (чтение карт)
- `firmware/serial/` - работа с последовательными портами:
  - `serial_reader.py` - BackgroundSerialReader
  - `qr_decoder.py` - QRDecoder (декодирование и верификация QR-кодов)
- `cache/` - кэш доступа (in-memory):
  - `access_cache.py` - LocalAccessCache (in-memory, без записи на SD-карту)
  - `repository.py` - AccessRepositoryAdapter
  - `identifier_hash.py` - хеширование идентификаторов
- `persistence/` - хранение событий (in-memory):
  - `event_store.py` - EventStore (in-memory очередь событий)
  - `event_log.py` - EventLogAdapter
- `backend/` - клиент бэкенда:
  - `rest_client.py` - RestClient (HTTP + mTLS + TCP keepalive)
  - `client.py` - BackendClient (бизнес-операции)
  - `certificate_manager.py` - CertificateManager (mTLS-сертификаты)
  - `gateway.py` - BackendGatewayAdapter
- `sound/` - управление звуком:
  - `player.py` - SoundPlayer (неблокирующий проигрыватель)
  - `output.py` - SoundOutputAdapter
- `devices/turnstile/` - логика турникета:
  - `turnstile_device.py` - TurnstileDevice (FSM турникета)
  - `commands.py` - асинхронные команды (OpenEntry, OpenExit, Unlock, Close, Alarm, Deny и др.)
- `config/` - конфигурация:
  - `config_loader.py` - загрузка config.yml
  - `module_resolver.py` - ModuleResolver (разрешение имён пинов/таймингов)

### Слой интерфейсов (`app/interfaces/`)
Точки входа в систему:
- `cli.py` - командный интерфейс для управления и диагностики

### Точка запуска
- `run_lgtu_controller.py` - запуск контроллера

## Хранение данных

Все данные (кэш доступа, очередь событий, ключи QR-кодов) хранятся **только в оперативной памяти**. На SD-карту ничего не пишется, кроме mTLS-сертификатов. При перезагрузке данные загружаются заново с бэкенда.

## Установка на Orange Pi

### 1. Подготовка системы

Подключитесь к Orange Pi по SSH и обновите систему:

```bash
ssh root@orangepi
apt update && apt upgrade -y
```

### 2. Установка Python и создание venv

```bash
# Установка Python 3.10+ и venv (если не установлен)
apt install python3 python3-pip python3-venv -y

# Создание виртуального окружения
cd /opt
git clone <repo-url> scud_lgtu
cd scud_lgtu
python3 -m venv venv
source venv/bin/activate
```

### 3. Установка зависимостей в venv

**Способ 1 (с интернетом):**
```bash
pip install -e .
```

**Способ 2 (без интернета - для Orange Pi):**

Вариант A - через pip с локальными пакетами (если есть):
```bash
# Сначала установите setuptools в venv
pip install --no-index setuptools wheel

# Затем установите зависимости
pip install --no-index gpiod pyserial pyyaml cryptography
```

Вариант B - использование системных пакетов (рекомендуется для Orange Pi):
```bash
# Установите зависимости в систему
apt install python3-gpiod python3-serial python3-yaml python3-cryptography -y

# Создайте символические ссылки в venv
ln -s /usr/lib/python3/dist-packages/gpiod venv/lib/python3.*/site-packages/
ln -s /usr/lib/python3/dist-packages/serial venv/lib/python3.*/site-packages/
ln -s /usr/lib/python3/dist-packages/yaml venv/lib/python3.*/site-packages/
```

### 4. Настройка конфигурации

Отредактируйте файл `app/config.yml` под ваше оборудование:

```bash
nano app/config.yml
```

Настройте:
- Пины GPIO для мультиплексора и сдвигового регистра
- Параметры Wiegand-считывателей
- Параметры последовательных портов
- Тайминги системы
- Параметры бэкенда (URL, api_path_prefix, TCP keepalive)
- QR-декодер (base_url)

### 5. Настройка gpiod

Убедитесь, что gpiod установлен и настроен:

```bash
# Проверка установки
gpiodetect

# Если не установлен
apt install gpiod -y
```

### 6. Запуск системы

```bash
# Активация виртуального окружения
source /opt/app/venv/bin/activate

# Запуск контроллера
python run_lgtu_controller.py
```

### 7. Настройка автозапуска через systemd

Создайте файл сервиса:

```bash
nano /etc/systemd/system/app.service
```

Содержимое:

```ini
[Unit]
Description=LGTU Controller - СКУД для Orange Pi
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/scud_lgtu
Environment="PATH=/opt/app/venv/bin"
ExecStart=/opt/app/venv/bin/python /opt/app/run_lgtu_controller.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активация сервиса:

```bash
systemctl daemon-reload
systemctl enable scud_lgtu
systemctl start scud_lgtu
systemctl status scud_lgtu
```

## Тестирование

Запуск тестов:

```bash
pytest app/tests/ -v --ignore=app/tests/test_backend_integration.py
```

## Конфигурация

Основной файл — `app/config.yml`. Ключевые секции:

- `gpiod` — пины GPIO: mux, shift, wiegand
- `mux.inputs` — имена входов мультиплексора
- `shift_register.pins` — имена выходов сдвигового регистра
- `timings` — таймауты прохода, Wiegand, синхронизации, очередей, command_stop_timeout_s, open_beep_duration_s
- `backend` — base_url, api_path_prefix, tcp_keepalive_*, request_timeout_s, cert
- `qr_decoder` — base_url (базовый URL QR-кодов)
- `sound` — директория звуков, команда плеера, stop_timeout_s, play_timeout_s
- `devices` — конфигурация устройств (кнопки, считыватели)
- `logging` — уровни логирования по каждому модулю индивидуально

## Функциональность

- Обработка QR-кодов (AES128-CTR + Ed25519, TLV payload)
- Обработка карт по Wiegand (частичное хеширование идентификатора)
- Логика проходов (вход/выход) с проверкой двойного прохода
- Пожарная сигнализация с инверсией (state False = норма, True = пожар)
- Кнопки управления:
  - Кнопка 1: открыть на вход
  - Кнопка 2: открыть на выход
  - Кнопка 3: модификатор Shift (для переключения в режимы unlocked_entry/unlocked_exit)
- FSM турникета с режимами: idle, entry_open, exit_open, unlocked_entry, unlocked_exit, blocked, alarm
- Синхронизация с бэкендом (ключи, списки доступа, события)
- Офлайн-режим с локальным кэшем (in-memory, при перезагрузке данные загружаются заново)
- mTLS-сертификаты с автоматической ротацией
- Инвентаризация точки доступа

## Логирование

Логи выводятся в stdout с форматом:

```
%(asctime)s %(name)s [%(levelname)s] %(message)s
```

Уровни логирования настраиваются в `config.yml` для каждого из 20 модулей индивидуально. По умолчанию:
- Application (lgtu_application, сервисы): INFO
- Турникет (commands, turnstile_device): INFO
- Инфраструктура (GPIO, Serial, кэш, бэкенд, звук): WARNING

Для просмотра логов при запуске через systemd:

```bash
journalctl -u scud_lgtu -f
```

## Разработка

### Установка зависимостей для разработки

```bash
pip install -e ".[dev]"
```

### Линтер и форматирование

```bash
ruff check app/
ruff format app/
```

### Типизация

```bash
mypy app/
```

## Репозитории

- **origin**: https://github.com/Peim0n/scud_lgtu
- **orangepi**: root@172.19.12.202:/opt/app.git (деплой на устройство)
- **hq**: git@git.hq.int-sys.ru:project/alo-acs-max-26.git (корпоративный репозиторий)

## Лицензия

MIT
