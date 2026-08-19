"""
Неблокирующий проигрыватель звуковых эффектов (SoundPlayer).

Использует очередь и фоновый поток для воспроизведения wav/mp3 файлов
без блокировки основного потока.
"""

import logging
import os
import subprocess
import threading
from queue import Empty, Full, Queue

logger = logging.getLogger(__name__)


class SoundPlayer:
    """
    Неблокирующий проигрыватель звуковых эффектов.

    Parameters
    ----------
    sound_dir : str, optional
        Директория с звуковыми файлами. По умолчанию "sounds".
    player_cmd : str, optional
        Команда для воспроизведения. По умолчанию "aplay" для wav.
        Для mp3 можно использовать "mpg123" или "ffplay".
    """

    def __init__(
        self,
        sound_dir: str,
        player_cmd: str,
        sound_queue_maxsize: int,
        stop_timeout: float = 5.0,
        play_timeout: float = 10.0,
    ):
        """Инициализировать проигрыватель."""
        self.sound_dir = sound_dir
        self.player_cmd = player_cmd
        self._stop_timeout = stop_timeout
        self._play_timeout = play_timeout

        # Очередь для звуковых эффектов
        self._queue: Queue = Queue(maxsize=sound_queue_maxsize)

        # Событие остановки
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Запустить фоновый поток воспроизведения."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[SoundPlayer] Поток уже запущен.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._play_loop,
            name="SoundPlayer",
            daemon=True,
        )
        self._thread.start()
        logger.info("[SoundPlayer] Поток запущен.")

    def stop(self, timeout: float | None = None) -> None:
        """
        Остановить фоновый поток воспроизведения.

        Parameters
        ----------
        timeout : float
            Максимальное время ожидания завершения (с).
        """
        if self._thread is None or not self._thread.is_alive():
            logger.info("[SoundPlayer] Поток не запущен.")
            return

        if timeout is None:
            timeout = self._stop_timeout
        self._stop_event.set()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(
                "[SoundPlayer] Поток не завершился за %ss.", timeout
            )
        else:
            logger.info("[SoundPlayer] Поток остановлен.")

    def play_effect(self, sound_name: str) -> None:
        """
        Воспроизвести звуковой эффект (неблокирующий).

        Parameters
        ----------
        sound_name : str
            Имя звукового файла без расширения (например, "success").
        """
        try:
            self._queue.put_nowait(sound_name)
        except Full as e:
            logger.warning("[SoundPlayer] Очередь переполнена: %s", e)

    def _play_loop(self) -> None:
        """Основной цикл воспроизведения."""
        logger.info("[SoundPlayer] Запуск цикла воспроизведения.")

        while not self._stop_event.is_set():
            try:
                sound_name = self._queue.get(timeout=0.1)
                self._play_sound(sound_name)
            except Empty:
                continue
            except Exception as e:  # noqa: BLE001
                logger.exception("[SoundPlayer] Ошибка воспроизведения: %s", e)

        logger.info("[SoundPlayer] Цикл воспроизведения завершен.")

    def _play_sound(self, sound_name: str) -> None:
        """
        Воспроизвести звуковой файл.

        Parameters
        ----------
        sound_name : str
            Имя звукового файла без расширения.
        """
        # Проверяем расширения в порядке приоритета
        extensions = ['.wav', '.mp3']
        sound_path = None

        for ext in extensions:
            path = os.path.join(self.sound_dir, f"{sound_name}{ext}")
            if os.path.exists(path):
                sound_path = path
                break

        if sound_path is None:
            logger.warning(f"[SoundPlayer] Файл не найден: {sound_name}")
            return

        try:
            # Выбираем команду в зависимости от расширения
            if sound_path.endswith('.mp3'):
                cmd = ["mpg123", "-q", sound_path]
            else:
                cmd = [self.player_cmd, "-q", sound_path]

            subprocess.run(cmd, check=True, timeout=self._play_timeout)
            logger.debug(f"[SoundPlayer] Воспроизведен: {sound_path}")
        except subprocess.TimeoutExpired:
            logger.warning(f"[SoundPlayer] Таймаут воспроизведения: {sound_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"[SoundPlayer] Ошибка воспроизведения: {e}")
        except Exception as e:  # noqa: BLE001
            logger.exception("[SoundPlayer] Неизвестная ошибка: %s", e)
