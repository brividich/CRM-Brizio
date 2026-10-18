"""Viste del Pannello di amministrazione, spezzate per pilastro (18/10/2026).

Lega qui solo le view di ``urls.py`` e il blocco import storico, così
``from admin_portale.views import X`` e ``views.X`` in ``urls.py`` restano invariati.
Tutto il resto non viene copiato ma letto dai sottomoduli via ``__getattr__`` (vedi in fondo);
per i test ``mock.patch`` va su ``admin_portale.views._helpers.X`` per le funzioni condivise
e su ``admin_portale.views.<pilastro>.X`` per le altre.
"""
# ruff: noqa: F401, E402
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlencode

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.validators import validate_email
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import URLPattern, URLResolver, Resolver404, get_resolver, resolve, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer
from werkzeug.security import generate_password_hash

from config.env_config import load_env_file_values, primary_runtime_env_path, update_env_file_values
from automazioni.approval_mailbox_runtime import (
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    run_approval_imap_poll_now,
    save_approval_imap_settings,
)
from ai_assistant.models import AiChatFeedback, AiKnowledgeEntry, AiToolPrivacyReview
from ai_assistant.services import clear_knowledge_cache
from ai_assistant.tools import build_runtime_context, get_runtime_tool_catalog
from core.acl import diagnose_permesso_for_context
from core.acl_v2 import (
    diagnose_acl_access,
    normalize_binding_path_pattern,
    normalize_permission_code,
    resolve_canonical_target,
    validate_permission_code,
)
from core.audit import log_action
from core.exporting import export_rows_response
from core.caporeparto_utils import (
    format_caporeparto_label,
    normalize_caporeparto_option,
)
from core.impersonation import start_impersonation
from core.ldap_conn import build_ldap_server, ldap_receive_timeout
from core.legacy_anagrafica import ensure_anagrafica_schema, sync_anagrafica_from_legacy_user
from core.legacy_cache import (
    bump_legacy_cache_version,
    get_cached_pulsanti_catalog,
    normalize_legacy_path,
)
from core.legacy_models import AnagraficaDipendente, Permesso, Pulsante, Ruolo, UtenteLegacy
from core.navigation_registry import (
    bump_navigation_registry_version,
    export_navigation_state,
    publish_navigation_snapshot,
    resolve_navigation_item_permission_code,
    restore_navigation_snapshot,
)
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.branding import get_portal_branding
from core.acl_capability import STALE_MISSING_ROUTE, STALE_SHADOWED, capability_index
from core.permission_categories import (
    category_for,
    category_order,
    display_module,
    module_label,
    readable_label,
)
from core.permission_taxonomy import (
    ACCESS_LEVELS,
    AREA_ORDER,
    CAPABILITY_IGNOTO,
    NATURE_ORDER,
    area_for_module,
    area_label,
    capability_for_code,
    capability_label,
    nature_for_code,
    nature_label,
)
from core.pdf import (
    PDF_TEMPLATE_DEFAULTS,
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
    section_heading,
)
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    ChecklistRisposta,
    ChecklistVoce,
    EmployeeBoardConfig,
    GroupPermissionGrant,
    LegacyRedirect,
    LoginBanner,
    NavigationItem,
    NavigationRoleAccess,
    NavigationSnapshot,
    Notifica,
    OptioneConfig,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    SiteConfig,
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserUiPreference,
    UserModuleVisibility,
    UserPermissionGrant,
    UserPermissionOverride,
)

from ..decorators import legacy_admin_required
from ..forms import BulkRoleForm, PulsanteForm, UtenteCreateForm, UtenteUpdateForm
from ..security import sensitive_admin_operation_required
from core import naming



logger = logging.getLogger(__name__)

from ._helpers import (
    index,
    pulsanti,
)
from .accessi import (
    accessi_dashboard,
    accessi_preset,
    accessi_semplice,
    accessi_unificati,
    acl_diagnostica,
    api_acl_v2_role_module_set,
    api_acl_v2_user_grant_toggle,
    api_acl_v2_user_module_set,
    api_permessi_modulo_set,
    api_ruolo_create,
    api_wizard_permessi_ruolo,
    gestione_accessi,
    mappa_permessi_navigazione,
    matrice_permessi,
    permessi,
    ruoli_list,
    ruolo_delete,
    ruolo_update,
    wizard_ruolo,
)
from .branding import (
    api_branding_favicon_remove,
    api_branding_favicon_upload,
    api_login_banner_create,
    api_login_banner_delete,
    api_login_banner_toggle,
    api_login_config_save,
    api_login_landing_remove,
    api_login_landing_upload,
    api_login_logo_remove,
    api_login_logo_upload,
    api_pdf_template_config_save,
    branding_config,
    login_config,
    pdf_template_config,
    pdf_template_preview,
)
from .configurazione import (
    admin_health_check,
    ai_feedback_approva,
    ai_feedback_scarta,
    ai_knowledge,
    ai_settings,
    api_anagrafica_voce_create,
    api_anagrafica_voce_delete,
    api_anagrafica_voce_toggle,
    api_anagrafica_voce_update,
    api_checklist_esegui,
    api_checklist_voce_create,
    api_checklist_voce_delete,
    api_checklist_voce_toggle,
    api_checklist_voce_update,
    api_opzione_create,
    api_opzione_delete,
    api_opzione_toggle,
    api_opzione_update,
    api_twofa_policy_save,
    api_twofa_user_email_set,
    api_twofa_user_method_set,
    api_twofa_user_reset,
    api_twofa_user_toggle,
    audit_log_view,
    checklist_index,
    checklist_utente,
    guestportal_sso,
    notifiche_config_view,
    notifiche_log_view,
    twofa_config,
)
from .navigazione import (
    api_legacy_redirect_delete,
    api_legacy_redirect_upsert,
    api_modulo_crea_da_catalog,
    api_nav_user_override_clear,
    api_nav_user_override_toggle,
    api_navigation_bootstrap_from_legacy,
    api_navigation_icon_upload,
    api_navigation_item_create,
    api_navigation_item_delete,
    api_navigation_item_update,
    api_navigation_publish,
    api_navigation_reorder,
    api_navigation_restore,
    api_pulsanti_card_image,
    api_pulsanti_module_card_image,
    api_pulsanti_set_enabled,
    api_wizard_pulsante_submit,
    navigation_builder,
    schema_dati,
    topbar_live,
    wizard_pulsante,
)
from .release import (
    api_release_restart_service,
    api_release_terminal_command,
    crea_release,
    download_release_package,
)
from .utenti import (
    api_anagrafica_risposte_save,
    api_reparto_capo_delete,
    api_reparto_capo_set,
    api_reparto_capo_sync,
    api_user_asset_assignments,
    api_user_dashboard_toggle,
    api_user_extra_info,
    api_user_module_toggle,
    api_user_modulo_perm_set,
    api_user_perm_override,
    ldap_diagnostica,
    ldap_import_utenti,
    user_activity_view,
    utente_create,
    utente_delete,
    utente_edit,
    utente_force_change_password,
    utente_impersonate,
    utente_permessi_effettivi,
    utente_quick_role,
    utente_toggle_active,
    utente_update,
    utenti_bulk_action,
    utenti_bulk_role,
    utenti_list,
)

from . import _helpers, accessi, branding, configurazione, navigazione, release, utenti  # noqa: E402

_PILASTRI = (_helpers, accessi, branding, configurazione, navigazione, release, utenti)


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
