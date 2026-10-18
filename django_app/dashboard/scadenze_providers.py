"""Provider condivisi per lo Scadenzario Globale Unificato (`/scadenze`).

Ogni dominio espone un provider `collect_*(ctx) -> list[ScadenzaItem]` che riusa
la logica/permessi già presenti nel modulo sorgente. La view aggregatrice
(`dashboard.views_scadenze`) li compone, filtra ed esporta.

Principi:
- **Nessuna duplicazione di logica di dominio**: i provider chiamano gli helper
  esistenti dei moduli; qui vive solo la normalizzazione verso `ScadenzaItem`.
- **Permessi**: ogni provider riceve la `request` e decide da sé se contribuire
  (rispettando l'ACL del proprio modulo). Un provider non autorizzato ritorna [].
- **Difensivo**: ogni provider è isolato in try/except a monte (vedi
  `collect_all`): un modulo rotto/assente non fa cadere l'intera pagina.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from django.utils import timezone

logger = logging.getLogger(__name__)


# Codici sorgente (stabili: usati nei filtri GET e nei test).
SOURCE_HR = "hr"
SOURCE_ASSET = "asset"
SOURCE_DPI = "dpi"
SOURCE_RENTRI = "rentri"
SOURCE_CAPA = "capa"
SOURCE_IMPIANTI = "impianti"

SOURCE_LABELS = {
    SOURCE_HR: "Personale (HR)",
    SOURCE_ASSET: "Asset",
    SOURCE_IMPIANTI: "Verifiche impianti",
    SOURCE_DPI: "DPI",
    SOURCE_RENTRI: "RENTRI",
    SOURCE_CAPA: "Azioni CAPA",
}

# Orizzonte dello scadenzario: tutto ciò che è scaduto più ciò che scade entro
# questi giorni. I filtri 30/60/90 lavorano dentro questa finestra.
ORIZZONTE_GIORNI = 90

# Pagina delle verifiche impianti: la sorgente entra solo se chi guarda la può
# aprire (stessa decisione dell'ACLMiddleware).
VERIFICHE_IMPIANTI_PATH = "/assets/manutenzione/verifiche-impianti/"


@dataclass
class ScadenzaItem:
    """Voce normalizzata dello scadenzario globale, comune a tutti i domini."""

    source: str               # uno dei SOURCE_*
    kind: str                 # sotto-tipo dominio (es. "qualifica", "fir")
    kind_label: str           # etichetta leggibile del tipo
    titolo: str               # descrizione breve della scadenza
    soggetto: str             # persona/asset/registro a cui si riferisce
    reparto: str              # reparto (per il filtro), "" se non applicabile
    data_scadenza: date | None
    giorni: int | None        # giorni alla scadenza (negativo = scaduto)
    url: str = ""             # link al dettaglio nel modulo sorgente
    extra: dict = field(default_factory=dict)

    @property
    def scaduta(self) -> bool:
        return self.giorni is not None and self.giorni < 0

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


@dataclass
class ScadenzeContext:
    """Contesto passato a ogni provider (data di riferimento + soglie + request)."""

    request: object
    oggi: date
    soglia_30: date
    soglia_60: date
    orizzonte: date

    @classmethod
    def build(cls, request, *, oggi: date | None = None) -> "ScadenzeContext":
        oggi = oggi or timezone.localdate()
        return cls(
            request=request,
            oggi=oggi,
            soglia_30=oggi + timedelta(days=30),
            soglia_60=oggi + timedelta(days=60),
            orizzonte=oggi + timedelta(days=ORIZZONTE_GIORNI),
        )


def _giorni(oggi: date, scad: date | None) -> int | None:
    return (scad - oggi).days if scad else None


# ---------------------------------------------------------------------------
# Provider: Asset (scadenze amministrative)
# ---------------------------------------------------------------------------

def collect_asset(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Scadenze asset: adempimenti amministrativi, licenze e contratti (`deadline_feed`).

    Gating: il modulo asset usa ACL di route + `@login_required`; la lista
    scadenze è visibile agli utenti con accesso al modulo asset. Qui replichiamo
    la sola visibilità di modulo (lettura), coerente con `asset_administrative_deadline_list`.
    """
    from core.acl import user_can_modulo_action

    request = ctx.request
    if not getattr(request.user, "is_superuser", False):
        if not user_can_modulo_action(request, "assets", "assets_deadlines"):
            return []

    # Stessa fonte di Calendario e Scadenzario della manutenzione: adempimenti
    # amministrativi (registro separato dai piani, senza le copie migrate,
    # senza doppioni), licenze software e contratti di assistenza. Licenze e
    # contratti restano soggetti all'ACL delle loro pagine.
    from assets.services import deadline_feed as feed

    kinds = feed.allowed_kinds(request) & {feed.KIND_ADMINISTRATIVE, feed.KIND_LICENSE, feed.KIND_CONTRACT}
    rows = feed.collect(
        start=None,
        end=ctx.orizzonte,
        filters=feed.FeedFilters(kinds=frozenset(kinds)),
        today=ctx.oggi,
    )
    items: list[ScadenzaItem] = []
    for row in rows:
        items.append(
            ScadenzaItem(
                source=SOURCE_ASSET,
                kind=row.kind,
                kind_label=row.kind_label,
                titolo=row.title,
                soggetto=(row.asset_name or row.asset_tag or row.target_label or "").strip(),
                reparto=(row.reparto or "").strip(),
                data_scadenza=row.due_date,
                giorni=_giorni(ctx.oggi, row.due_date),
                url=row.detail_url,
                extra={"asset_tag": row.asset_tag},
            )
        )
    return items


