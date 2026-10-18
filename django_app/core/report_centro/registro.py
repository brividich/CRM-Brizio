"""Registro delle emissioni: chi ha scaricato quale report, quando, con quali filtri.

Il middleware guarda ogni risposta e, se porta un documento generato (PDF,
Excel, CSV, Word, ZIP), scrive una :class:`core.models.ReportEmissione`. Nessun
modulo deve chiamarlo: basta che il file esca da una view.

Cosa entra nel registro:

- risposte **non in streaming** con un tipo da report → sono file costruiti al
  volo dal portale (i generatori lavorano in memoria);
- risposte **in streaming** (``FileResponse``) solo se la route è nel catalogo:
  di norma sono allegati caricati dagli utenti, che non sono report — ma alcune
  voci (archivio della reportistica, report pianificati) servono un file già
  generato e salvato.

Le route di scaricamento di allegati e documenti caricati (nomi con
«allegato», «download», «scarica», «documento»…) restano fuori se non sono
catalogate. Le altre route non catalogate vengono registrate comunque, con
chiave vuota: la pagina del Centro report le mostra come «da catalogare».

Il file non viene mai conservato: solo nome, dimensione, impronta SHA-256 e i
parametri della richiesta (querystring e argomenti della route, senza segreti).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta

from django.utils import timezone

from core.report_centro import catalogo

logger = logging.getLogger(__name__)

CONTENT_TYPE_FORMATO = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",
    "text/csv": "csv",
    "application/csv": "csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
}
ESTENSIONE_FORMATO = {"pdf": "pdf", "xlsx": "xlsx", "xls": "xlsx", "csv": "csv", "docx": "docx", "zip": "zip"}

# Route non catalogate con questi frammenti nel nome servono file caricati o
# anteprime di configurazione, non report.
_ROUTE_ALLEGATI = re.compile(
    r"allegat|attachment|download|scarica|documento|referto|_file\b|upload|template|anteprima|preview", re.I
)
# Chiavi della querystring che non devono mai finire nel registro.
_CHIAVI_SEGRETE = re.compile(r"token|password|passwd|secret|csrf|sig|auth", re.I)
_FILENAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.I)

MAX_PARAMETRI = 30
MAX_VALORE = 200

RETENTION_KEY = "report_emissioni_conservazione_giorni"
RETENTION_DEFAULT = 730
MAX_GIORNI = 3650


def _nome_file(response) -> str:
    disposition = str(response.get("Content-Disposition") or "")
    match = _FILENAME.search(disposition)
    if not match:
        return ""
    from urllib.parse import unquote

    return unquote(match.group(1)).strip()[:255]


def formato_risposta(response) -> str:
    """Formato del documento nella risposta, o stringa vuota se non è un report."""
    content_type = str(response.get("Content-Type") or "").split(";")[0].strip().lower()
    formato = CONTENT_TYPE_FORMATO.get(content_type, "")
    if formato:
        return formato
    nome = _nome_file(response)
    if nome and "." in nome and content_type in ("", "application/octet-stream"):
        return ESTENSIONE_FORMATO.get(nome.rsplit(".", 1)[1].lower(), "")
    return ""


def _parametri(request) -> dict:
    risultato: dict = {}
    for chiave in list(request.GET.keys())[:MAX_PARAMETRI]:
        if _CHIAVI_SEGRETE.search(chiave):
            continue
        valori = [str(v)[:MAX_VALORE] for v in request.GET.getlist(chiave)[:5]]
        risultato[chiave[:60]] = valori[0] if len(valori) == 1 else valori
    match = getattr(request, "resolver_match", None)
    kwargs = getattr(match, "kwargs", None) or {}
    if kwargs:
        risultato["_route"] = {str(k)[:60]: str(v)[:MAX_VALORE] for k, v in list(kwargs.items())[:10]}
    return risultato


def _dimensione_e_impronta(response) -> tuple[int | None, str]:
    if getattr(response, "streaming", False):
        try:
            return int(response.get("Content-Length")), ""
        except (TypeError, ValueError):
            return None, ""
    contenuto = response.content or b""
    return len(contenuto), hashlib.sha256(contenuto).hexdigest()


def deve_registrare(request, response) -> tuple[bool, str, "catalogo.ReportVoce | None"]:
    """Decide se la risposta va nel registro. Ritorna (sì/no, formato, voce)."""
    if getattr(response, "status_code", 0) != 200:
        return False, "", None
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False, "", None
    formato = formato_risposta(response)
    if not formato:
        return False, "", None
    match = getattr(request, "resolver_match", None)
    view_name = str(getattr(match, "view_name", "") or "")
    voce = catalogo.voce_per_route(view_name) if view_name else None
    if voce is not None:
        return True, formato, voce
    if getattr(response, "streaming", False):
        return False, "", None
    if view_name and _ROUTE_ALLEGATI.search(view_name):
        return False, "", None
    return True, formato, None


def registra(request, response, *, formato: str, voce) -> None:
    from core.audit import _get_client_ip
    from core.impersonation import display_name_for_user
    from core.models import ReportEmissione

    match = getattr(request, "resolver_match", None)
    view_name = str(getattr(match, "view_name", "") or "")
    impersonator_legacy = getattr(request, "impersonator_legacy_user", None)
    effective_legacy = getattr(request, "legacy_user", None)
    if effective_legacy is None:
        try:
            from core.legacy_utils import get_legacy_user

            effective_legacy = get_legacy_user(request.user)
        except Exception:
            effective_legacy = None
    actor_legacy = impersonator_legacy or effective_legacy
    utente = display_name_for_user(
        django_user=getattr(request, "impersonator_user", None) or request.user,
        legacy_user=actor_legacy,
    )
    impersonato = ""
    if getattr(request, "impersonation_active", False):
        impersonato = display_name_for_user(
            django_user=getattr(request, "impersonated_user", None) or request.user,
            legacy_user=getattr(request, "impersonated_legacy_user", None) or effective_legacy,
        )
    dimensione, impronta = _dimensione_e_impronta(response)
    nome_file = _nome_file(response)
    if voce is not None:
        modulo = voce.modulo
        titolo = voce.nome
    else:
        modulo = view_name.split(":", 1)[0] if ":" in view_name else ""
        titolo = nome_file or view_name or request.path
    ReportEmissione.objects.create(
        legacy_user_id=getattr(actor_legacy, "id", None),
        utente_display=str(utente or "")[:200],
        impersonato_display=str(impersonato or "")[:200],
        report_chiave=voce.chiave if voce is not None else "",
        modulo=modulo[:80],
        titolo=str(titolo)[:200],
        route_name=view_name[:160],
        path=str(request.path)[:500],
        formato=formato if formato in dict(ReportEmissione.FORMATO_CHOICES) else "altro",
        nome_file=nome_file,
        dimensione_byte=dimensione,
        sha256=impronta,
        parametri=_parametri(request),
        dati_personali=bool(voce.dati_personali) if voce is not None else False,
        profilo_layout=str(getattr(request, "_report_profilo_layout", "") or "")[:100],
        ip_address=_get_client_ip(request),
    )


class ReportEmissioneMiddleware:
    """Registra i report scaricati. Non blocca mai la risposta: un errore va nel log."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            ok, formato, voce = deve_registrare(request, response)
            if ok:
                registra(request, response, formato=formato, voce=voce)
        except Exception:
            logger.exception("Registro emissioni report: scrittura fallita per %s", getattr(request, "path", "?"))
        return response


# ---------------------------------------------------------------------------
# Conservazione
# ---------------------------------------------------------------------------

def giorni_conservazione() -> int:
    from core.models import SiteConfig

    try:
        valore = int(str(SiteConfig.get(RETENTION_KEY, str(RETENTION_DEFAULT))).strip())
    except (TypeError, ValueError):
        return RETENTION_DEFAULT
    return max(0, min(valore, MAX_GIORNI))


def imposta_conservazione(giorni: int) -> int:
    from core.models import SiteConfig

    giorni = max(0, min(int(giorni), MAX_GIORNI))
    SiteConfig.set(RETENTION_KEY, str(giorni), "Centro report: giorni di conservazione del registro emissioni (0 = sempre).")
    return giorni


def pulisci_scadute(giorni: int | None = None) -> int:
    """Elimina le emissioni più vecchie della soglia. ``0`` = conserva sempre."""
    from core.models import ReportEmissione

    giorni = giorni_conservazione() if giorni is None else int(giorni)
    if giorni <= 0:
        return 0
    soglia = timezone.now() - timedelta(days=giorni)
    eliminate, _ = ReportEmissione.objects.filter(created_at__lt=soglia).delete()
    return int(eliminate)
