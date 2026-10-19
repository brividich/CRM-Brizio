"""API dati in sola lettura per applicazioni: ``/api/v1/``.

Per Power BI (connettore Web), Power Automate, gestionali. **Solo rete interna**:

* autenticazione per applicazione: ``Authorization: Bearer <token>``; a DB c'è solo
  l'hash SHA-256 (:class:`dati_bi.models.ApiClient`), confronto con
  ``hmac.compare_digest``; ogni applicazione legge solo i suoi **ambiti**;
* client IP ammessi in ``DATI_API_ALLOWED_IPS`` (IP o reti CIDR);
* solo GET, risposte JSON (401 token assente/errato, 403 rete o ambito non ammessi);
* **nessun dato personale nominativo**: niente nomi di persone, email, testi
  liberi; il personale c'è solo come conteggi per reparto e tipo.

Il prefisso è in ``MIDDLEWARE_EXEMPT_PREFIXES`` (niente sessione: chiama una
macchina), quindi l'unica protezione è qui. Non pubblicarlo su Entra Application
Proxy. Contratto ed esempi: docs/moduli/dati_bi.md. Lo schema OpenAPI
(``/api/v1/openapi.json``) è visibile solo agli amministratori collegati.
"""
# Niente «from __future__ import annotations»: django-ninja legge le annotazioni
# dei parametri a runtime (con le stringhe i parametri di query non si risolvono).
import hmac
import ipaddress
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from ninja import Field, NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.pagination import LimitOffsetPagination, paginate
from ninja.security import HttpBearer

from core.net import client_ip

from .models import ApiClient

logger = logging.getLogger(__name__)

MAX_PAGINA = 500


