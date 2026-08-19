"""Тесты SyncService — синхронизация списка доступа и событий (п. 5.4.3, §6.5 ТЗ)."""
from app.application.services.sync_service import SyncService
from app.infrastructure.persistence.event_store import EventStore, PassageEvent


class FakeBackendGateway:
    def __init__(self, online=True, access_response=None, send_events_result=True,
                 last_event=None, last_event_raises=True):
        self._online = online
        self._access_response = access_response or {"status": "ok", "update": 0, "id": []}
        self._send_events_result = send_events_result
        self.access_calls = []
        self.sent_events = []
        self._last_event = last_event
        # По умолчанию get_last_event "не реализован" в фейке (как если бы
        # бэкенд был недоступен) — это то, что происходит в тестах, где
        # сверка event_id не является предметом проверки.
        self._last_event_raises = last_event_raises
        self.get_last_event_calls = 0

    def is_online(self):
        return self._online

    def get_access_list(self, update=1):
        self.access_calls.append(update)
        return self._access_response

    def send_events(self, events):
        self.sent_events.append(list(events))
        return self._send_events_result

    def get_last_event(self):
        self.get_last_event_calls += 1
        if self._last_event_raises:
            raise RuntimeError("бэкенд недоступен")
        return self._last_event or {"event_id": 0}


class FakeAccessRepository:
    def __init__(self):
        self.updates = []

    def update(self, data):
        self.updates.append(data)


def _event(token="a") -> PassageEvent:
    return PassageEvent(event_type="access", direction="in", token_type="maxid", token=token, result="pass")


def test_first_sync_forces_full_update():
    backend = FakeBackendGateway()
    repo = FakeAccessRepository()
    store = EventStore()
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)

    assert backend.access_calls == [0]
    assert len(repo.updates) == 1


def test_second_sync_uses_delta_update():
    backend = FakeBackendGateway()
    repo = FakeAccessRepository()
    store = EventStore()
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)
    service.tick(now=1600.0)

    assert backend.access_calls == [0, 1]


def test_force_full_update_resets_flag():
    backend = FakeBackendGateway()
    repo = FakeAccessRepository()
    store = EventStore()
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)
    service.tick(now=1000.0)  # update=0
    service.tick(now=1600.0)  # update=1

    service.force_full_update()
    service.tick(now=2200.0)

    assert backend.access_calls == [0, 1, 0]


def test_events_requeued_when_backend_offline():
    backend = FakeBackendGateway(online=False)
    repo = FakeAccessRepository()
    store = EventStore()
    store.append(_event())
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)

    assert backend.sent_events == []
    assert store.count() == 1  # событие не потеряно


def test_events_requeued_when_send_fails():
    backend = FakeBackendGateway(send_events_result=False)
    repo = FakeAccessRepository()
    store = EventStore()
    store.append(_event())
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)

    assert len(backend.sent_events) == 1
    assert store.count() == 1  # возвращено в очередь после неудачи


def test_events_not_requeued_on_success():
    backend = FakeBackendGateway(send_events_result=True)
    repo = FakeAccessRepository()
    store = EventStore()
    store.append(_event())
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)

    assert store.count() == 0


class _EventLogAdapterLike:
    """Минимальная обёртка над EventStore с интерфейсом EventLogAdapter."""

    def __init__(self, store: EventStore):
        self._store = store

    def flush(self):
        return self._store.flush()

    def requeue(self, events):
        self._store.requeue(events)

    def peek_next_event_id(self):
        return self._store.peek_next_event_id()

    def oldest_pending_event_id(self):
        return self._store.oldest_pending_event_id()


def test_reconciliation_happens_once_after_successful_get_last_event():
    backend = FakeBackendGateway(last_event={"event_id": 5}, last_event_raises=False)
    repo = FakeAccessRepository()
    store = EventStore()
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)
    service.tick(now=1600.0)
    service.tick(now=2200.0)

    assert backend.get_last_event_calls == 1  # сверка выполняется один раз


def test_reconciliation_retries_until_backend_reachable():
    backend = FakeBackendGateway(last_event_raises=True)
    repo = FakeAccessRepository()
    store = EventStore()
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    service.tick(now=1000.0)
    service.tick(now=1600.0)

    assert backend.get_last_event_calls == 2  # не сверилось - пробует снова


def test_reconciliation_logs_critical_on_gap(caplog):
    # Бэкенд подтвердил только до 3, но локально следующий event_id будет 10 -
    # значит события 4..9 потеряны безвозвратно.
    backend = FakeBackendGateway(last_event={"event_id": 3}, last_event_raises=False)
    repo = FakeAccessRepository()
    store = EventStore()
    store._next_event_id = 10
    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    with caplog.at_level("CRITICAL"):
        service.tick(now=1000.0)

    assert any("разрыв event_id" in record.message for record in caplog.records)


def test_reconciliation_no_gap_when_pending_already_covers_confirmed(caplog):
    backend = FakeBackendGateway(last_event={"event_id": 3}, last_event_raises=False)
    repo = FakeAccessRepository()
    store = EventStore()
    for _ in range(4):
        store.append(_event())  # event_id 1..4, всё ещё в очереди (не flush)

    service = SyncService(backend, _EventLogAdapterLike(store), repo, sync_interval=600)

    with caplog.at_level("CRITICAL"):
        service.tick(now=1000.0)

    # oldest_pending=1 <= confirmed(3)+1 -> нет разрыва, критических записей нет.
    assert not any("разрыв event_id" in record.message for record in caplog.records)
