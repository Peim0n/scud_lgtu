# LGTU Controller - OrangePi Deployment

Полный проект контроллера турникета ЛГТУ для развертывания на OrangePi.

## Состав проекта

- `scud_lgtu/` - основной пакет с модулями:
  - `lgtu_controller.py` - новый модуль контроллера ЛГТУ
  - `basic_business_logic.py` - базовые функции бизнес-логики
  - `data_types.py` - типы данных
  - `engine.py` - основной движок системы
  - `pin_controller.py` - управление пинами GPIO
  - `wiegand_reader.py` - чтение карт Wiegand
  - `qr_decoder.py` - декодер QR-кодов
  - `backend_client.py` - клиент для бэкенда
  - `access_controller.py` - контроллер доступа
  - `local_access_cache.py` - локальный кэш доступа
  - `config.yml` - конфигурация системы
- `main.py` - основной файл запуска
- `requirements.txt` - зависимости Python
- `config.yml` - конфигурация системы (в корне)

## Установка на OrangePi

1. Скопировать весь проект на OrangePi:
   ```bash
   scp -r orangepi_deploy/* root@orangepi:/opt/scud_lgtu/
   ```

2. Установить зависимости:
   ```bash
   ssh root@orangepi
   cd /opt/scud_lgtu
   pip install -r requirements.txt
   ```

3. Настроить конфигурацию:
   - Отредактировать `config.yml` под ваше оборудование
   - Настроить параметры бэкенда

4. Запустить систему:
   ```bash
   python main.py
   ```

## Запуск LGTU контроллера

Для запуска только LGTU контроллера используйте:
```bash
python run_lgtu_controller.py
```

Или программно:
```python
from scud_lgtu.engine import ScudEngine

engine = ScudEngine()
engine.start()
engine.run_lgtu_controller()
```

## Конфигурация

Основные тайминги в `config.yml`:

- `auth_timeout_s: 30.0` - время действия авторизации
- `relay_open_duration_s: 2.0` - время открытия реле
- `indicator_duration_s: 2.0` - длительность индикатора

## Функциональность LGTU контроллера

- Обработка QR-кодов (валидация в декодере)
- Обработка карт МИР с учетом шифрования считывателем
- Логика проходов (вход/выход) с проверкой двойного прохода
- Пожарная сигнализация с инверсией (state False = норма, True = пожар)
- Кнопки управления:
  - Кнопка 1: открыть на вход
  - Кнопка 2: открыть на выход
  - Кнопка 3: не используется
- Синхронизация с бэкендом (ключи, списки доступа)
- Офлайн-режим с локальным кэшем

## TODO

- Реализовать HMAC шифрование PAN карт в методе `encrypt_card_pan`
