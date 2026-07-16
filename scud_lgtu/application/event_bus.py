"""
Event bus for application layer.

Реализует паттерн Publisher-Subscriber для асинхронной обработки событий.
Поддерживает как синхронные, так и асинхронные обработчики.
"""
import asyncio
import threading
from typing import Callable, Dict, List, Any
from collections import defaultdict


class EventBus:
    """
    Шина событий для публикации и подписки на события.

    Поддерживает синхронные и асинхронные обработчики событий.
    Во время тревоги игнорирует все события кроме PassageDetected (датчики).

    Attributes
    ----------
    _subscribers : Dict[str, List[Callable]]
        Словарь подписчиков по типам событий
    _loop : asyncio.AbstractEventLoop
        Event loop для асинхронных обработчиков
    _lock : threading.Lock
        Блокировка для потокобезопасности
    _turnstile : TurnstileState
        Состояние турникета для проверки тревоги
    """

    def __init__(self, turnstile=None):
        """
        Инициализировать шину событий.

        Parameters
        ----------
        turnstile : TurnstileState, optional
            Состояние турникета для фильтрации событий во время тревоги
        """
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._loop = None
        self._lock = threading.Lock()
        self._turnstile = turnstile  # Для проверки состояния тревоги

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """
        Подписаться на тип события.

        Parameters
        ----------
        event_type : str
            Имя типа события (например, "CardRead", "QrRead")
        handler : Callable
            Функция-обработчик события (синхронная или асинхронная)
        """
        with self._lock:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """
        Отписаться от типа события.

        Parameters
        ----------
        event_type : str
            Имя типа события
        handler : Callable
            Функция-обработчик для удаления
        """
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].remove(handler)

    def publish(self, event: Any) -> None:
        """
        Опубликовать событие всем подписчикам.

        Parameters
        ----------
        event : Any
            Объект события для публикации

        Note
        ----
        Во время тревоги игнорируются все события кроме PassageDetected (датчики).
        Это необходимо для точного подсчета людей во время эвакуации.
        """
        event_type = type(event).__name__

        # Во время тревоги игнорировать все события кроме PassageDetected (датчики)
        if self._turnstile and self._turnstile._current_state == "ALARM":
            if event_type != "PassageDetected":
                return  # Игнорировать все события кроме датчиков

        with self._lock:
            handlers = self._subscribers.get(event_type, []).copy()

        for handler in handlers:
            try:
                # Вызываем обработчик и проверяем, является ли результат корутиной
                result = handler(event)

                if asyncio.iscoroutine(result):
                    # Если результат - корутина, планируем её как задачу
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(
                            lambda c=result: asyncio.create_task(c)
                        )
                # Если результат не корутина, это был синхронный обработчик
            except Exception as e:
                # Логируем ошибку, но не прерываем работу
                print(f"Error in event handler: {e}")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Установить event loop для асинхронных обработчиков.

        Parameters
        ----------
        loop : asyncio.AbstractEventLoop
            Event loop для планирования асинхронных задач
        """
        self._loop = loop
