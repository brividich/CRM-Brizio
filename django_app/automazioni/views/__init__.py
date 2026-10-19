"""Viste del modulo Automazioni, spezzate per pilastro (18/10/2026).

Lega qui solo le view di ``urls.py`` e il blocco import storico, così
``from automazioni.views import X`` e ``views.X`` in ``urls.py`` restano invariati.
Tutto il resto non viene copiato ma letto dai sottomoduli via ``__getattr__`` (vedi in fondo);
per i test ``mock.patch`` va su ``automazioni.views._helpers.X`` per le funzioni condivise
e su ``automazioni.views.<pilastro>.X`` per le altre.
"""
# ruff: noqa: F401, E402
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.db import connection, transaction
from django.db.utils import OperationalError as DjangoOperationalError, ProgrammingError as DjangoProgrammingError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action
from core.public_headers import risposta_pubblica, risposta_pubblica_con_form
from monitoring.models import AutomationJob, AutomationExecution
from monitoring.services import detect_missed_jobs, detect_stuck_jobs

from ..forms import (
    ApprovalEmailTemplateForm,
    AutomationDeliveryEndpointForm,
    AutomationActionFormSet,
    AutomationConditionFormSet,
    AutomationPackageDryRunForm,
    AutomationPackageUploadForm,
    AutomationRuleForm,
    AutomationRuleTestForm,
    PowerAutomateFlowUploadForm,
    TeamsWebhookPresetForm,
    _safe_json_array_length,
)
from ..models import (
    ApprovalEmailTemplate,
    ApprovalEmailTemplateDeliveryMode,
    APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE,
    AutomationAction,
    AutomationActionLog,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    AutomationDeliveryEndpoint,
    AutomationDeliveryEndpointType,
    AutomationTableConfig,
    TeamsWebhookPreset,
    list_teams_flow_endpoints,
    list_approval_email_templates,
)
from ..approval_mailbox_runtime import (
    get_approval_graph_form_defaults,
    get_approval_graph_status,
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    get_approval_mailbox_backend,
    get_default_approval_mailbox_details,
    run_approval_poll_now,
    run_approval_imap_poll_now,
    save_approval_graph_settings,
    save_approval_imap_settings,
    MAILBOX_BACKEND_GRAPH,
    MAILBOX_BACKEND_IMAP,
)
from ..services import (
    count_queue_by_status,
    discover_module_tables,
    get_action_table_whitelist,
    get_queue_event_detail,
    list_queue_events,
    process_approval_decision,
    delete_queue_event,
    process_single_queue_event_by_id,
    reset_queue_event_to_pending,
    run_rule,
    stop_queue_event,
)
from ..package_importer import (
    PackageImportError,
    analyze_package_dict,
    analyze_package_bytes,
    build_example_payload,
    build_example_payload_json,
    create_rule_draft_from_analysis,
    import_analyzed_package,
    list_recent_source_records,
    load_source_record_payload,
    run_package_dry_run,
)
from ..power_automate_bridge import (
    analyze_power_automate_flow_upload,
    apply_power_automate_recommended_remediation,
)
from ..source_registry import (
    AUTOMAZIONI_ACL_ACTIONS,
    AUTOMAZIONI_MODULE_CODE,
    build_placeholder_examples,
    get_action_mapping_fields,
    get_condition_fields,
    get_registered_sources,
    get_source_definition,
    get_source_fields,
    get_template_fields,
    get_trigger_fields,
)


import logging as _logging


from .approvazioni import (
    approval_decision_page,
    approval_link_page,
    approval_mailbox_log_page,
    approval_proxy_approve,
    approval_proxy_reject,
    approval_status_page,
    approval_template_clone_page,
    approval_template_create_page,
    approval_template_delete_page,
    approval_template_edit_page,
    approval_template_preview_page,
    approval_templates_list_page,
    teams_flow_endpoint_create,
    teams_flow_endpoint_delete,
    teams_flow_endpoint_edit,
    teams_preset_create,
    teams_preset_delete,
    teams_preset_edit,
    teams_presets_page,
)
from .coda import (
    pianificati_action,
    pianificati_mail_config_page,
    pianificati_mail_config_save,
    pianificati_mail_test,
    pianificati_page,
    queue_delete_view,
    queue_detail_page,
    queue_list_page,
    queue_reset_view,
    queue_retry_view,
    queue_stop_view,
    run_log_detail_page,
    run_log_list_page,
)
from .configurazione import (
    event_notifications_page,
    settings_page,
)
from .regole import (
    api_recent_records,
    api_record_payload,
    api_source_field_values,
    api_table_config_delete,
    api_table_config_list,
    api_table_config_save,
    api_test_rule_ajax,
    contenuti_page,
    rule_action_reorder_view,
    rule_condition_reorder_view,
    rule_create_page,
    rule_delete_view,
    rule_designer_create_page,
    rule_designer_page,
    rule_detail_page,
    rule_edit_page,
    rule_list_page,
    rule_package_import_page,
    rule_package_import_result_page,
    rule_power_automate_convert_page,
    rule_power_automate_package_download,
    rule_test_page,
    rule_toggle_view,
    sorgenti_page,
    trigger_generator_page,
)

from . import _helpers, approvazioni, coda, configurazione, regole  # noqa: E402

_PILASTRI = (_helpers, approvazioni, coda, configurazione, regole)


def __getattr__(name):
    """Tutto ciò che non è una view di ``urls.py`` si legge dal sottomodulo al momento
    dell'accesso, non viene copiato qui: un ``mock.patch`` sul sottomodulo vale per tutti
    i chiamanti, come quando c'era un solo ``views.py``.
    """
    for mod in _PILASTRI:
        try:
            return getattr(mod, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
