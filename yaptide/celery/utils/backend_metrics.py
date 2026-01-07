from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Iterable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from celery import signals
from celery.backends import asynchronous as async_backends
from celery.backends import base as celery_backends
from celery.backends.redis import RedisBackend
from kombu.message import Message
from kombu.messaging import Producer
from redis.client import Pipeline

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class _StoreMetricSpec:
    serialize: str
    redis_set: str


@dataclass(frozen=True)
class _FetchMetricSpec:
    redis_get: str
    deserialize: str


_MERGE_TASK = "yaptide.celery.tasks.merge_results"
_MERGING_QUEUED_TASK = "yaptide.celery.tasks.set_merging_queued_state"

_STORE_METRICS: dict[str, _StoreMetricSpec] = {
    "yaptide.celery.tasks.run_single_simulation": _StoreMetricSpec(
        "JSON Serialize (simulation_result)",
        "Redis Set (simulation_result)",
    ),
    _MERGING_QUEUED_TASK: _StoreMetricSpec(
        "JSON Serialize (merging_queued)",
        "Redis Set (merging_queued)",
    ),
}
_CALLBACK_TARGET = _MERGING_QUEUED_TASK
_FETCH_METRICS: dict[str, _FetchMetricSpec] = {
    _CALLBACK_TARGET: _FetchMetricSpec(
        "Redis Get (simulation_result)",
        "JSON Deserialize (simulation_result)",
    )
}

_MERGING_FETCH_SPEC = _FetchMetricSpec(
    "Redis Get (merging_queued)",
    "JSON Deserialize (merging_queued)",
)

_BROKER_SERIALIZE_METRIC = "Broker Serialize (merging_queued)"
_BROKER_PUBLISH_METRIC = "Broker Publish (merging_queued)"
_BROKER_QUEUE_DELAY_METRIC = "Broker Queue Delay (merging_queued)"
_BROKER_DESERIALIZE_METRIC = "Broker Deserialize (merging_queued)"

_ENQUEUE_TS_HEADER = "yaptide_enqueue_ts"
_SIM_HEADER = "yaptide_simulation_id"

_TRANSFER_KEY_PREFIX = "yaptide:transfer_metrics"
_missing_simid_metrics: set[str] = set()
_missing_client_logged = False


@dataclass
class _MetricContext:
    request: Any | None = None
    result: Any | None = None
    backend: celery_backends.BaseBackend | None = None
    serialize_metric: str | None = None
    set_metric: str | None = None
    fetch_metric: str | None = None
    deserialize_metric: str | None = None
    serialize_recorded: bool = False
    set_recorded: bool = False
    fetch_recorded: bool = False


_context_var: ContextVar[_MetricContext | None] = ContextVar("_metric_context", default=None)


@dataclass
class _PendingFetch:
    spec: _FetchMetricSpec
    simulation_id: Any


_pending_fetch: dict[Any, _PendingFetch] = {}
_pending_fetch_by_sim: dict[Any, list[Any]] = {}
_backend_cache: celery_backends.BaseBackend | None = None


@dataclass
class _BrokerPublishContext:
    simulation_id: Any
    backend: celery_backends.BaseBackend | None
    publish_start: float
    serialize_total: float = 0.0
    token: Token | None = None


_broker_context_var: ContextVar[_BrokerPublishContext | None] = ContextVar("_broker_context", default=None)
_broker_signals_connected = False


def _metric_key(sim_id: Any) -> str:
    return f"{_TRANSFER_KEY_PREFIX}:{sim_id}"


def _get_backend() -> celery_backends.BaseBackend | None:
    global _backend_cache
    if _backend_cache is not None:
        return _backend_cache
    try:
        from yaptide.celery.simulation_worker import celery_app  # pylint: disable=import-outside-toplevel

        _backend_cache = celery_app.backend
    except Exception:  # pragma: no cover
        _backend_cache = None
    return _backend_cache
    
def _extract_sim_id_from_mapping(candidate: Any) -> Any:
    try:
        if isinstance(candidate, Mapping) and "simulation_id" in candidate:
            return candidate.get("simulation_id")
    except Exception:  # pragma: no cover
        return None
    return None

