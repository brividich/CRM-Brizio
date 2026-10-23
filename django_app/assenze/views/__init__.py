"""Viste del modulo Assenze, spezzate per pilastro (18/10/2026).

Lega qui solo le view di ``urls.py`` e il blocco import storico, così
``from assenze.views import X`` e ``views.X`` in ``urls.py`` restano invariati.
Tutto il resto non viene copiato ma letto dai sottomoduli via ``__getattr__`` (vedi in fondo);
per i test ``mock.patch`` va su ``assenze.views._helpers.X`` per le funzioni condivise
e su ``assenze.views.<pilastro>.X`` per le altre.
"""
# ruff: noqa: F401, E402

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core import signing
from django.db import connections, transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from config.env_config import get_first_env_value
from core.csv_export import CSV_CONTENT_TYPE, bom_first, safe_csv_writer
from core.acl import user_can_modulo_action
from core.caporeparto_utils import resolve_caporeparto_legacy_user

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_utils import get_legacy_user, legacy_table_columns, legacy_table_has_column
from core.models import AuditLog
from core.module_branding import get_module_branding_context, handle_module_branding_post
from core.permessi import decisione, sistema_ruoli_attivo

from ..constants import (
    AUTO_FINE_MINUTI,
    TIPI_ASSENZA_STORAGE,
    TIPI_ASSENZA_UI,
    SHORTCUT_PRESETS,
    SHORTCUT_CUSTOM,
    PERMESSO_MIN_MINUTES,
    PERMESSO_MAX_HOURS,
)
from core import naming
from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

from .amministrazione import (
    api_admin_assenza_delete,
    api_admin_bulk_consenso,
    export_gestione_assenze_csv,
    gestione_admin,
    impostazioni_admin,
    riconciliazione,
)
from .eventi import (
    api_check_corsi,
    api_dipendente_default_capo,
    api_eventi,
    api_eventi_colors,
    api_evento_delete,
    api_evento_update,
    calendario,
    menu,
)
from .richieste import (
    aggiorna_consenso_placeholder,
    api_car_aggiorna_consenso,
    api_mia_assenza_update,
    car_dashboard,
    certificazione_presenza,
    export_assenze_car_csv,
    gestione_assenze,
    invio_placeholder,
    richiesta_assenze,
)
from .sharepoint import (
    api_sync_pull,
    api_sync_push,
)
from .hr_gestione import (
    api_storico,
    api_verifica_richiesta,
    hr_calendario,
    hr_contatori,
    hr_copertura,
    hr_cruscotto,
    hr_saldi,
    hr_saldi_modello,
)

from . import _helpers, amministrazione, eventi, hr_gestione, richieste, sharepoint  # noqa: E402

_PILASTRI = (_helpers, amministrazione, eventi, richieste, sharepoint, hr_gestione)


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
