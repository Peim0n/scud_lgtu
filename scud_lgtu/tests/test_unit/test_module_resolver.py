"""
Unit-тесты для ModuleResolver.
"""

import pytest

from scud_lgtu.infrastructure.config.module_resolver import ModuleResolver


class TestModuleResolver:
    """Тесты для ModuleResolver."""

    def test_resolve_local_name_in_context(self):
        """Тест разрешения локального имени в контексте модуля."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("shift_register")

        result = resolver.resolve("beep1")
        assert result == {"offset": 3, "inverted": False}

    def test_resolve_explicit_module_name(self):
        """Тест разрешения с явным указанием модуля."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)

        result = resolver.resolve("shift_register.beep1")
        assert result == {"offset": 3, "inverted": False}

    def test_resolve_reference_chain(self):
        """Тест разрешения цепочки ссылок."""
        config = {
            "business": {
                "entry_beeper": "shift_register.beep1"
            },
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("business")

        result = resolver.resolve("entry_beeper")
        assert result == {"offset": 3, "inverted": False}

    def test_resolve_not_found(self):
        """Тест ошибки при отсутствии имени."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("shift_register")

        with pytest.raises(ValueError, match="Name not found"):
            resolver.resolve("nonexistent")

    def test_resolve_without_context(self):
        """Тест ошибки при отсутствии контекста."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)

        with pytest.raises(ValueError, match="no context set"):
            resolver.resolve("beep1")

    def test_caching(self):
        """Тест кэширования результатов."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("shift_register")

        # Первый вызов - разрешение
        result1 = resolver.resolve("beep1")
        # Второй вызов - из кэша
        result2 = resolver.resolve("beep1")

        assert result1 == result2
        assert "beep1" in resolver._cache

    def test_clear_cache(self):
        """Тест очистки кэша."""
        config = {
            "shift_register": {
                "pins": {
                    "beep1": {"offset": 3, "inverted": False}
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("shift_register")

        resolver.resolve("beep1")
        assert len(resolver._cache) > 0

        resolver.clear_cache()
        assert len(resolver._cache) == 0

    def test_get_timing(self):
        """Тест получения тайминга."""
        config = {
            "shift_register": {
                "timings": {
                    "shift_queue_maxsize": 50
                }
            }
        }
        resolver = ModuleResolver(config)

        result = resolver.get_timing("shift_register", "shift_queue_maxsize")
        assert result == 50

    def test_get_timing_with_default(self):
        """Тест получения тайминга со значением по умолчанию."""
        config = {
            "shift_register": {
                "timings": {}
            }
        }
        resolver = ModuleResolver(config)

        result = resolver.get_timing("shift_register", "nonexistent", 100)
        assert result == 100

    def test_get_pin(self):
        """Тест получения пина."""
        config = {
            "gpiod_controller": {
                "pins": {
                    "shift_data": "PA6"
                }
            }
        }
        resolver = ModuleResolver(config)

        result = resolver.get_pin("gpiod_controller", "shift_data")
        assert result == "PA6"

    def test_get_pin_not_found(self):
        """Тест ошибки при отсутствии пина."""
        config = {
            "gpiod_controller": {
                "pins": {
                    "shift_data": "PA6"
                }
            }
        }
        resolver = ModuleResolver(config)

        with pytest.raises(ValueError, match="Pin not found"):
            resolver.get_pin("gpiod_controller", "nonexistent")

    def test_complex_reference_chain(self):
        """Тест сложной цепочки ссылок."""
        config = {
            "business": {
                "entry_beeper": "shift_register.beep1"
            },
            "shift_register": {
                "beep1": "gpiod_controller.shift_data"
            },
            "gpiod_controller": {
                "pins": {
                    "shift_data": "PA6"
                }
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("business")

        result = resolver.resolve("entry_beeper")
        assert result == "PA6"

    def test_resolve_string_value(self):
        """Тест что строковые значения не резолвятся рекурсивно."""
        config = {
            "shift_register": {
                "ser_data": "PA6"  # Прямое значение, не ссылка
            }
        }
        resolver = ModuleResolver(config)
        resolver.set_context("shift_register")

        result = resolver.resolve("ser_data")
        assert result == "PA6"