def _extract_sim_id(candidate: Any) -> Any:
    sim_id = _extract_sim_id_from_mapping(candidate)
    if sim_id is not None:
        return sim_id
    if isinstance(candidate, Iterable) and not isinstance(candidate, (str, bytes, Mapping)):
        for item in candidate:
            sim_id = _extract_sim_id(item)
            if sim_id is not None:
                return sim_id
    return None

def _resolve_simulation_id(request: Any, result: Any) -> Any:
    if request is not None:
        sim_id = _extract_sim_id(getattr(request, "kwargs", None))
        if sim_id is not None:
            return sim_id
        sim_id = _extract_sim_id(getattr(request, "args", None))
        if sim_id is not None:
            return sim_id
    return _extract_sim_id(result)

def _append_metric(backend: celery_backends.BaseBackend,
                   request: Any,
                   result: Any,
                   metric: str,
                   duration: float) -> None:
    if metric is None:
        return
    sim_id = _resolve_simulation_id(request, result)
    if sim_id is None:
        if metric not in _missing_simid_metrics:
            _missing_simid_metrics.add(metric)
            logger.warning("Transfer metric %s skipped: simulation_id missing in task %s", metric,
                           getattr(request, "task", None))
        return
    _append_metric_for_sim(backend, sim_id, metric, duration)


def _append_metric_for_sim(backend: celery_backends.BaseBackend | None,
                           sim_id: Any,
                           metric: str,
                           duration: float) -> None:
    if backend is None or sim_id is None or metric is None:
        return
    client = getattr(backend, "client", None)
    if client is None:
        global _missing_client_logged
        if not _missing_client_logged:
            logger.warning("Transfer metrics disabled: backend %s has no client", type(backend).__name__)
            _missing_client_logged = True
        return
    payload = json.dumps({"metric": metric, "duration": duration})
    key = _metric_key(sim_id)
    ttl = getattr(backend, "expires", None) or 86400
    try:
        client.rpush(key, payload)
        client.expire(key, int(ttl))
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to append metric %s for sim %s: %s", metric, sim_id, exc)


def record_metric_for_simulation(backend: celery_backends.BaseBackend | None,
                                 sim_id: Any,
                                 metric: str,
                                 duration: float) -> None:
    _append_metric_for_sim(backend, sim_id, metric, duration)

def drain_metrics(backend: celery_backends.BaseBackend, sim_id: Any) -> dict[str, list[float]]:
    client = getattr(backend, "client", None)
    if client is None or sim_id is None:
        return {}
    key = _metric_key(sim_id)
    try:
        entries = client.lrange(key, 0, -1)
        client.delete(key)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to drain metrics for sim %s: %s", sim_id, exc)
        return {}
    metrics: dict[str, list[float]] = {}
    for entry in entries or []:
        try:
            payload = json.loads(entry)
            metric_name = payload.get("metric")
            duration = float(payload.get("duration"))
        except Exception:
            continue
        metrics.setdefault(metric_name, []).append(duration)
    return metrics

def _get_context() -> _MetricContext | None:
    return _context_var.get()


