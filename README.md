# LGTU Controller - СКУД для Orange Pi Zero LTS

Система контроля доступа на базе gpiod + threading для Orange Pi Zero LTS с чистой архитектурой.

## Архитектура проекта

Проект реализует чистую архитектуру (Clean Architecture) с разделением на слои:

### Доменный слой (`scud_lgtu/domain/`)
Содержит основную бизнес-логику и не зависит от инфраструктуры:
- `enums.py` - перечисления (направление, тип токена, результат, важность)
- `models.py` - доменные модели (Credential, AccessDecision, AuthSession, Passage, OutputCommand)
- `turnstile.py` - конечный автомат турникета
- `services.py` - доменные сервисы (AccessPolicy, PassageTracker, CredentialHasher)
- `events.py` - события домена (QrRead, CardRead, PassageDetected, AlarmChanged, ButtonPressed)
- `ports.py` - порты (интерфейсы) для адаптеров

### Слой приложения (`scud_lgtu/application/`)
Оркестрация бизнес-логики и use cases:
- `event_bus.py` - шина событий с поддержкой asyncio
- `handlers/` - обработчики событий (QR, карты, проходы, тревога, кнопки, мультиплексор)
- `services/` - сервисы приложения (AccessService, PassageService, SyncService)
- `lgtu_application.py` - основное приложение LGTU
- `lgtu_controller.py` - контроллер ЛГТУ (устаревающий, используется для регрессионных тестов)
- `basic_business_logic.py` - базовая бизнес-логика (устаревающая)

### Инфраструктурный слой (`scud_lgtu/infrastructure/`)
Адаптеры внешних систем:
- `engine.py` - основной движок системы
- `gpio/` - управление GPIO (контроллер, мультиплексор, сдвиговый регистр, сигналы)
- `serial/` - работа с последовательными портами (QR-код, считыватели)
- `cache/` - локальный кэш доступа
- `persistence/` - хранение событий
- `backend/` - клиент бэкенда
- `sound/` - управление звуком
- `threads/` - управление потоками

### Слой интерфейсов (`scud_lgtu/interfaces/`)
Точки входа в систему:
- `cli.py` - командный интерфейс

### Файлы конфигурации
- `config.py` - загрузка конфигурации
- `settings.py` - типизированная конфигурация
- `bootstrap.py` - контейнер внедрения зависимостей
- `config.yml` - конфигурация системы

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
pip install --no-index gpiod pyserial pyyaml
```

Вариант B - использование системных пакетов (рекомендуется для Orange Pi):
```bash
# Установите зависимости в систему
apt install python3-gpiod python3-serial python3-yaml -y

# Создайте символические ссылки в venv
ln -s /usr/lib/python3/dist-packages/gpiod venv/lib/python3.*/site-packages/
ln -s /usr/lib/python3/dist-packages/serial venv/lib/python3.*/site-packages/
ln -s /usr/lib/python3/dist-packages/yaml venv/lib/python3.*/site-packages/
```

**Примечание:** Для работы без интернета рекомендуется использовать системные пакеты через apt и создать символические ссылки в venv.

### 4. Настройка конфигурации

Отредактируйте файл `scud_lgtu/config.yml` под ваше оборудование:

```bash
nano scud_lgtu/config.yml
```

Настройте:
- Пины GPIO для мультиплексора и сдвигового регистра
- Параметры Wiegand-считывателей
- Параметры последовательных портов
- Тайминги системы
- Параметры бэкенда

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
source /opt/scud_lgtu/venv/bin/activate

# Запуск контроллера
python run_lgtu_controller.py
```

### 7. Настройка автозапуска через systemd

Создайте файл сервиса:

```bash
nano /etc/systemd/system/scud_lgtu.service
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
Environment="PATH=/opt/scud_lgtu/venv/bin"
ExecStart=/opt/scud_lgtu/venv/bin/python /opt/scud_lgtu/run_lgtu_controller.py
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

Запуск регрессионных тестов:

```bash
cd /opt/scud_lgtu
source venv/bin/activate
pytest scud_lgtu/tests/test_regression/ -v
```

## Конфигурация

Основные параметры в `scud_lgtu/config.yml`:

- `auth_timeout_s: 30.0` - время действия авторизации
- `relay_open_duration_s: 2.0` - время открытия реле
- `indicator_duration_s: 2.0` - длительность индикатора
- `backend_sync_interval_s: 60.0` - интервал синхронизации с бэкендом

## Функциональность

- Обработка QR-кодов (валидация в декодере)
- Обработка карт МИР с учётом шифрования считывателем
- Логика проходов (вход/выход) с проверкой двойного прохода
- Пожарная сигнализация с инверсией (state False = норма, True = пожар)
- Кнопки управления:
  - Кнопка 1: открыть на вход
  - Кнопка 2: открыть на выход
  - Кнопка 3: не используется
- Синхронизация с бэкендом (ключи, списки доступа)
- Офлайн-режим с локальным кэшем

## Логирование

Логи выводятся в stdout с форматом:

```
%(asctime)s - %(name)s [%(levelname)s] %(message)s
```

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
ruff check scud_lgtu/
ruff format scud_lgtu/
```

### Типизация

```bash
mypy scud_lgtu/
```

## Лицензия

MIT
