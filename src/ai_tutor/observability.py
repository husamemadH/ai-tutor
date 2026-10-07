import asyncio
import json
import logging
import math
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

logger = logging.getLogger("ai_tutor.events")


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"time": datetime.now(UTC).isoformat(), "event": event, **fields}))


def elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)


def failure_reason(exc: BaseException) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "provider_http_error"
    if isinstance(exc, httpx.TransportError):
        return "connection_error"
    return type(exc).__name__


@dataclass
class RequestObservation:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.monotonic)
    outcome: str | None = None
    reason: str | None = None
    first_text_ms: float | None = None


current_request: ContextVar[RequestObservation | None] = ContextVar(
    "observed_request", default=None
)


def mark_chat_started() -> None:
    if observation := current_request.get():
        observation.outcome = "cancelled"


def mark_first_text() -> None:
    if (observation := current_request.get()) and observation.first_text_ms is None:
        observation.first_text_ms = elapsed_ms(observation.started)


def mark_outcome(outcome: str, exc: BaseException | None = None) -> None:
    if observation := current_request.get():
        observation.outcome = outcome
        observation.reason = failure_reason(exc) if exc else None


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        observation = RequestObservation()
        token = current_request.set(observation)
        status = None
        response_complete = False

        async def observed_send(message):
            nonlocal status, response_complete
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", observation.request_id.encode("ascii")),
                    ],
                }
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True

        try:
            await self.app(scope, receive, observed_send)
        except BaseException as exc:
            if isinstance(
                exc, (asyncio.CancelledError, GeneratorExit, BrokenPipeError, ConnectionResetError)
            ):
                if observation.outcome != "completed":
                    mark_outcome("cancelled")
            else:
                mark_outcome("failed", exc)
            raise
        finally:
            if observation.outcome is None:
                if status == 429:
                    observation.outcome = "busy"
                elif status and status >= 500:
                    observation.outcome = "failed"
                elif status and status >= 400:
                    observation.outcome = "rejected"
                else:
                    observation.outcome = "completed" if response_complete else "cancelled"
            route = scope.get("route")
            log_event(
                "request_finished",
                request_id=observation.request_id,
                method=scope["method"],
                route=getattr(route, "path", "unmatched"),
                status=status,
                outcome=observation.outcome,
                reason=observation.reason,
                duration_ms=elapsed_ms(observation.started),
                first_text_ms=observation.first_text_ms,
                response_complete=response_complete,
            )
            current_request.reset(token)


@dataclass
class ProviderObservation:
    status: int | None = None
    usage: dict = field(default_factory=dict)

    def record_usage(self, usage) -> None:
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost"):
            value = usage.get(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                self.usage[key] = value


@contextmanager
def observe_provider(provider: str, operation: str, model: str):
    started = time.monotonic()
    observation = ProviderObservation()
    request = current_request.get()
    outcome = "completed"
    reason = None
    try:
        yield observation
    except BaseException as exc:
        outcome = (
            "cancelled" if isinstance(exc, (GeneratorExit, asyncio.CancelledError)) else "failed"
        )
        reason = failure_reason(exc) if outcome == "failed" else None
        raise
    finally:
        log_event(
            "provider_finished",
            request_id=request.request_id if request else None,
            provider=provider,
            operation=operation,
            model=model,
            status=observation.status,
            outcome=outcome,
            reason=reason,
            duration_ms=elapsed_ms(started),
            **observation.usage,
        )
