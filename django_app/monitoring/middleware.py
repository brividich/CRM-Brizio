from __future__ import annotations

import logging
from time import perf_counter

from django.conf import settings
from django.utils import timezone

from .models import Issue
from .services import (
    build_request_event_context,
    get_exception_traceback,
    open_or_update_issue_from_web_error,
)

logger = logging.getLogger(__name__)


class IssueCaptureMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = bool(getattr(settings, "MONITORING_ENABLED", True))
        self.capture_403 = bool(getattr(settings, "MONITORING_CAPTURE_403", True))
        self.capture_404 = bool(getattr(settings, "MONITORING_CAPTURE_404", False))
        self.slow_request_threshold_ms = int(getattr(settings, "MONITORING_SLOW_REQUEST_THRESHOLD_MS", 3000) or 0)
        self.ignore_prefixes = (
            "/health",
            "/version",
            "/static/",
            "/media/",
            "/favicon",
            "/monitoring/",
            "/admin-portale/monitoring/",
        )

    def __call__(self, request):
        if not self.enabled or self._should_ignore(request):
            return self.get_response(request)

        started = perf_counter()
        try:
            response = self.get_response(request)
        except Exception as exc:
            self._safe_capture_exception(request, exc)
            raise

        elapsed_ms = int((perf_counter() - started) * 1000)
        self._safe_capture_response(request, response, elapsed_ms)
        return response

    def _should_ignore(self, request) -> bool:
        path = str(getattr(request, "path", "") or "")
        if any(path.startswith(prefix) for prefix in self.ignore_prefixes):
            return True
        return path in {"/health", "/version"}

    def _safe_capture_exception(self, request, exc: Exception) -> None:
        try:
            event = build_request_event_context(request)
            open_or_update_issue_from_web_error(
                category=Issue.Category.SYSTEM,
                severity=Issue.Severity.CRITICAL,
                source=Issue.Source.WEB,
                status_code=500,
                method=event["method"],
                current_url=event["current_url"],
                route_name=event["route_name"],
                module_name=event["module_name"],
                view_name=event["view_name"],
                user=event["user"],
                legacy_user_id=event["legacy_user_id"],
                session_key=event["session_key"],
                request_id=event["request_id"],
                message=str(exc) or "Eccezione non gestita",
                exception_class=exc.__class__.__name__,
                traceback_text=get_exception_traceback(exc),
                user_agent=event["user_agent"],
                remote_addr=event["remote_addr"],
                extra_json={"captured_by": "IssueCaptureMiddleware", "captured_at": timezone.now().isoformat()},
                release_version=event["release_version"],
                environment=event["environment"],
            )
        except Exception:
            logger.exception("IssueCaptureMiddleware: registrazione eccezione fallita")

    def _safe_capture_response(self, request, response, elapsed_ms: int) -> None:
        try:
            status_code = int(getattr(response, "status_code", 200) or 200)
            event = build_request_event_context(request)
            if status_code >= 500:
                open_or_update_issue_from_web_error(
                    category=Issue.Category.SYSTEM,
                    severity=Issue.Severity.HIGH,
                    source=Issue.Source.WEB,
                    status_code=status_code,
                    method=event["method"],
                    current_url=event["current_url"],
                    route_name=event["route_name"],
                    module_name=event["module_name"],
                    view_name=event["view_name"],
                    user=event["user"],
                    legacy_user_id=event["legacy_user_id"],
                    session_key=event["session_key"],
                    request_id=event["request_id"],
                    message=f"Risposta HTTP {status_code} restituita senza eccezione propagata.",
                    exception_class="HTTP500Response",
                    traceback_text="",
                    user_agent=event["user_agent"],
                    remote_addr=event["remote_addr"],
                    extra_json={"captured_by": "IssueCaptureMiddleware"},
                    release_version=event["release_version"],
                    environment=event["environment"],
                )
            elif status_code == 403 and self.capture_403 and event["user"] is not None:
                open_or_update_issue_from_web_error(
                    category=Issue.Category.ACL,
                    severity=Issue.Severity.MEDIUM,
                    source=Issue.Source.WEB,
                    status_code=status_code,
                    method=event["method"],
                    current_url=event["current_url"],
                    route_name=event["route_name"],
                    module_name=event["module_name"],
                    view_name=event["view_name"],
                    user=event["user"],
                    legacy_user_id=event["legacy_user_id"],
                    session_key=event["session_key"],
                    request_id=event["request_id"],
                    message="Risposta 403 rilevata su route autenticata.",
                    exception_class="HTTP403Response",
                    traceback_text="",
                    user_agent=event["user_agent"],
                    remote_addr=event["remote_addr"],
                    extra_json={"captured_by": "IssueCaptureMiddleware"},
                    release_version=event["release_version"],
                    environment=event["environment"],
                )
            elif status_code == 404 and self.capture_404 and event["user"] is not None:
                open_or_update_issue_from_web_error(
                    category=Issue.Category.UI,
                    severity=Issue.Severity.LOW,
                    source=Issue.Source.WEB,
                    status_code=status_code,
                    method=event["method"],
                    current_url=event["current_url"],
                    route_name=event["route_name"],
                    module_name=event["module_name"],
                    view_name=event["view_name"],
                    user=event["user"],
                    legacy_user_id=event["legacy_user_id"],
                    session_key=event["session_key"],
                    request_id=event["request_id"],
                    message="Route interna non trovata.",
                    exception_class="HTTP404Response",
                    traceback_text="",
                    user_agent=event["user_agent"],
                    remote_addr=event["remote_addr"],
                    extra_json={"captured_by": "IssueCaptureMiddleware"},
                    release_version=event["release_version"],
                    environment=event["environment"],
                )

            if self.slow_request_threshold_ms > 0 and elapsed_ms >= self.slow_request_threshold_ms and status_code < 500:
                open_or_update_issue_from_web_error(
                    category=Issue.Category.PERFORMANCE,
                    severity=Issue.Severity.MEDIUM,
                    source=Issue.Source.WEB,
                    status_code=status_code,
                    method=event["method"],
                    current_url=event["current_url"],
                    route_name=event["route_name"],
                    module_name=event["module_name"],
                    view_name=event["view_name"],
                    user=event["user"],
                    legacy_user_id=event["legacy_user_id"],
                    session_key=event["session_key"],
                    request_id=event["request_id"],
                    message=f"Richiesta lenta: {elapsed_ms} ms.",
                    exception_class="SlowRequest",
                    traceback_text="",
                    user_agent=event["user_agent"],
                    remote_addr=event["remote_addr"],
                    extra_json={
                        "captured_by": "IssueCaptureMiddleware",
                        "elapsed_ms": elapsed_ms,
                        "threshold_ms": self.slow_request_threshold_ms,
                    },
                    release_version=event["release_version"],
                    environment=event["environment"],
                )
        except Exception:
            logger.exception("IssueCaptureMiddleware: registrazione response fallita")
