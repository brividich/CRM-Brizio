from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone
from rest_framework import routers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityAsset,
    SecurityEvidenceContainer,
    SecurityEvidenceItem,
    SecurityEventRecord,
    SecurityKpiSnapshot,
    SecurityMailboxMessage,
    SecurityReport,
    SecurityRemediationTicket,
    SecuritySource,
    SecuritySourceFile,
    SourceType,
    SecurityVulnerabilityFinding,
    Severity,
)
from .serializers import (
    BackupJobRecordSerializer,
    IngestMailboxMessageSerializer,
    IngestSourceFileSerializer,
    SecurityAlertSerializer,
    SecurityAssetSerializer,
    SecurityEventRecordSerializer,
    SecurityEvidenceContainerSerializer,
    SecurityKpiSnapshotSerializer,
    SecurityReportSerializer,
    SecuritySourceSerializer,
    SecurityVulnerabilityFindingSerializer,
)
from .services.ingestion import ingest_mailbox_message, ingest_source_file
from .services.kpi_service import build_daily_kpi_snapshots
from .services.parser_engine import run_pending_parsers
from .services.rule_engine import evaluate_security_rules
from .permissions import CanManageSecurityCenter, CanViewSecurityCenter
from .services.addon_registry import ACTIVE_ALERT_STATUSES, ACTIVE_TICKET_STATUSES, get_addon_detail, get_addon_registry
from .services.security_inbox_pipeline import process_mailbox_message, process_source_file, summarize_pipeline_result


class RetryConflict(Exception):
    pass


class SecurityHealthApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response({"status": "ok"})


class SecuritySessionApiView(APIView):
    def get(self, request):
        return Response({
            "authenticated": request.user.is_authenticated,
            "username": request.user.username if request.user.is_authenticated else None,
            "can_view_security": request.user.has_perm("security.can_view_security_center") if request.user.is_authenticated else False,
        })


class SecurityAddonsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response({"addons": get_addon_registry()})


class SecurityAddonDetailApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request, code):
        addon = get_addon_detail(code)
        if addon is None:
            raise NotFound("Unknown addon.")
        return Response(addon)


class DashboardSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response(
            {
                "generated_at": _iso(timezone.now()),
                "open_alerts_count": SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
                "critical_alerts_count": SecurityAlert.objects.filter(
                    status__in=ACTIVE_ALERT_STATUSES,
                    severity=Severity.CRITICAL,
                ).count(),
                "open_tickets_count": SecurityRemediationTicket.objects.filter(status__in=ACTIVE_TICKET_STATUSES).count(),
                "evidence_containers_count": SecurityEvidenceContainer.objects.count(),
                "recent_alerts": _recent_alerts(limit=5),
                "recent_tickets": _recent_tickets(limit=5),
                "kpi_summary": _kpi_summary_payload(),
                "ingestion_status": _ingestion_status_payload(),
            }
        )


class RecentAlertsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        limit = _bounded_limit(request.query_params.get("limit"), default=20, maximum=100)
        return Response(
            {
                "generated_at": _iso(timezone.now()),
                "alerts": _recent_alerts(limit=limit),
            }
        )


class KpiSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response(_kpi_summary_payload())


class AddonsSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        return Response(
            {
                "generated_at": _iso(timezone.now()),
                "modules": [_addon_summary_dto(addon) for addon in get_addon_registry()],
            }
        )


class InboxRecentApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        limit = _bounded_limit(request.query_params.get("limit"), default=10, maximum=50)
        reports = list(
            SecurityReport.objects.select_related("source", "mailbox_message", "source_file")
            .prefetch_related("metrics")
            .annotate(
                metrics_count=Count("metrics", distinct=True),
                events_count=Count("events", distinct=True),
                alerts_count=Count("events__alerts", distinct=True),
                evidence_count=Count("events__alerts__evidence_containers", distinct=True),
                tickets_count=Count("events__alerts__tickets", distinct=True),
            )
            .order_by("-created_at")[:limit]
        )
        report_ids = [report.id for report in reports]
        event_summary_by_report = _event_summary_by_report(report_ids)
        alert_summary_by_report = _alert_summary_by_report(report_ids)

        mailbox_messages = list(SecurityMailboxMessage.objects.select_related("source").order_by("-received_at")[:limit])
        source_files = list(SecuritySourceFile.objects.select_related("source").order_by("-uploaded_at")[:limit])
        linked_reports_by_message = _linked_report_summary("mailbox_message_id", [message.id for message in mailbox_messages])
        linked_reports_by_file = _linked_report_summary("source_file_id", [source_file.id for source_file in source_files])

        return Response(
            {
                "generated_at": _iso(timezone.now()),
                "recent_reports": [
                    _report_recent_dto(report, event_summary_by_report, alert_summary_by_report)
                    for report in reports
                ],
                "recent_mailbox_messages": [
                    _mailbox_message_recent_dto(message, linked_reports_by_message)
                    for message in mailbox_messages
                ],
                "recent_source_files": [
                    _source_file_recent_dto(source_file, linked_reports_by_file)
                    for source_file in source_files
                ],
                "latest_pipeline_status": _ingestion_status_payload(),
            }
        )


