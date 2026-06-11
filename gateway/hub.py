"""Change-stream hub — MongoDB Atlas is the event bus.

A single watcher thread holds one change stream over the whole kickoff
database. Every write any agent makes (through MCP or the driver) becomes
a change event, fanned out to every connected SSE client. The UI therefore
shows *actual database writes*, not synthetic notifications — when a card
appears in the decision feed, that is the insert hitting Atlas.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from agents.common import mongo

logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class ChangeStreamHub:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.Thread(target=self._watch_forever, name="mongo-change-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def _publish(self, event: dict) -> None:
        if self._loop is None:
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            def _put(q=q):
                if q.full():
                    try:
                        q.get_nowait()  # drop oldest under backpressure
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(event)
            self._loop.call_soon_threadsafe(_put)

    def _watch_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                db = mongo.db()
                with db.watch(full_document="updateLookup", max_await_time_ms=1000) as stream:
                    self.connected = True
                    backoff = 1.0
                    logger.info("change stream open on db=%s", db.name)
                    while not self._stop.is_set():
                        change = stream.try_next()
                        if change is None:
                            continue
                        coll = change.get("ns", {}).get("coll", "")
                        if coll.startswith("_") or coll not in mongo.WATCHED_COLLECTIONS:
                            continue
                        doc = change.get("fullDocument") or {}
                        self._publish(
                            {
                                "type": "change",
                                "collection": coll,
                                "operation": change.get("operationType"),
                                "doc": _jsonable(doc),
                                "ts": datetime.now(timezone.utc).isoformat(),
                            }
                        )
            except Exception as e:  # noqa: BLE001 — reconnect on any stream failure
                self.connected = False
                logger.warning("change stream lost (%s); reconnecting in %.0fs", str(e)[:120], backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)


hub = ChangeStreamHub()