def _ip_ammesso(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in getattr(settings, "DATI_API_ALLOWED_IPS", ["127.0.0.1", "::1"]) or []:
        entry = str(entry).strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.warning("DATI_API_ALLOWED_IPS: voce non valida %r", entry)
    return False


class ClientAuth(HttpBearer):
    """Bearer token dell'applicazione. Rete non ammessa = 403, token errato = 401."""

    def authenticate(self, request, token):
        if not _ip_ammesso(client_ip(request)):
            raise HttpError(403, "Rete non autorizzata per l'API dati.")
        token = (token or "").strip()
        if not token:
            return None
        digest = ApiClient.hash_token(token)
        client = ApiClient.objects.filter(token_hash=digest, attivo=True).first()
        if client is None or not hmac.compare_digest(client.token_hash, digest):
            return None
        now = timezone.now()
        if client.ultimo_accesso is None or (now - client.ultimo_accesso).total_seconds() > 300:
            ApiClient.objects.filter(pk=client.pk).update(ultimo_accesso=now)
        return client


def _richiede(request, ambito: str) -> ApiClient:
    client: ApiClient = request.auth
    if not client.puo(ambito):
        raise HttpError(403, f"Ambito «{ambito}» non autorizzato per questa applicazione.")
    return client


api = NinjaAPI(
    title="NOVICROM HUB — API dati (sola lettura)",
    version="1.0.0",
    urls_namespace="dati_bi_api",
    auth=ClientAuth(),
    docs_url=None,
    openapi_url="/openapi.json",
    docs_decorator=staff_member_required,
    description="Dati del portale per Power BI e altre applicazioni. Nessun dato personale nominativo.",
)


class Pagina(LimitOffsetPagination):
    class Input(LimitOffsetPagination.Input):
        limit: int = 100

    def paginate_queryset(self, queryset, pagination, **params):
        pagination.limit = max(1, min(int(pagination.limit or 100), MAX_PAGINA))
        return super().paginate_queryset(queryset, pagination, **params)


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class AssetOut(Schema):
    asset_id: int = Field(..., alias="id")
    asset_tag: str
    numero_interno: str = Field("", alias="internal_number")
    nome: str = Field(..., alias="name")
    tipo: str = Field(..., alias="asset_type")
    categoria: Optional[str] = None
    reparto: str = ""
    stato: str = Field(..., alias="status")
    costruttore: Optional[str] = Field(None, alias="manufacturer")
    modello: Optional[str] = Field(None, alias="model")
    data_acquisto: Optional[date] = Field(None, alias="purchase_date")

    @staticmethod
    def resolve_categoria(obj):
        return obj.asset_category.label if obj.asset_category_id else None


@api.get("/asset/", response=List[AssetOut], summary="Anagrafica asset")
@paginate(Pagina)
def elenco_asset(request, reparto: str = "", stato: str = ""):
    _richiede(request, "asset")
    from assets.models import Asset

    qs = Asset.objects.select_related("asset_category").order_by("asset_tag", "id")
    if reparto:
        qs = qs.filter(reparto=reparto)
    if stato:
        qs = qs.filter(status=stato)
    return qs


# ---------------------------------------------------------------------------
# Manutenzione
# ---------------------------------------------------------------------------

class OrdineLavoroOut(Schema):
    odl_id: int = Field(..., alias="id")
    asset_tag: str = ""
    reparto: str = ""
    tipo: str = Field(..., alias="kind")
    priorita: str = Field(..., alias="priority")
    stato: str = Field(..., alias="status")
    titolo: str = Field("", alias="title")
    aperto_il: Optional[datetime] = Field(None, alias="opened_at")
    chiuso_il: Optional[datetime] = Field(None, alias="closed_at")
    minuti_intervento: Optional[int] = Field(None, alias="intervention_duration_minutes")
    minuti_fermo: Optional[int] = Field(None, alias="downtime_minutes")
    costo_totale_eur: Optional[Decimal] = Field(None, alias="cost_eur")
    esterno: bool = False
    fornitore: Optional[str] = None

    @staticmethod
    def resolve_asset_tag(obj):
        return obj.asset.asset_tag

    @staticmethod
    def resolve_reparto(obj):
        return obj.asset.reparto or ""

    @staticmethod
    def resolve_esterno(obj):
        return bool(obj.supplier_id)

    @staticmethod
    def resolve_fornitore(obj):
        return obj.supplier.ragione_sociale if obj.supplier_id else None


@api.get("/ordini-lavoro/", response=List[OrdineLavoroOut], summary="Ordini di lavoro (senza assegnatari)")
@paginate(Pagina)
def elenco_ordini_lavoro(request, dal: Optional[date] = None, al: Optional[date] = None, stato: str = ""):
    _richiede(request, "manutenzione")
    from assets.models import WorkOrder

    qs = WorkOrder.objects.select_related("asset", "supplier").order_by("-opened_at", "-id")
    if dal:
        qs = qs.filter(opened_at__date__gte=dal)
    if al:
        qs = qs.filter(opened_at__date__lte=al)
    if stato:
        qs = qs.filter(status=stato)
    return qs


# ---------------------------------------------------------------------------
# Scadenze (stesse sorgenti e regole dello Scadenzario globale)
# ---------------------------------------------------------------------------

# Sorgenti dello scadenzario esposte voce per voce, e se il «soggetto» è una
# cosa (asset, impianto, registro) e quindi si può mostrare. Personale (HR) mai
# voce per voce: solo /scadenze/riepilogo/ con l'ambito personale_aggregato.
_SORGENTI_DETTAGLIO = {"asset": True, "impianti": True, "rentri": True, "dpi": False, "capa": False}


class ServizioUtente:
    """Identità di servizio per i provider dello scadenzario: l'autorizzazione
    vera è l'ambito del token; qui si leggono tutte le voci delle sorgenti
    richieste e si tolgono i nominativi prima di rispondere."""

    is_authenticated = True
    is_active = True
    is_superuser = True
    is_staff = False
    id = pk = None
    username = "api-dati"

    def get_full_name(self):
        return "API dati"


def _voci(sorgenti: set[str], oggi: date | None = None):
    from django.http import HttpRequest

    from dashboard.scadenze_providers import collect_all

    request = HttpRequest()
    request.method = "GET"
    request.user = ServizioUtente()
    request.session = {}
    return collect_all(request, sources=sorgenti, oggi=oggi)


def _stato(giorni: int | None) -> str:
    if giorni is None:
        return ""
    if giorni < 0:
        return "scaduta"
    if giorni <= 30:
        return "entro_30"
    if giorni <= 60:
        return "entro_60"
    return "entro_90"


class ScadenzaOut(Schema):
    fonte: str
    tipo: str
    tipo_etichetta: str
    titolo: str
    soggetto: str
    reparto: str
    scadenza: Optional[date]
    giorni: Optional[int]
    stato: str


@api.get("/scadenze/", response=List[ScadenzaOut], summary="Scadenze voce per voce (senza nominativi)")
@paginate(Pagina)
def elenco_scadenze(request, fonte: str = "", stato: str = ""):
    _richiede(request, "scadenze")
    sorgenti = set(_SORGENTI_DETTAGLIO)
    if fonte:
        if fonte not in _SORGENTI_DETTAGLIO:
            raise HttpError(400, f"Fonte non valida. Valori: {', '.join(sorted(_SORGENTI_DETTAGLIO))}.")
        sorgenti = {fonte}
    out = []
    for v in _voci(sorgenti):
        riga = {
            "fonte": v.source, "tipo": v.kind, "tipo_etichetta": v.kind_label,
            "titolo": v.titolo if _SORGENTI_DETTAGLIO.get(v.source) or v.source == "dpi" else v.kind_label,
            "soggetto": v.soggetto if _SORGENTI_DETTAGLIO.get(v.source) else "",
            "reparto": v.reparto or "", "scadenza": v.data_scadenza, "giorni": v.giorni,
            "stato": _stato(v.giorni),
        }
        if stato and riga["stato"] != stato:
            continue
        out.append(riga)
    return out


class RiepilogoOut(Schema):
    fonte: str
    tipo: str
    tipo_etichetta: str
    reparto: str
    stato: str
    quante: int


@api.get("/scadenze/riepilogo/", response=List[RiepilogoOut], summary="Conteggi per fonte, tipo, reparto e stato")
def riepilogo_scadenze(request):
    client = _richiede(request, "scadenze")
    sorgenti = set(_SORGENTI_DETTAGLIO)
    if client.puo("personale_aggregato"):
        sorgenti.add("hr")
    conteggi: dict[tuple, int] = {}
    etichette: dict[str, str] = {}
    for v in _voci(sorgenti):
        chiave = (v.source, v.kind, v.reparto or "", _stato(v.giorni))
        conteggi[chiave] = conteggi.get(chiave, 0) + 1
        etichette[v.kind] = v.kind_label
    return [
        {"fonte": f, "tipo": t, "tipo_etichetta": etichette.get(t, t), "reparto": r, "stato": s, "quante": n}
        for (f, t, r, s), n in sorted(conteggi.items())
    ]


class StatoOut(Schema):
    applicazione: str
    ambiti: List[str]
    ora_server: datetime


@api.get("/stato/", response=StatoOut, summary="Verifica del token e degli ambiti")
def stato(request):
    client: ApiClient = request.auth
    return {"applicazione": client.nome, "ambiti": list(client.ambiti or []), "ora_server": timezone.now()}