class InboxItemRetryApiView(APIView):
    permission_classes = [CanManageSecurityCenter]

    def post(self, request, item_kind, pk):
        try:
            item, normalized_kind, source_report = _retry_target(item_kind, pk)
        except SecurityReport.DoesNotExist:
            return Response({"error": "report not found"}, status=status.HTTP_404_NOT_FOUND)
        except SecurityMailboxMessage.DoesNotExist:
            return Response({"error": "mailbox item not found"}, status=status.HTTP_404_NOT_FOUND)
        except SecuritySourceFile.DoesNotExist:
            return Response({"error": "file item not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            return Response(_retry_item(item, normalized_kind, source_report, bool((request.data or {}).get("force_reprocess", False))))
        except RetryConflict as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)


class InboxBulkRetryApiView(APIView):
    permission_classes = [CanManageSecurityCenter]

    def post(self, request):
        data = request.data or {}
        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            return Response({"error": "items must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
        if len(items) > 25:
            return Response({"error": "items limit is 25"}, status=status.HTTP_400_BAD_REQUEST)

        force_reprocess = bool(data.get("force_reprocess", False))
        seen = set()
        results = []
        for item_ref in items:
            payload = _bulk_retry_item(item_ref, force_reprocess, seen)
            results.append(payload)

        return Response({"summary": _bulk_retry_summary(results), "results": results})


class SecuritySourceViewSet(viewsets.ModelViewSet):
    queryset = SecuritySource.objects.order_by("name")
    serializer_class = SecuritySourceSerializer

    @action(detail=True, methods=["post"], url_path="ingest-mailbox-message")
    def ingest_mailbox(self, request, pk=None):
        source = self.get_object()
        serializer = IngestMailboxMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = ingest_mailbox_message(source=source, **serializer.validated_data)
        return Response({"id": message.id, "parse_status": message.parse_status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="ingest-source-file")
    def ingest_file(self, request, pk=None):
        source = self.get_object()
        serializer = IngestSourceFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_obj = ingest_source_file(
            source=source,
            original_name=serializer.validated_data["original_name"],
            content=serializer.validated_data["content"],
            file_type=serializer.validated_data.get("file_type", SourceType.CSV),
        )
        return Response({"id": file_obj.id, "parse_status": file_obj.parse_status}, status=status.HTTP_201_CREATED)


class SecurityReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityReport.objects.order_by("-created_at")
    serializer_class = SecurityReportSerializer


class SecurityEventRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityEventRecord.objects.order_by("-occurred_at")
    serializer_class = SecurityEventRecordSerializer


class SecurityAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityAlert.objects.order_by("-created_at")
    serializer_class = SecurityAlertSerializer


class SecurityEvidenceContainerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityEvidenceContainer.objects.order_by("-created_at")
    serializer_class = SecurityEvidenceContainerSerializer


class SecurityAssetViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityAsset.objects.order_by("hostname")
    serializer_class = SecurityAssetSerializer


class SecurityVulnerabilityFindingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityVulnerabilityFinding.objects.order_by("-last_seen_at")
    serializer_class = SecurityVulnerabilityFindingSerializer


class BackupJobRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BackupJobRecord.objects.order_by("-created_at")
    serializer_class = BackupJobRecordSerializer


class SecurityKpiSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityKpiSnapshot.objects.order_by("-snapshot_date")
    serializer_class = SecurityKpiSnapshotSerializer


class SecurityPipelineViewSet(viewsets.ViewSet):
    @action(detail=False, methods=["post"], url_path="run-parsers")
    def run_parsers(self, request):
        return Response({"parsed_items": run_pending_parsers()})

    @action(detail=False, methods=["post"], url_path="evaluate-rules")
    def evaluate_rules(self, request):
        return Response({"evaluated_events": evaluate_security_rules()})

    @action(detail=False, methods=["post"], url_path="build-kpis")
    def build_kpis(self, request):
        return Response({"snapshots": build_daily_kpi_snapshots()})


router = routers.DefaultRouter()
router.register("sources", SecuritySourceViewSet)
router.register("reports", SecurityReportViewSet)
router.register("events", SecurityEventRecordViewSet)
router.register("alerts", SecurityAlertViewSet)
router.register("evidence", SecurityEvidenceContainerViewSet)
router.register("assets", SecurityAssetViewSet)
router.register("vulnerabilities", SecurityVulnerabilityFindingViewSet)
router.register("backup-jobs", BackupJobRecordViewSet)
router.register("kpis", SecurityKpiSnapshotViewSet)
router.register("pipeline", SecurityPipelineViewSet, basename="pipeline")


def _recent_alerts(limit):
    alerts = SecurityAlert.objects.select_related("source").order_by("-updated_at", "-created_at")[:limit]
    return [
        {
            "id": alert.id,
            "title": alert.title,
            "severity": alert.severity,
            "status": alert.status,
            "source_name": alert.source.name,
            "source": alert.source.name,
            "created_at": _iso(alert.created_at),
            "updated_at": _iso(alert.updated_at),
            "detail_url": reverse("security:alert_detail", kwargs={"pk": alert.pk}),
        }
        for alert in alerts
    ]


def _recent_tickets(limit):
    tickets = SecurityRemediationTicket.objects.select_related("source", "alert").order_by("-updated_at", "-created_at")[:limit]
    return [
        {
            "id": ticket.id,
            "title": ticket.title,
            "severity": ticket.severity,
            "status": ticket.status,
            "source_name": ticket.source.name,
            "source": ticket.source.name,
            "created_at": _iso(ticket.created_at),
            "updated_at": _iso(ticket.updated_at),
            "detail_url": reverse("security:tickets_list"),
        }
        for ticket in tickets
    ]


def _report_recent_dto(report, event_summary_by_report, alert_summary_by_report):
    payload = report.parsed_payload or {}
    parse_warnings = payload.get("parse_warnings") or []
    if not isinstance(parse_warnings, list):
        parse_warnings = []
    return {
        "id": report.id,
        "title": report.title,
        "source_name": report.source.name,
        "source_type": report.source.source_type,
        "vendor": report.source.vendor,
        "report_type": report.report_type,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "parser_name": report.parser_name,
        "parse_status": report.parse_status,
        "created_at": _iso(report.created_at),
        "input_kind": _report_input_kind(report),
        "metrics_count": getattr(report, "metrics_count", 0),
        "events_count": getattr(report, "events_count", 0),
        "alerts_count": getattr(report, "alerts_count", 0),
        "evidence_count": _report_evidence_count(report),
        "tickets_count": _report_ticket_count(report),
        "warnings_count": len(parse_warnings),
        "dedup_status": _report_dedup_status(report),
        "tuning_actions": _report_tuning_actions(report),
        "timeline": _report_timeline(report),
        "metric_preview": _metric_preview(report),
        "event_summary": event_summary_by_report.get(report.id, []),
        "alert_summary": alert_summary_by_report.get(report.id, []),
        "alert_preview": _alert_preview(report),
        "ticket_preview": _ticket_preview(report),
        "evidence_preview": _evidence_preview(report),
    }


def _mailbox_message_recent_dto(message, linked_reports_by_message):
    linked = linked_reports_by_message.get(message.id, _empty_linked_report_summary())
    pipeline = message.pipeline_result or {}
    return {
        "id": message.id,
        "subject": message.subject,
        "sender": message.sender,
        "source_name": message.source.name,
        "source_type": message.source.source_type,
        "parse_status": message.parse_status,
        "received_at": _iso(message.received_at),
        "parser_name": linked["parser_name"] or str(pipeline.get("parser_name") or ""),
        "linked_report_ids": linked["report_ids"],
        "reports_count": linked["reports_count"],
        "metrics_count": linked["metrics_count"] or _safe_int(pipeline.get("metrics_count") or pipeline.get("metrics_created")),
        "events_count": linked["events_count"] or _safe_int(pipeline.get("findings_count") or pipeline.get("events_created")),
        "alerts_count": linked["alerts_count"] or _safe_int(pipeline.get("alerts_count") or pipeline.get("alerts_created")),
        "evidence_count": linked["evidence_count"] or _safe_int(pipeline.get("evidence_created")),
        "tickets_count": linked["tickets_count"] or _safe_int(pipeline.get("ticket_created") or pipeline.get("tickets_changed")),
        "warnings_count": _safe_int(pipeline.get("warnings_count")),
        "errors_count": _safe_int(pipeline.get("errors_count")),
        "pipeline_status": str(pipeline.get("status") or ""),
    }


def _source_file_recent_dto(source_file, linked_reports_by_file):
    linked = linked_reports_by_file.get(source_file.id, _empty_linked_report_summary())
    return {
        "id": source_file.id,
        "original_name": source_file.original_name,
        "source_name": source_file.source.name,
        "source_type": source_file.source.source_type,
        "file_type": source_file.file_type,
        "parse_status": source_file.parse_status,
        "uploaded_at": _iso(source_file.uploaded_at),
        "parser_name": linked["parser_name"],
        "linked_report_ids": linked["report_ids"],
        "reports_count": linked["reports_count"],
        "metrics_count": linked["metrics_count"],
        "events_count": linked["events_count"],
        "alerts_count": linked["alerts_count"],
        "evidence_count": linked["evidence_count"],
        "tickets_count": linked["tickets_count"],
        "warnings_count": linked["warnings_count"],
    }


def _retry_target(item_kind, pk):
    normalized = str(item_kind or "").strip().lower().replace("_", "-")
    if normalized in {"mail", "mailbox", "mailbox-message"}:
        return SecurityMailboxMessage.objects.select_related("source").get(pk=pk), "mailbox", None
    if normalized in {"file", "source-file"}:
        return SecuritySourceFile.objects.select_related("source").get(pk=pk), "file", None
    if normalized == "report":
        report = SecurityReport.objects.select_related("mailbox_message", "source_file").get(pk=pk)
        if report.mailbox_message_id:
            return report.mailbox_message, "mailbox", report
        if report.source_file_id:
            return report.source_file, "file", report
        raise ValueError("report has no linked input to reprocess")
    raise ValueError("unsupported item kind")


def _retry_item(item, item_kind, source_report=None, force_reprocess=False, skip_conflicts=False):
    previous_status = getattr(item, "parse_status", "")
    if previous_status == ParseStatus.PARSED and not force_reprocess:
        if skip_conflicts:
            return _retry_skipped_payload(item, item_kind, previous_status, "Input gia processato.")
        raise RetryConflict("item already processed; force_reprocess required")

    if previous_status in (ParseStatus.PARSED, ParseStatus.SKIPPED):
        item.parse_status = ParseStatus.PENDING
        item.save(update_fields=["parse_status"])

    if item_kind == "mailbox":
        result = process_mailbox_message(item, dry_run=False)
    else:
        result = process_source_file(item, dry_run=False)

    item.refresh_from_db()
    summary = summarize_pipeline_result(result)
    return _retry_result_payload(item, item_kind, previous_status, summary, result, source_report)


def _bulk_retry_item(item_ref, force_reprocess, seen):
    try:
        item_kind = str(item_ref.get("kind") or item_ref.get("item_kind") or "").strip()
        pk = int(item_ref.get("id"))
        item, normalized_kind, source_report = _retry_target(item_kind, pk)
    except (AttributeError, TypeError, ValueError) as exc:
        return _bulk_retry_error_payload(item_ref, str(exc) or "invalid item")
    except SecurityReport.DoesNotExist:
        return _bulk_retry_error_payload(item_ref, "report not found")
    except SecurityMailboxMessage.DoesNotExist:
        return _bulk_retry_error_payload(item_ref, "mailbox item not found")
    except SecuritySourceFile.DoesNotExist:
        return _bulk_retry_error_payload(item_ref, "file item not found")

    key = (normalized_kind, item.id)
    if key in seen:
        return _retry_skipped_payload(item, normalized_kind, getattr(item, "parse_status", ""), "Input duplicato nella richiesta.")
    seen.add(key)
    return _retry_item(item, normalized_kind, source_report, force_reprocess=force_reprocess, skip_conflicts=True)


def _bulk_retry_error_payload(item_ref, message):
    safe_ref = item_ref if isinstance(item_ref, dict) else {}
    return {
        "item_kind": str(safe_ref.get("kind") or ""),
        "id": _safe_int(safe_ref.get("id")),
        "source_report_id": None,
        "previous_status": "",
        "parse_status": "",
        "status": "error",
        "processed": False,
        "parser_detected": False,
        "parser_name": "",
        "reports_parsed": 0,
        "metrics_count": 0,
        "events_count": 0,
        "alerts_count": 0,
        "evidence_count": 0,
        "tickets_count": 0,
        "warnings_count": 0,
        "errors_count": 1,
        "message": message,
    }


def _retry_skipped_payload(item, item_kind, previous_status, message):
    return {
        "item_kind": item_kind,
        "id": item.id,
        "source_report_id": None,
        "previous_status": previous_status,
        "parse_status": getattr(item, "parse_status", ""),
        "status": "skipped",
        "processed": False,
        "parser_detected": False,
        "parser_name": "",
        "reports_parsed": 0,
        "metrics_count": 0,
        "events_count": 0,
        "alerts_count": 0,
        "evidence_count": 0,
        "tickets_count": 0,
        "warnings_count": 0,
        "errors_count": 0,
        "message": message,
    }


def _bulk_retry_summary(results):
    return {
        "total": len(results),
        "processed": sum(1 for item in results if item.get("processed")),
        "success": sum(1 for item in results if item.get("status") == "success"),
        "skipped": sum(1 for item in results if item.get("status") == "skipped"),
        "failed": sum(1 for item in results if item.get("status") == "error" or _safe_int(item.get("errors_count")) > 0),
        "reports_parsed": sum(_safe_int(item.get("reports_parsed")) for item in results),
        "events": sum(_safe_int(item.get("events_count")) for item in results),
        "alerts": sum(_safe_int(item.get("alerts_count")) for item in results),
    }


def _retry_result_payload(item, item_kind, previous_status, summary, result, source_report=None):
    return {
        "item_kind": item_kind,
        "id": item.id,
        "source_report_id": source_report.id if source_report else None,
        "previous_status": previous_status,
        "parse_status": item.parse_status,
        "status": summary.get("status", "unknown"),
        "processed": bool(result.get("processed", True)),
        "parser_detected": bool(summary.get("parser_detected")),
        "parser_name": summary.get("parser_name", ""),
        "reports_parsed": _safe_int(result.get("reports_parsed")),
        "metrics_count": _safe_int(summary.get("metrics_count")),
        "events_count": _safe_int(summary.get("findings_count")),
        "alerts_count": _safe_int(summary.get("alerts_count")),
        "evidence_count": _safe_int(summary.get("evidence_created")),
        "tickets_count": _safe_int(summary.get("ticket_created")),
        "warnings_count": _safe_int(summary.get("warnings_count")),
        "errors_count": _safe_int(summary.get("errors_count")),
        "message": _retry_result_message(summary.get("status", "unknown"), item.parse_status),
    }


def _retry_result_message(result_status, parse_status):
    if result_status == "success" and parse_status == ParseStatus.PARSED:
        return "Processamento completato."
    if result_status == "skipped":
        return "Nessun parser compatibile trovato."
    if result_status == "already_processed":
        return "Input gia processato."
    if result_status in {"error", "failed"} or parse_status == ParseStatus.FAILED:
        return "Processamento completato con errori."
    return "Processamento aggiornato."


def _metric_preview(report):
    metrics = sorted(report.metrics.all(), key=lambda metric: metric.name)[:5]
    return [
        {
            "name": metric.name,
            "value": metric.value,
            "unit": metric.unit,
        }
        for metric in metrics
    ]


def _alert_preview(report):
    alerts = (
        SecurityAlert.objects.filter(event__report=report)
        .select_related("source")
        .order_by("-updated_at", "-created_at")[:5]
    )
    return [
        {
            "id": alert.id,
            "title": alert.title,
            "severity": alert.severity,
            "status": alert.status,
            "source_name": alert.source.name,
            "created_at": _iso(alert.created_at),
            "updated_at": _iso(alert.updated_at),
            "detail_url": reverse("security:alert_detail", kwargs={"pk": alert.pk}),
        }
        for alert in alerts
    ]


def _ticket_preview(report):
    tickets = (
        SecurityRemediationTicket.objects.filter(
            Q(alert__event__report=report) | Q(linked_alerts__event__report=report)
        )
        .select_related("source", "alert")
        .distinct()
        .order_by("-updated_at", "-created_at")[:5]
    )
    return [
        {
            "id": ticket.id,
            "title": ticket.title,
            "severity": ticket.severity,
            "status": ticket.status,
            "source_name": ticket.source.name,
            "occurrence_count": ticket.occurrence_count,
            "updated_at": _iso(ticket.updated_at),
            "detail_url": reverse("security:tickets_list"),
        }
        for ticket in tickets
    ]


def _evidence_preview(report):
    containers = (
        SecurityEvidenceContainer.objects.filter(
            Q(alert__event__report=report) | Q(items__report=report)
        )
        .select_related("source", "alert")
        .annotate(items_count=Count("items", distinct=True))
        .distinct()
        .order_by("-created_at")[:5]
    )
    return [
        {
            "id": str(container.id),
            "title": container.title,
            "status": container.status,
            "source_name": container.source.name,
            "items_count": getattr(container, "items_count", 0),
            "created_at": _iso(container.created_at),
        }
        for container in containers
    ]


def _report_evidence_count(report):
    direct_count = getattr(report, "evidence_count", None)
    if direct_count is not None:
        indirect_count = SecurityEvidenceItem.objects.filter(report=report).values("container_id").distinct().count()
        return max(int(direct_count or 0), indirect_count)
    return SecurityEvidenceContainer.objects.filter(alert__event__report=report).distinct().count()


def _report_ticket_count(report):
    annotated_count = getattr(report, "tickets_count", None)
    if annotated_count is not None:
        return int(annotated_count or 0)
    return SecurityRemediationTicket.objects.filter(alert__event__report=report).distinct().count()


def _report_dedup_status(report):
    payload = report.parsed_payload or {}
    has_dedup_key = bool(payload.get("dedup_key"))
    linked_input_id = report.mailbox_message_id or report.source_file_id
    if has_dedup_key:
        duplicate_count = SecurityReport.objects.filter(
            source=report.source,
            parsed_payload__dedup_key=payload.get("dedup_key"),
        ).exclude(pk=report.pk).count()
        return {
            "state": "tracked",
            "label": "Deduplica attiva",
            "detail": "Reimport riconoscibile dal parser" if duplicate_count == 0 else "Sono presenti report con la stessa chiave",
            "duplicates": duplicate_count,
            "input_linked": bool(linked_input_id),
        }
    return {
        "state": "missing",
        "label": "Deduplica da verificare",
        "detail": "Il parser non ha esposto una chiave deduplicabile",
        "duplicates": 0,
        "input_linked": bool(linked_input_id),
    }


def _report_tuning_actions(report):
    return [
        {
            "kind": "parser",
            "label": "Tuning parser",
            "target": "/configuration?tab=test",
            "detail": report.parser_name,
        },
        {
            "kind": "source",
            "label": "Tuning sorgente",
            "target": "/configuration",
            "detail": report.source.name,
        },
        {
            "kind": "rules",
            "label": "Tuning regole",
            "target": "/configuration?tab=rules",
            "detail": report.report_type,
        },
    ]


def _report_timeline(report):
    timeline = [
        {
            "kind": "input",
            "label": "Input acquisito",
            "status": "done",
            "at": _iso(_report_received_at(report) or report.created_at),
            "detail": _report_input_label(report),
            "count": 1,
        },
        {
            "kind": "parser",
            "label": "Parser eseguito",
            "status": "done" if report.parse_status == ParseStatus.PARSED else "attention",
            "at": _iso(report.created_at),
            "detail": report.parser_name,
            "count": 1,
        },
    ]
    metrics_count = getattr(report, "metrics_count", report.metrics.count())
    events_count = getattr(report, "events_count", report.events.count())
    alerts_count = getattr(report, "alerts_count", SecurityAlert.objects.filter(event__report=report).distinct().count())
    evidence_count = _report_evidence_count(report)
    tickets_count = _report_ticket_count(report)
    warnings_count = len((report.parsed_payload or {}).get("parse_warnings") or [])

    if metrics_count:
        timeline.append({"kind": "metrics", "label": "Metriche estratte", "status": "done", "at": _iso(report.created_at), "detail": "KPI disponibili", "count": metrics_count})
    if events_count:
        timeline.append({"kind": "events", "label": "Eventi normalizzati", "status": "done", "at": _iso(report.created_at), "detail": "Record strutturati", "count": events_count})
    if alerts_count:
        timeline.append({"kind": "alerts", "label": "Alert generati", "status": "attention", "at": _iso(report.created_at), "detail": "Richiede triage", "count": alerts_count})
    if evidence_count:
        timeline.append({"kind": "evidence", "label": "Evidenze archiviate", "status": "done", "at": _iso(report.created_at), "detail": "Evidence Container", "count": evidence_count})
    if tickets_count:
        timeline.append({"kind": "tickets", "label": "Caso/ticket collegato", "status": "attention", "at": _iso(report.created_at), "detail": "Remediation workflow", "count": tickets_count})
    if warnings_count:
        timeline.append({"kind": "warnings", "label": "Avvisi parser", "status": "attention", "at": _iso(report.created_at), "detail": "Controllare configurazione o layout sorgente", "count": warnings_count})
    return timeline


def _report_received_at(report):
    if report.mailbox_message_id:
        return report.mailbox_message.received_at
    if report.source_file_id:
        return report.source_file.uploaded_at
    return None


def _report_input_label(report):
    if report.mailbox_message_id:
        return "Mailbox"
    if report.source_file_id:
        return "File upload"
    return "Manuale"


def _event_summary_by_report(report_ids):
    summaries = defaultdict(list)
    if not report_ids:
        return summaries
    rows = (
        SecurityEventRecord.objects.filter(report_id__in=report_ids)
        .values("report_id", "event_type", "severity")
        .annotate(total=Count("id"))
        .order_by("report_id", "event_type", "severity")
    )
    for row in rows:
        summaries[row["report_id"]].append(
            {
                "event_type": row["event_type"],
                "severity": row["severity"],
                "total": row["total"],
            }
        )
    return summaries


def _alert_summary_by_report(report_ids):
    summaries = defaultdict(list)
    if not report_ids:
        return summaries
    rows = (
        SecurityAlert.objects.filter(event__report_id__in=report_ids)
        .values("event__report_id", "status", "severity")
        .annotate(total=Count("id"))
        .order_by("event__report_id", "status", "severity")
    )
    for row in rows:
        summaries[row["event__report_id"]].append(
            {
                "status": row["status"],
                "severity": row["severity"],
                "total": row["total"],
            }
        )
    return summaries


def _linked_report_summary(link_field, object_ids):
    summaries = {}
    if not object_ids:
        return summaries

    report_rows = (
        SecurityReport.objects.filter(**{f"{link_field}__in": object_ids})
        .annotate(
            metrics_count=Count("metrics", distinct=True),
            events_count=Count("events", distinct=True),
            alerts_count=Count("events__alerts", distinct=True),
            evidence_count=Count("events__alerts__evidence_containers", distinct=True),
            tickets_count=Count("events__alerts__tickets", distinct=True),
        )
        .values(
            link_field,
            "id",
            "parser_name",
            "parsed_payload",
            "metrics_count",
            "events_count",
            "alerts_count",
            "evidence_count",
            "tickets_count",
        )
        .order_by(link_field, "-created_at")
    )
    for row in report_rows:
        summary = summaries.setdefault(row[link_field], _empty_linked_report_summary())
        summary["report_ids"].append(row["id"])
        summary["reports_count"] += 1
        summary["metrics_count"] += row["metrics_count"]
        summary["events_count"] += row["events_count"]
        summary["alerts_count"] += row["alerts_count"]
        summary["evidence_count"] += row["evidence_count"]
        summary["tickets_count"] += row["tickets_count"]
        summary["parser_name"] = summary["parser_name"] or row["parser_name"]
        parse_warnings = (row["parsed_payload"] or {}).get("parse_warnings") or []
        if isinstance(parse_warnings, list):
            summary["warnings_count"] += len(parse_warnings)
    return summaries


def _empty_linked_report_summary():
    return {
        "report_ids": [],
        "reports_count": 0,
        "metrics_count": 0,
        "events_count": 0,
        "alerts_count": 0,
        "evidence_count": 0,
        "tickets_count": 0,
        "warnings_count": 0,
        "parser_name": "",
    }


def _report_input_kind(report):
    if report.mailbox_message_id:
        return "mailbox"
    if report.source_file_id:
        return "file"
    return "manual"


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _kpi_summary_payload():
    latest_date = SecurityKpiSnapshot.objects.order_by("-snapshot_date").values_list("snapshot_date", flat=True).first()
    if not latest_date:
        return {
            "generated_at": _iso(timezone.now()),
            "counters": {},
            "trends": [],
            "period_label": "",
            "empty_state": True,
        }

    snapshots = SecurityKpiSnapshot.objects.filter(snapshot_date=latest_date).order_by("name")
    counters = {}
    for snapshot in snapshots:
        counters[snapshot.name] = counters.get(snapshot.name, 0) + snapshot.value

    trend_rows = (
        SecurityKpiSnapshot.objects.filter(snapshot_date__gte=latest_date - timezone.timedelta(days=6))
        .values("snapshot_date")
        .annotate(total=Sum("value"))
        .order_by("snapshot_date")
    )
    trends = [{"date": row["snapshot_date"].isoformat(), "total": row["total"] or 0} for row in trend_rows]
    return {
        "generated_at": _iso(timezone.now()),
        "counters": counters,
        "trends": trends,
        "period_label": latest_date.isoformat(),
        "empty_state": False,
    }


def _ingestion_status_payload():
    return {
        "reports_total": SecurityReport.objects.count(),
        "events_total": SecurityEventRecord.objects.count(),
        "mailbox_messages": {
            "pending": SecurityMailboxMessage.objects.filter(parse_status=ParseStatus.PENDING).count(),
            "parsed": SecurityMailboxMessage.objects.filter(parse_status=ParseStatus.PARSED).count(),
            "failed": SecurityMailboxMessage.objects.filter(parse_status=ParseStatus.FAILED).count(),
        },
        "source_files": {
            "pending": SecuritySourceFile.objects.filter(parse_status=ParseStatus.PENDING).count(),
            "parsed": SecuritySourceFile.objects.filter(parse_status=ParseStatus.PARSED).count(),
            "failed": SecuritySourceFile.objects.filter(parse_status=ParseStatus.FAILED).count(),
        },
    }


def _addon_summary_dto(addon):
    return {
        "code": addon["code"],
        "name": addon["name"],
        "status": addon["status"],
        "enabled": addon.get("enabled_source_count", 0) > 0 or addon.get("enabled_parser_count", 0) > 0,
        "configured": addon.get("total_source_count", 0) > 0 or addon.get("total_parser_count", 0) > 0,
        "parser_count": addon.get("total_parser_count", 0),
        "source_count": addon.get("total_source_count", 0),
        "alert_rule_count": addon.get("total_rule_count", 0),
        "warning_count": addon.get("warning_count", 0),
        "detail_url": addon.get("links", {}).get("detail") or reverse("security:admin_addon_detail", kwargs={"code": addon["code"]}),
    }


def _bounded_limit(value, default, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))


def _iso(value):
    return value.isoformat() if value else None
