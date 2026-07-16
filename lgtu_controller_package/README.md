# LGTU Controller Package

Пакет контроллера турникета ЛГТУ для системы управления доступом.

## Состав пакета

- `lgtu_controller.py` - основной модуль контроллера
- `basic_business_logic.py` - базовые функции бизнес-логики
- `data_types.py` - типы данных (ScudEvent, EventType и т.д.)
- `config.yml` - конфигурация с таймингами

## Функциональность

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

## Установка

1. Скопировать файлы в проект
2. Импортировать контроллер в engine.py:

```python
from .lgtu_controller import LGTUController

controller = LGTUController(
    engine=self,
    cache=self._cache,
    store=self._store,
    backend_client=self._backend,
    config=self._cfg
)
controller.run()
```

## Конфигурация

Тайминги настраиваются в `config.yml`:

- `auth_timeout_s: 30.0` - время действия авторизации
- `relay_open_duration_s: 2.0` - время открытия реле
- `indicator_duration_s: 2.0` - длительность индикатора

## TODO

- Реализовать HMAC шифрование PAN карт в методе `encrypt_card_pan`
