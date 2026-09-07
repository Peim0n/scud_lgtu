"""Доменные сервисы и политики доступа."""
from app.domain.enums import DirectionEnum
from app.domain.models import AccessDecision, AuthSession, Credential


class AccessPolicy:
    """
    Политика доступа для проверки учётных данных.

    Использует порт AccessRepository для проверки разрешений на основе учётных данных.
    """

    def __init__(self, repository=None):
        """
        Инициализировать политику доступа с репозиторием.

        Parameters
        ----------
        repository : AccessRepository, optional
            Репозиторий доступа для проверки разрешений. Если None, доступ всегда запрещен.
        """
        self._repository = repository

    def check(self, credential: Credential) -> AccessDecision:
        """
        Проверить, разрешены ли учётные данные.

        Parameters
        ----------
        credential : Credential
            Учётные данные для проверки (карта, QR-код и т.д.)

        Returns
        -------
        AccessDecision
            Решение о доступе (разрешено/запрещено) с причиной
        """
        if self._repository is None:
            return AccessDecision(allowed=False, reason="No repository configured")

        # Делегировать проверку репозиторию
        return self._repository.is_allowed(credential)


class PassageTracker:
    """
    Отслеживание проходов для предотвращения двойных проходов.

    Хранит информацию о последних проходах для каждого токена (карты/QR-кода).
    Предотвращает повторный вход с тем же токеном до завершения прохода.
    """

    def __init__(self):
        """Инициализировать отслеживание проходов."""
        # Формат: {token: {"direction": "in"/"out", "passed": bool}}
        self._last_passages = {}

    def track(self, session: AuthSession) -> None:
        """
        Отследить новую сессию прохода.

        Parameters
        ----------
        session : AuthSession
            Сессия авторизации для отслеживания
        """
        self._last_passages[session.token] = {
            "direction": session.direction.value,
            "passed": session.used
        }

    def is_double_pass(self, token: str, direction: DirectionEnum) -> bool:
        """
        Проверить, является ли это двойным проходом.

        Parameters
        ----------
        token : str
            Токен учётных данных
        direction : DirectionEnum
            Направление прохода

        Returns
        -------
        bool
            True если это двойной проход в том же направлении, False иначе
        """
        if token not in self._last_passages:
            return False

        last_passage = self._last_passages[token]

        # Двойной проход если направление совпадает и предыдущий проход завершен
        return last_passage["direction"] == direction.value and last_passage["passed"]

    def mark_completed(self, token: str) -> None:
        """
        Отметить проход как завершённый.

        Parameters
        ----------
        token : str
            Токен учётных данных
        """
        if token in self._last_passages:
            self._last_passages[token]["passed"] = True

    def mark_passed(self, token: str) -> None:
        """
        Отметить проход как завершённый (синоним mark_completed).

        Parameters
        ----------
        token : str
            Токен учётных данных
        """
        self.mark_completed(token)
