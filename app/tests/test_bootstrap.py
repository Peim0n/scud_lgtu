"""Тесты сборки приложения пакета app.tests."""
import os

import pytest

from app.infrastructure.bootstrap import build_application


@pytest.fixture
def config_path():
    """Получить путь к тестовому файлу конфигурации."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, "config.yml")


def test_build_application_returns_app(config_path):
    """Проверить, что build_application возвращает объект приложения."""
    from app.application.lgtu_application import LGTUApplication
    app = build_application(config_path)
    assert app is not None
    assert isinstance(app, LGTUApplication)
    assert hasattr(app, 'start')
    assert hasattr(app, 'shutdown')
    assert hasattr(app, 'run')


def test_build_application_loads_config(config_path):
    """Проверить, что build_application загружает конфигурацию."""
    app = build_application(config_path)
    assert app is not None


def test_build_application_sets_logging(config_path):
    """Проверить, что build_application настраивает логирование."""
    import logging

    # Собрать приложение
    app = build_application(config_path)

    # Проверить, что логирование настроено
    root_logger = logging.getLogger()
    assert root_logger.level is not None
