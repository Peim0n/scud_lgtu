# Тестирование модулей

## Юнит-тесты

```bash
python -m unittest discover -s tests
```

## QR-код

```bash
python scripts/generate_qr.py 12345 --keyset 167
python scripts/generate_qr.py 12345 --png code.png
```

## Управление локальным кэшем

```bash
python scripts/manage_access.py -p local_access.json add maxid 12345
python scripts/manage_access.py -p local_access.json list
python scripts/manage_access.py -p local_access.json remove maxid 12345
```

## Интерактивное тестирование железа

```bash
python main.py
```

## HTTP API

Запустить `app.py` и обращаться к `http://localhost:8080` (порт из `config.yml`).

## Запуск приложения

```bash
python -m scud_lgtu.app
```