# ---------------------------------------------------------------------------
# Provider: RENTRI (FIR mancanti)
# ---------------------------------------------------------------------------

def collect_rentri(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Adempimenti RENTRI aperti — FIR mancanti sugli scarichi O/M/R.

    Riusa l'helper `_scadenzario_buckets` del modulo rentri (single source of
    truth) e prende il solo bucket `fir`. Il "giorni" è la giacenza: i movimenti
    senza FIR sono per definizione già "in ritardo" (giorni negativi = età).
    """
    from core.acl import user_can_modulo_action

    request = ctx.request
    if not getattr(request.user, "is_superuser", False):
        if not user_can_modulo_action(request, "rentri", "rentri_elenco"):
            return []

    from rentri.views import _scadenzario_buckets
    from django.urls import reverse

    try:
        elenco_url = reverse("rentri_elenco")
    except Exception:
        elenco_url = ""

    items: list[ScadenzaItem] = []
    buckets = _scadenzario_buckets(ctx.oggi)
    fir_bucket = next((b for b in buckets if b.get("key") == "fir"), None)

    for row in (fir_bucket or {}).get("rows", []):
        data = row.get("data")
        # giorni di giacenza → segno negativo per ordinare i più vecchi come "scaduti"
        giacenza = row.get("giorni")
        giorni = -giacenza if isinstance(giacenza, int) else None
        items.append(
            ScadenzaItem(
                source=SOURCE_RENTRI,
                kind="fir",
                kind_label="FIR mancante",
                titolo=f"FIR mancante · {row.get('tipo_label') or row.get('tipo') or ''}".strip(" ·"),
                soggetto=str(row.get("id_registrazione") or row.get("codice") or "").strip(),
                reparto="",
                data_scadenza=data,
                giorni=giorni,
                url=elenco_url,
                extra={"codice": row.get("codice"), "quantita": str(row.get("quantita") or "")},
            )
        )

    # Deposito temporaneo: CER in giacenza che si avvicinano/superano il limite.
    # Isolato in try/except così un errore qui non azzera anche i FIR.
    try:
        from datetime import timedelta
        from rentri.giacenze import giacenze_per_cer, soglie_deposito

        try:
            giacenze_url = reverse("rentri_giacenze")
        except Exception:
            giacenze_url = elenco_url

        gmax = soglie_deposito()["giorni_max"]
        for g in giacenze_per_cer():
            if not g.aperta or not g.primo_carico:
                continue
            scad = g.primo_carico + timedelta(days=gmax)
            if scad > ctx.orizzonte:
                continue
            items.append(
                ScadenzaItem(
                    source=SOURCE_RENTRI,
                    kind="deposito",
                    kind_label="Deposito temporaneo",
                    titolo=f"Deposito {'pericoloso ' if g.pericoloso else ''}CER {g.codice}".strip(),
                    soggetto=g.codice,
                    reparto="",
                    data_scadenza=scad,
                    giorni=_giorni(ctx.oggi, scad),
                    url=giacenze_url,
                    extra={
                        "giacenza": str(g.giacenza),
                        "giorni_deposito": g.giorni_giacenza,
                        "pericoloso": g.pericoloso,
                    },
                )
            )
    except Exception:
        logger.exception("Scadenzario globale: deposito temporaneo RENTRI fallito")

    return items


# ---------------------------------------------------------------------------
# Provider: DPI (vita utile residua)
# ---------------------------------------------------------------------------

def collect_dpi(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Scadenze DPI per vita utile (`ConsegnaDPI.data_scadenza_stimata`)."""
    from core.acl import user_can_modulo_action

    request = ctx.request
    if not getattr(request.user, "is_superuser", False):
        if not user_can_modulo_action(request, "dpi", "dpi_view"):
            return []

    from dpi.models import ConsegnaDPI, StatoRichiesta
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from django.urls import reverse

    # Stesso perimetro del promemoria DPI (``send_dpi_expiry_reminders``): solo le
    # consegne in essere. Una consegna sostituita da una successiva dello stesso
    # tipo è storico, non una scadenza da gestire.
    qs = (
        ConsegnaDPI.objects
        .select_related("richiesta", "richiesta__tipo_dpi", "richiesta__categoria")
        .filter(
            richiesta__stato=StatoRichiesta.CONSEGNATA,
            sostituita_da__isnull=True,
            data_scadenza_stimata__isnull=False,
            data_scadenza_stimata__lte=ctx.orizzonte,
        )
        .order_by("data_scadenza_stimata")
    )
    consegne = list(qs)
    if not consegne:
        return []

    legacy_ids = {
        c.richiesta.richiedente_legacy_id
        for c in consegne
        if c.richiesta and c.richiesta.richiedente_legacy_id
    }
    dip_map: dict[int, dict] = {}
    if legacy_ids:
        for r in fetch_anagrafica_rows(ids=list(legacy_ids), deduplicate=True):
            if r.get("id"):
                dip_map[int(r["id"])] = r

    items: list[ScadenzaItem] = []
    for c in consegne:
        req = c.richiesta
        dip = dip_map.get(getattr(req, "richiedente_legacy_id", None) or -1, {})
        nominativo = " ".join(
            str(dip.get(k) or "").strip() for k in ("cognome", "nome")
        ).strip() or getattr(req, "richiedente_nome", "") or (req.numero if req else "")
        # Il tipo DPI è opzionale; la categoria è sempre presente sulla richiesta.
        tipo = getattr(req, "tipo_dpi", None) or getattr(req, "categoria", None)
        try:
            url = reverse("dpi:detail", args=[req.id]) if req else ""
        except Exception:
            url = ""
        items.append(
            ScadenzaItem(
                source=SOURCE_DPI,
                kind="dpi",
                kind_label="DPI (vita utile)",
                titolo=getattr(tipo, "nome", "") or "DPI",
                soggetto=nominativo,
                reparto=str(dip.get("reparto") or "").strip(),
                data_scadenza=c.data_scadenza_stimata,
                giorni=_giorni(ctx.oggi, c.data_scadenza_stimata),
                url=url,
                extra={"richiesta": getattr(req, "numero", "")},
            )
        )
    return items


