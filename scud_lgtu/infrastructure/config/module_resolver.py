"""
Модульный резолвер имен устройств.

Каждый модуль работает со своими локальными именами.
Мапинг между модулями осуществляется через конфигурацию.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ModuleResolver:
    """
    Резолвер модульных имен с локальными именами в каждом модуле.

    Каждый модуль работает со своими локальными именами.
    Мапинг между модулями - в конфиге через "module.local_name".

    Examples
    --------
    >>> resolver = ModuleResolver(config)
    >>> resolver.set_context("shift_register")
    >>> config = resolver.resolve("beep1")  # → {offset: 3, inverted: false}
    >>> resolver.set_context("business")
    >>> config = resolver.resolve("entry_beeper")  # → "shift_register.beep1" → {offset: 3, inverted: false}
    >>> config = resolver.resolve("shift_register.beep1")  # → {offset: 3, inverted: false}
    """

    def __init__(self, config: dict):
        """
        Инициализировать резолвер.

        Parameters
        ----------
        config : dict
            Полный конфигурационный словарь
        """
        self._config = config
        self._current_module: Optional[str] = None
        self._cache: dict[str, Any] = {}

    def set_context(self, module_name: str) -> None:
        """
        Установить текущий модуль.

        Parameters
        ----------
        module_name : str
            Имя текущего модуля (например, "shift_register", "business")
        """
        self._current_module = module_name
        logger.debug(f"[ModuleResolver] Контекст установлен: {module_name}")

    def resolve(self, name: str) -> Any:
        """
        Разрешить имя до конфигурации.

        - Если имя содержит точку: "module.local_name" - явный мапинг
        - Если имя без точки: ищем в текущем модуле

        Parameters
        ----------
        name : str
            Имя для разрешения

        Returns
        -------
        Any
            Разрешенная конфигурация (dict, str, int и т.д.)

        Raises
        ------
        ValueError
            Если имя не найдено
        """
        if name in self._cache:
            return self._cache[name]

        result = self._resolve_impl(name)
        self._cache[name] = result
        return result

    def _resolve_impl(self, name: str) -> Any:
        """Внутренняя реализация разрешения без кэширования."""
        # Явный мапинг с точкой: "module.local_name"
        if '.' in name:
            module, local_name = name.split('.', 1)
            config = self._get_module_config(module)
            result = self._find_in_config(config, local_name)
            if result is not None:
                # Рекурсивное разрешение если результат - строка-ссылка (содержит точку)
                if isinstance(result, str) and '.' in result:
                    return self._resolve_impl(result)
                return result
            else:
                raise ValueError(f"Name not found: {name} (module '{module}' has no key '{local_name}')")

        # Локальное имя в текущем модуле
        if self._current_module:
            config = self._get_module_config(self._current_module)
            result = self._find_in_config(config, name)
            if result is not None:
                # Рекурсивное разрешение если результат - строка-ссылка (содержит точку)
                if isinstance(result, str) and '.' in result:
                    return self._resolve_impl(result)
                return result
            else:
                raise ValueError(
                    f"Name not found: {name} (context: {self._current_module}, "
                    f"available keys: {list(config.keys()) if config else []})"
                )

        raise ValueError(
            f"Name not found: {name} (no context set, use set_context() or use 'module.name' format)"
        )

    def _find_in_config(self, config: dict, name: str) -> Any:
        """
        Найти имя в конфигурации с поиском в подсекциях.

        Сначала ищет прямо в config, затем в подсекциях 'pins' и 'timings'.

        Parameters
        ----------
        config : dict
            Конфигурация секции
        name : str
            Имя для поиска

        Returns
        -------
        Any
            Найденное значение или None
        """
        # Прямой поиск
        if name in config:
            return config[name]

        # Поиск в подсекциях
        for subsection in ['pins', 'timings']:
            if subsection in config and isinstance(config[subsection], dict):
                if name in config[subsection]:
                    return config[subsection][name]

        return None

    def _get_module_config(self, module_name: str) -> dict:
        """
        Получить конфигурацию секции модуля.

        Parameters
        ----------
        module_name : str
            Имя секции конфигурации

        Returns
        -------
        dict
            Конфигурация секции или пустой словарь
        """
        return self._config.get(module_name, {})

    def clear_cache(self) -> None:
        """Очистить кэш разрешенных имен."""
        self._cache.clear()
        logger.debug("[ModuleResolver] Кэш очищен")

    def get_timing(self, module_name: str, timing_name: str, default: Any = None) -> Any:
        """
        Получить тайминг из секции timings модуля.

        Parameters
        ----------
        module_name : str
            Имя модуля
        timing_name : str
            Имя тайминга
        default : Any, optional
            Значение по умолчанию если не найден

        Returns
        -------
        Any
            Значение тайминга или default
        """
        module_config = self._get_module_config(module_name)
        timings = module_config.get('timings', {})
        return timings.get(timing_name, default)

    def get_pin(self, module_name: str, pin_name: str) -> str:
        """
        Получить имя пина из секции pins модуля.

        Parameters
        ----------
        module_name : str
            Имя модуля
        pin_name : str
            Имя пина

        Returns
        -------
        str
            Имя пина (например, "PA6")

        Raises
        ------
        ValueError
            Если пин не найден
        """
        module_config = self._get_module_config(module_name)
        pins = module_config.get('pins', {})
        if pin_name not in pins:
            raise ValueError(f"Pin not found: {pin_name} in module {module_name}")
        return pins[pin_name]
