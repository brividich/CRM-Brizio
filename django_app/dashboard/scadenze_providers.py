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

SOURCE_LABELS = {
    SOURCE_HR: "Personale (HR)",
    SOURCE_ASSET: "Asset",
    SOURCE_DPI: "DPI",
    SOURCE_RENTRI: "RENTRI",
    SOURCE_CAPA: "Azioni CAPA",
}


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


@dataclass
class ScadenzeContext:
    """Contesto passato a ogni provider (data di riferimento + soglie + request)."""

    request: object
    oggi: date
    soglia_30: date
    soglia_60: date

    @classmethod
    def build(cls, request) -> "ScadenzeContext":
        oggi = timezone.localdate()
        return cls(
            request=request,
            oggi=oggi,
            soglia_30=oggi + timedelta(days=30),
            soglia_60=oggi + timedelta(days=60),
        )


def _giorni(oggi: date, scad: date | None) -> int | None:
    return (scad - oggi).days if scad else None


# ---------------------------------------------------------------------------
# Provider: Asset (scadenze amministrative)
# ---------------------------------------------------------------------------

def collect_asset(ctx: ScadenzeContext) -> list[ScadenzaItem]:
    """Scadenze amministrative degli asset (`AssetAdministrativeDeadline`).

    Gating: il modulo asset usa ACL di route + `@login_required`; la lista
    scadenze è visibile agli utenti con accesso al modulo asset. Qui replichiamo
    la sola visibilità di modulo (lettura), coerente con `asset_administrative_deadline_list`.
    """
    from core.acl import user_can_modulo_action

    request = ctx.request
    if not getattr(request.user, "is_superuser", False):
        if not user_can_modulo_action(request, "assets", "assets_deadlines"):
            return []

    from assets.models import AssetAdministrativeDeadline
    from django.urls import reverse

    items: list[ScadenzaItem] = []
    qs = (
        AssetAdministrativeDeadline.objects
        .select_related("asset")
        .filter(is_active=True, due_date__isnull=False, due_date__lte=ctx.soglia_60)
        .order_by("due_date")
    )
    for d in qs:
        asset = d.asset
        try:
            url = reverse("assets:asset_detail", args=[asset.id]) if asset else ""
        except Exception:
            url = ""
        items.append(
            ScadenzaItem(
                source=SOURCE_ASSET,
                kind=d.deadline_type.lower(),
                kind_label=d.get_deadline_type_display(),
                titolo=d.title,
                soggetto=(getattr(asset, "name", "") or getattr(asset, "asset_tag", "") or "").strip(),
                reparto=str(getattr(asset, "reparto", "") or "").strip(),
                data_scadenza=d.due_date,
                giorni=_giorni(ctx.oggi, d.due_date),
                url=url,
                extra={"asset_tag": getattr(asset, "asset_tag", "")},
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
            if scad > ctx.soglia_60:
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

    from dpi.models import ConsegnaDPI
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from django.urls import reverse

    qs = (
        ConsegnaDPI.objects
        .select_related("richiesta", "richiesta__tipo_dpi", "richiesta__categoria")
        .filter(data_scadenza_stimata__isnull=False, data_scadenza_stimata__lte=ctx.soglia_60)
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
    """Scadenze del personale, ognuna gated dal proprio permesso anagrafica.

    - Qualifiche: visibili a ogni utente autenticato.
    - Visite mediche (dati sanitari): solo `_can_view_visite_mediche` → titolo
      generico "Visita medica" senza esiti clinici (privacy).
    - Formazione obbligatoria: solo `_can_view_formazione`.
    - Contratti a termine / periodi di prova (dato HR): solo `_check_hr_permission`.
    """
    from django.db.models import Max
    from anagrafica.views import (
        _can_view_formazione,
        _can_view_visite_mediche,
        _check_hr_permission,
    )
    from anagrafica.models import (
        DipendenteAnagraficaAziendale,
        DipendenteQualifica,
        StoricoContratto,
        VisitaMedica,
    )
    from anagrafica.models_formazione import TrainingDeadline
    from core.legacy_anagrafica import fetch_anagrafica_rows

    request = ctx.request
    oggi, soglia = ctx.oggi, ctx.soglia_60

    dip_map = {int(r["id"]): r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("id")}

    def _dip(legacy_id):
        d = dip_map.get(legacy_id, {})
        nominativo = " ".join(
            str(d.get(k) or "").strip() for k in ("cognome", "nome")
        ).strip() or f"ID {legacy_id}"
        return nominativo, str(d.get("reparto") or "").strip()

    items: list[ScadenzaItem] = []

    # Qualifiche (tutti)
    for q in DipendenteQualifica.objects.select_related("tipo").filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia
    ):
        nominativo, reparto = _dip(q.legacy_anagrafica_id)
        items.append(ScadenzaItem(
            source=SOURCE_HR, kind="qualifica", kind_label="Qualifica",
            titolo=q.tipo.nome, soggetto=nominativo, reparto=reparto,
            data_scadenza=q.data_scadenza, giorni=_giorni(oggi, q.data_scadenza),
            extra={"legacy_id": q.legacy_anagrafica_id},
        ))

    # Visite mediche (gated — solo esito valido/scaduto, nessun dato clinico)
    if _can_view_visite_mediche(request):
        latest = (
            VisitaMedica.objects.filter(data_scadenza__isnull=False)
            .values("legacy_anagrafica_id", "tipo_id").annotate(m=Max("id"))
            .values_list("m", flat=True)
        )
        for v in VisitaMedica.objects.select_related("tipo").filter(
            id__in=list(latest), data_scadenza__lte=soglia
        ):
            nominativo, reparto = _dip(v.legacy_anagrafica_id)
            items.append(ScadenzaItem(
                source=SOURCE_HR, kind="visita", kind_label="Visita medica",
                titolo=v.tipo.nome, soggetto=nominativo, reparto=reparto,
                data_scadenza=v.data_scadenza, giorni=_giorni(oggi, v.data_scadenza),
                extra={"legacy_id": v.legacy_anagrafica_id},
            ))

    # Formazione obbligatoria (gated)
    if _can_view_formazione(request):
        for d in TrainingDeadline.objects.select_related("corso").filter(
            is_required=True, data_scadenza__isnull=False, data_scadenza__lte=soglia
        ):
            nominativo, reparto = _dip(d.legacy_anagrafica_id)
            items.append(ScadenzaItem(
                source=SOURCE_HR, kind="formazione", kind_label="Formazione",
                titolo=d.corso.titolo, soggetto=nominativo, reparto=reparto,
                data_scadenza=d.data_scadenza, giorni=_giorni(oggi, d.data_scadenza),
                extra={"legacy_id": d.legacy_anagrafica_id},
            ))

    # Contratti a termine e periodi di prova (gated: dato HR)
    if _check_hr_permission(request):
        cessati = set(
            DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        ultimo: dict[int, StoricoContratto] = {}
        for c in (
            StoricoContratto.objects.filter(legacy_anagrafica_id__isnull=False)
            .order_by("legacy_anagrafica_id", "-data_inizio", "-created_at")
        ):
            ultimo.setdefault(c.legacy_anagrafica_id, c)
        scadenze: list[tuple[int, date, str]] = []
        for legacy_id, c in ultimo.items():
            if legacy_id in cessati or c.data_fine is None:
                continue
            scadenze.append((legacy_id, c.data_fine, f"Contratto {c.tipologia_contratto or 'a termine'}"))
        for legacy_id, fine in DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=True, prova_data_fine__isnull=False, prova_data_fine__gte=oggi
        ).values_list("legacy_anagrafica_id", "prova_data_fine"):
            scadenze.append((legacy_id, fine, "Fine periodo di prova"))
        for legacy_id, data_fine, descr in scadenze:
            if data_fine > soglia:
                continue
            nominativo, reparto = _dip(legacy_id)
            items.append(ScadenzaItem(
                source=SOURCE_HR, kind="contratto", kind_label="Contratto",
                titolo=descr, soggetto=nominativo, reparto=reparto,
                data_scadenza=data_fine, giorni=_giorni(oggi, data_fine),
                extra={"legacy_id": legacy_id},
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
        .filter(data_scadenza__isnull=False, data_scadenza__lte=ctx.soglia_60)
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
# Registry + aggregatore difensivo
# ---------------------------------------------------------------------------

# Ordine = ordine di sorgente nei filtri UI.
PROVIDERS: dict[str, Callable[[ScadenzeContext], list[ScadenzaItem]]] = {
    SOURCE_HR: collect_hr,
    SOURCE_ASSET: collect_asset,
    SOURCE_DPI: collect_dpi,
    SOURCE_RENTRI: collect_rentri,
    SOURCE_CAPA: collect_capa,
}


def collect_all(request, *, sources: set[str] | None = None) -> list[ScadenzaItem]:
    """Esegue i provider richiesti e ritorna le voci ordinate per urgenza.

    Ogni provider è isolato: un errore (modulo assente/rotto, query legacy non
    disponibile) viene loggato e non fa cadere l'intera pagina — la sorgente
    semplicemente non contribuisce.
    """
    ctx = ScadenzeContext.build(request)
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