def _instrument_store_result() -> None:
    backend_cls = getattr(celery_backends, "BaseKeyValueStoreBackend", None)
    if backend_cls is None or getattr(backend_cls, "_yaptide_store_instrumented", False):
        return

    original = backend_cls.store_result

    def wrapped_store_result(self, task_id: Any, result: Any, state: str, *args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request")
        task_name = getattr(request, "task", None) if request else None
        spec = _STORE_METRICS.get(task_name)
        token = None
        if spec is not None:
            ctx = _MetricContext(
                request=request,
                result=result,
                backend=self,
                serialize_metric=spec.serialize,
                set_metric=spec.redis_set,
            )
            token = _context_var.set(ctx)
            if task_name == "yaptide.celery.tasks.set_merging_queued_state":
                sim_id = _resolve_simulation_id(request, result)
                if sim_id is not None:
                    _pending_fetch[task_id] = _PendingFetch(spec=_MERGING_FETCH_SPEC,
                                                             simulation_id=sim_id)
                    _pending_fetch_by_sim.setdefault(sim_id, []).append(task_id)
        try:
            return original(self, task_id, result, state, *args, **kwargs)
        finally:
            if token is not None:
                _context_var.reset(token)

    backend_cls.store_result = wrapped_store_result  # type: ignore[assignment]
    backend_cls._yaptide_store_instrumented = True
    logger.info("Celery BaseKeyValueStoreBackend store_result instrumentation enabled")


def _instrument_encode() -> None:
    def wrap(cls: type, label: str) -> None:
        if cls is None or getattr(cls, "_yaptide_encode_instrumented", False):
            return

        original = cls.encode

        def wrapped_encode(self, data: Any, *args: Any, **kwargs: Any) -> Any:
            ctx = _get_context()
            metric = ctx.serialize_metric if ctx else None
            active = bool(metric) and not ctx.serialize_recorded if ctx else False
            start = time.perf_counter() if active else None
            try:
                return original(self, data, *args, **kwargs)
            finally:
                if active and ctx and start is not None:
                    ctx.serialize_recorded = True
                    duration = time.perf_counter() - start
                    _append_metric(self, ctx.request, ctx.result, metric, duration)

        cls.encode = wrapped_encode  # type: ignore[assignment]
        cls._yaptide_encode_instrumented = True
        logger.info("Celery %s encode instrumentation enabled", label)

    wrap(getattr(celery_backends, "BaseBackend", None), "BaseBackend")
    wrap(RedisBackend, "RedisBackend")
    wrap(getattr(async_backends, "RedisBackend", None), "AsyncRedisBackend")


def _instrument_decode() -> None:
    def wrap(cls: type, label: str) -> None:
        if cls is None or getattr(cls, "_yaptide_decode_instrumented", False):
            return

        original = cls.decode

        def wrapped_decode(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
            ctx = _get_context()
            metric = ctx.deserialize_metric if ctx else None
            active = bool(metric)
            start = time.perf_counter() if active else None
            try:
                return original(self, payload, *args, **kwargs)
            finally:
                if active and ctx and start is not None:
                    duration = time.perf_counter() - start
                    _append_metric(self, ctx.request, ctx.result, metric, duration)

        cls.decode = wrapped_decode  # type: ignore[assignment]
        cls._yaptide_decode_instrumented = True
        logger.info("Celery %s decode instrumentation enabled", label)

    wrap(getattr(celery_backends, "BaseBackend", None), "BaseBackend")
    wrap(RedisBackend, "RedisBackend")
    wrap(getattr(async_backends, "RedisBackend", None), "AsyncRedisBackend")


def _instrument_redis_set() -> None:
    def wrap(cls: type) -> None:
        if cls is None or getattr(cls, "_yaptide_redis_io_instrumented", False):
            return

        def instrument(method_name: str, metric_attr: str, flag_attr: str) -> None:
            if not hasattr(cls, method_name):
                return

            original = getattr(cls, method_name)

            def wrapped(self, *args: Any, **kwargs: Any):
                ctx = _get_context()
                metric = getattr(ctx, metric_attr) if ctx else None
                recorded = getattr(ctx, flag_attr) if ctx else False
                active = bool(metric) and not recorded
                start = time.perf_counter() if active else None
                try:
                    return original(self, *args, **kwargs)
                finally:
                    if active and ctx and start is not None:
                        setattr(ctx, flag_attr, True)
                        duration = time.perf_counter() - start
                        _append_metric(self, ctx.request, ctx.result, metric, duration)

            setattr(cls, method_name, wrapped)

        instrument("set", "set_metric", "set_recorded")
        instrument("get", "fetch_metric", "fetch_recorded")
        cls._yaptide_redis_io_instrumented = True
        logger.info("Celery %s redis IO instrumentation enabled", cls.__name__)

    wrap(RedisBackend)
    wrap(getattr(async_backends, "RedisBackend", None))


def _instrument_pipeline_execute() -> None:
    if getattr(Pipeline, "_yaptide_execute_instrumented", False):
        return

    original = Pipeline.execute
    fetch_commands = {"LRANGE", "ZRANGE", "ZRANGEBYSCORE", "ZRANGEWITHSCORES", "ZREVRANGE"}

    def wrapped_execute(self, *args: Any, **kwargs: Any):
        ctx = _get_context()
        measure = False
        if ctx and ctx.fetch_metric and not ctx.fetch_recorded:
            for command, _ in getattr(self, "command_stack", []) or []:
                if not command:
                    continue
                name = command[0]
                if isinstance(name, bytes):
                    name = name.decode()
                name = str(name).upper()
                if name in fetch_commands:
                    measure = True
                    break
        start = time.perf_counter() if measure else None
        try:
            return original(self, *args, **kwargs)
        finally:
            if measure and ctx and start is not None and ctx.backend is not None:
                ctx.fetch_recorded = True
                duration = time.perf_counter() - start
                _append_metric(ctx.backend, ctx.request, ctx.result, ctx.fetch_metric, duration)

    Pipeline.execute = wrapped_execute  # type: ignore[assignment]
    Pipeline._yaptide_execute_instrumented = True
    logger.info("Redis pipeline execute instrumentation enabled")


def _before_task_publish_handler(sender=None, body=None, headers=None, **kwargs):  # noqa: D401
    if sender != _MERGE_TASK:
        return
    headers = headers or {}
    body = body or ()
    sim_id = _extract_sim_id(body)
    if sim_id is None:
        return
    backend = _get_backend()
    if backend is None:
        return
    headers[_ENQUEUE_TS_HEADER] = time.time()
    headers[_SIM_HEADER] = sim_id
    ctx = _BrokerPublishContext(simulation_id=sim_id,
                                backend=backend,
                                publish_start=time.perf_counter())
    ctx.token = _broker_context_var.set(ctx)


def _after_task_publish_handler(sender=None, headers=None, **kwargs):  # noqa: D401
    if sender != _MERGE_TASK:
        return
    ctx = _broker_context_var.get()
    if ctx is None:
        return
    total = time.perf_counter() - ctx.publish_start
    serialize = ctx.serialize_total
    _append_metric_for_sim(ctx.backend, ctx.simulation_id, _BROKER_SERIALIZE_METRIC, serialize)
    publish_only = max(total - serialize, 0.0)
    _append_metric_for_sim(ctx.backend, ctx.simulation_id, _BROKER_PUBLISH_METRIC, publish_only)
    if ctx.token is not None:
        _broker_context_var.reset(ctx.token)


def _instrument_producer_prepare() -> None:
    if getattr(Producer, "_yaptide_prepare_instrumented", False):
        return

    original = Producer._prepare

    def wrapped_prepare(self, *args: Any, **kwargs: Any):
        ctx = _broker_context_var.get()
        start = time.perf_counter() if ctx else None
        try:
            return original(self, *args, **kwargs)
        finally:
            if ctx and start is not None:
                ctx.serialize_total += time.perf_counter() - start

    Producer._prepare = wrapped_prepare  # type: ignore[assignment]
    Producer._yaptide_prepare_instrumented = True
    logger.info("Kombu Producer serialization instrumentation enabled")


def _instrument_producer_publish_cleanup() -> None:
    if getattr(Producer, "_yaptide_publish_instrumented", False):
        return

    original = Producer.publish

    def wrapped_publish(self, *args: Any, **kwargs: Any):
        try:
            return original(self, *args, **kwargs)
        except Exception:
            ctx = _broker_context_var.get()
            if ctx and ctx.token is not None:
                try:
                    _broker_context_var.reset(ctx.token)
                except LookupError:
                    pass
            raise

    Producer.publish = wrapped_publish  # type: ignore[assignment]
    Producer._yaptide_publish_instrumented = True


def _instrument_message_decode() -> None:
    if getattr(Message, "_yaptide_decode_instrumented", False):
        return

    original = Message._decode

    def wrapped_decode(self: Message):
        headers = getattr(self, "headers", None) or {}
        sim_id = headers.get(_SIM_HEADER)
        should_measure = headers.get("task") == _MERGE_TASK and sim_id is not None and not headers.get(
            "_yaptide_decode_recorded")
        if not should_measure:
            return original(self)
        headers["_yaptide_decode_recorded"] = True
        backend = _get_backend()
        start = time.perf_counter()
        try:
            return original(self)
        finally:
            duration = time.perf_counter() - start
            _append_metric_for_sim(backend, sim_id, _BROKER_DESERIALIZE_METRIC, duration)

    Message._decode = wrapped_decode  # type: ignore[assignment]
    Message._yaptide_decode_instrumented = True
    logger.info("Broker deserialize instrumentation enabled")


def _instrument_broker_publish() -> None:
    global _broker_signals_connected
    if not _broker_signals_connected:
        signals.before_task_publish.connect(_before_task_publish_handler, weak=False)
        signals.after_task_publish.connect(_after_task_publish_handler, weak=False)
        _broker_signals_connected = True
    _instrument_producer_prepare()
    _instrument_producer_publish_cleanup()


def _instrument_task_meta_fetch() -> None:
    backend_cls = getattr(celery_backends, "BaseKeyValueStoreBackend", None)
    if backend_cls is None or getattr(backend_cls, "_yaptide_meta_instrumented", False):
        return

    original = backend_cls._get_task_meta_for

    def wrapped_get_task_meta(self, task_id: Any):
        ctx = _get_context()
        if ctx and (ctx.serialize_metric or ctx.set_metric):
            return original(self, task_id)

        pending = _pending_fetch.get(task_id)
        token = None
        if pending is not None:
            ctx_fetch = _MetricContext(
                request=None,
                result={"simulation_id": pending.simulation_id},
                backend=self,
                fetch_metric=pending.spec.redis_get,
                deserialize_metric=pending.spec.deserialize,
            )
            token = _context_var.set(ctx_fetch)

        try:
            return original(self, task_id)
        finally:
            if token is not None:
                _context_var.reset(token)
                removed = _pending_fetch.pop(task_id, None)
                if removed is not None:
                    sim_entries = _pending_fetch_by_sim.get(removed.simulation_id)
                    if sim_entries and task_id in sim_entries:
                        sim_entries.remove(task_id)
                        if not sim_entries:
                            _pending_fetch_by_sim.pop(removed.simulation_id, None)

    backend_cls._get_task_meta_for = wrapped_get_task_meta  # type: ignore[assignment]
    backend_cls._yaptide_meta_instrumented = True
    logger.info("Celery BaseKeyValueStoreBackend task-meta instrumentation enabled")

def _instrument_chord_gather() -> None:
    if getattr(RedisBackend, "_yaptide_chord_instrumented", False):
        redis_backend = None
    else:
        redis_backend = RedisBackend

    async_backend_cls = getattr(async_backends, "RedisBackend", None)
    if async_backend_cls is not None and getattr(async_backend_cls, "_yaptide_chord_instrumented", False):
        async_backend = None
    else:
        async_backend = async_backend_cls

    if redis_backend is None and async_backend is None:
        return

    def wrap(cls):
        original = cls.on_chord_part_return

        def wrapped_on_chord_part_return(self, request, state, result, *args: Any, **kwargs: Any) -> Any:
            chord = getattr(request, "chord", None)
            callback = None
            if chord is not None:
                callback = getattr(chord, "task", None)
                if callback is None and isinstance(chord, Mapping):
                    callback = chord.get("task")

            spec = _FETCH_METRICS.get(callback)
            token = None
            if spec is not None:
                ctx = _MetricContext(
                    request=request,
                    result=result,
                    backend=self,
                    fetch_metric=spec.redis_get,
                    deserialize_metric=spec.deserialize,
                )
                token = _context_var.set(ctx)

            try:
                return original(self, request, state, result, *args, **kwargs)
            finally:
                if token is not None:
                    _context_var.reset(token)

        cls.on_chord_part_return = wrapped_on_chord_part_return  # type: ignore[assignment]
        cls._yaptide_chord_instrumented = True

    if redis_backend is not None:
        wrap(redis_backend)
        logger.info("Celery redis chord instrumentation enabled")
    if async_backend is not None:
        wrap(async_backend)
        logger.info("Celery async chord instrumentation enabled")


def ensure_merge_fetch(backend: celery_backends.BaseBackend, sim_id: Any) -> None:
    if backend is None or sim_id is None:
        return
    task_ids = _pending_fetch_by_sim.pop(sim_id, None)
    if not task_ids:
        return

    for task_id in list(task_ids):
        with contextlib.suppress(Exception):
            backend._get_task_meta_for(task_id)
        _pending_fetch.pop(task_id, None)

def enable() -> None:
    try:
        _instrument_store_result()
        _instrument_encode()
        _instrument_decode()
        _instrument_redis_set()
        _instrument_pipeline_execute()
        _instrument_broker_publish()
        _instrument_message_decode()
        _instrument_task_meta_fetch()
        _instrument_chord_gather()
        logger.info("Backend transfer instrumentation active")
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to enable backend metrics: %s", exc)


enable()