# ---------------------------------------------------------------------------
# Provider: HR (qualifiche, visite mediche, formazione obbligatoria, contratti)
# ---------------------------------------------------------------------------

def collect_hr(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Scadenze del personale: qualifiche, visite mediche, formazione obbligatoria,
    contratti e periodi di prova.

    Adattatore su ``anagrafica.views._build_scadenzario_voci``, la fonte unica dello
    Scadenzario di Anagrafica e del blocco «Cose da gestire»: stesse regole
    (solo la qualifica e la visita in vigore, ex dipendenti esclusi) e stesso
    gating per sorgente (visite = dato sanitario, formazione e contratti = dato
    HR). Prima qui c'era una seconda copia della logica che contava le qualifiche
    già rinnovate e i cessati: i numeri delle due pagine non tornavano.
    """
    from django.urls import reverse

    from anagrafica.views import _build_scadenzario_voci
    from core.naming import nome_completo

    voci = _build_scadenzario_voci(ctx.request, periodo=(date(1900, 1, 1), ctx.orizzonte))
    try:
        base_url = reverse("anagrafica:scadenzario")
    except Exception:
        base_url = ""

    items: list[ScadenzaItem] = []
    for v in voci:
        kind = v.get("kind") or ""
        items.append(ScadenzaItem(
            source=SOURCE_HR,
            kind=kind,
            kind_label=v.get("kind_label") or "",
            titolo=v.get("tipo_nome") or "",
            soggetto=nome_completo(v.get("nome") or "", v.get("cognome") or ""),
            reparto=(v.get("reparto") or "").strip(),
            data_scadenza=v.get("data_scadenza"),
            giorni=v.get("giorni"),
            url=f"{base_url}?tipo={kind}" if base_url and kind else base_url,
            extra={"legacy_id": v.get("legacy_id")},
        ))
    return items


# ---------------------------------------------------------------------------
# Provider: CAPA (azioni correttive/preventive con scadenza)
# ---------------------------------------------------------------------------

def collect_capa(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Azioni CAPA aperte con scadenza entro la soglia.

    Gating: i gestori CAPA (`_can_manage_capa`) vedono tutte le azioni; gli altri
    utenti vedono solo le proprie azioni assegnate (responsabile). Coerente con
    la lista `/capa/`.
    """
    from core.models import ActionItem
    from core.views_capa import _can_manage_capa
    from django.urls import reverse

    request = ctx.request
    qs = (
        ActionItem.objects
        .select_related("responsabile")
        .exclude(stato__in=ActionItem.STATI_CONCLUSI)
        .filter(data_scadenza__isnull=False, data_scadenza__lte=ctx.orizzonte)
    )
    if not _can_manage_capa(request):
        user_id = getattr(getattr(request, "user", None), "id", None)
        if not user_id:
            return []
        qs = qs.filter(responsabile_id=user_id)

    items: list[ScadenzaItem] = []
    for a in qs.order_by("data_scadenza"):
        try:
            url = reverse("capa_detail", args=[a.pk])
        except Exception:
            url = ""
        resp = a.responsabile
        soggetto = (resp.get_full_name() or resp.username) if resp else (a.source_label or "—")
        items.append(ScadenzaItem(
            source=SOURCE_CAPA,
            kind="capa",
            kind_label="Azione CAPA",
            titolo=a.titolo,
            soggetto=soggetto,
            reparto=str(a.reparto or "").strip(),
            data_scadenza=a.data_scadenza,
            giorni=_giorni(ctx.oggi, a.data_scadenza),
            url=url,
            extra={"origine": a.origine_label, "stato": a.get_stato_display()},
        ))
    return items


# ---------------------------------------------------------------------------
# Provider: verifiche periodiche degli impianti
# ---------------------------------------------------------------------------

def collect_impianti(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Prossime verifiche degli impianti (``PeriodicCheckType.next_due_date``).

    Stato e scadenza sono quelli della pagina Verifiche impianti
    (``assets.services.periodic_checks.type_state``): la data si ricalcola da sola
    a ogni verifica registrata, qui si legge e basta. I tipi senza data («da
    pianificare») non sono una scadenza e restano fuori.

    Gating: la stessa decisione ACL della pagina delle verifiche (fail-closed).
    """
    from core.middleware import acl_allows_path

    request = ctx.request
    try:
        if not acl_allows_path(VERIFICHE_IMPIANTI_PATH, django_user=request.user, request=request):
            return []
    except Exception:
        logger.exception("Scadenzario globale: ACL verifiche impianti non valutabile")
        return []

    from django.urls import reverse

    from assets.models import PeriodicCheckType
    from assets.services.periodic_checks import STATE_LABELS, type_state

    qs = (
        PeriodicCheckType.objects.select_related("system", "supplier")
        .filter(is_active=True, next_due_date__isnull=False, next_due_date__lte=ctx.orizzonte)
        .order_by("next_due_date", "id")
    )
    items: list[ScadenzaItem] = []
    for t in qs:
        stato = type_state(t, today=ctx.oggi)
        items.append(ScadenzaItem(
            source=SOURCE_IMPIANTI,
            kind="verifica_impianto",
            kind_label="Verifica impianto",
            titolo=t.name,
            soggetto=t.system.name if t.system_id else "",
            reparto="",
            data_scadenza=t.next_due_date,
            giorni=_giorni(ctx.oggi, t.next_due_date),
            url=reverse("assets:periodic_check_type_detail", args=[t.id]),
            extra={"stato": STATE_LABELS.get(stato, ""), "esecutore": t.performer_label},
        ))
    return items


# ---------------------------------------------------------------------------
# Registry + aggregatore difensivo
# ---------------------------------------------------------------------------

# Ordine = ordine di sorgente nei filtri UI.
PROVIDERS: dict[str, Callable[[ScadenzeContext], list[ScadenzaItem]]] = {
    SOURCE_HR: collect_hr,
    SOURCE_ASSET: collect_asset,
    SOURCE_IMPIANTI: collect_impianti,
    SOURCE_DPI: collect_dpi,
    SOURCE_RENTRI: collect_rentri,
    SOURCE_CAPA: collect_capa,
}


def collect_all(request, *, sources: set[str] | None = None, oggi: date | None = None) -> list[ScadenzaItem]:
    """Esegue i provider richiesti e ritorna le voci ordinate per urgenza.

    Ogni provider è isolato: un errore (modulo assente/rotto, query legacy non
    disponibile) viene loggato e non fa cadere l'intera pagina — la sorgente
    semplicemente non contribuisce.
    """
    ctx = ScadenzeContext.build(request, oggi=oggi)
    wanted = sources or set(PROVIDERS.keys())
    out: list[ScadenzaItem] = []
    for code, provider in PROVIDERS.items():
        if code not in wanted:
            continue
        try:
            out.extend(provider(ctx))
        except Exception:
            logger.exception("Scadenzario globale: provider '%s' fallito", code)
    # Urgenza: prima i più scaduti (giorni più negativi); None in fondo.
    out.sort(key=lambda it: (it.giorni is None, it.giorni if it.giorni is not None else 0))
    return out
