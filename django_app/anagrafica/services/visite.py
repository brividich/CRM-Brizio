"""Servizi di calcolo per le visite mediche dipendente.

Centralizza la logica di scadenza e di matching tipologie ↔ ruoli operativi
in modo che view, template e management command condividano un'unica fonte
di verità.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

from django.db.models import Max
from django.utils import timezone

from ..models import (
    DipendenteAnagraficaAziendale,
    DocumentoDipendente,
    DipendenteRuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)


STATO_MANCANTE = "mancante"
STATO_VALIDA = "valida"
STATO_IN_SCADENZA = "in_scadenza"
STATO_SCADUTA = "scaduta"
RIFERIMENTO_VISITA = "anagrafica.visitamedica"


def completa_referti_visite(visite: Iterable[VisitaMedica]) -> list[VisitaMedica]:
    """Aggiunge a ogni visita la lista dei referti, principale e aggiuntivi."""
    elenco = list(visite)
    if not elenco:
        return elenco

    visite_per_id = {visita.pk: visita for visita in elenco if visita.pk}
    aggiuntivi: dict[int, list[DocumentoDipendente]] = {
        visita_id: [] for visita_id in visite_per_id
    }
    documenti = (
        DocumentoDipendente.objects
        .filter(
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            oggetto_riferimento_tipo=RIFERIMENTO_VISITA,
            oggetto_riferimento_id__in=visite_per_id,
        )
        .order_by("created_at", "id")
    )
    for documento in documenti:
        aggiuntivi[documento.oggetto_riferimento_id].append(documento)

    for visita in elenco:
        referti = []
        visti = set()
        if visita.referto_documento_id:
            referti.append(visita.referto_documento)
            visti.add(visita.referto_documento_id)
        for documento in aggiuntivi.get(visita.pk, []):
            if documento.pk not in visti:
                referti.append(documento)
                visti.add(documento.pk)
        visita.referti_documenti = referti
    return elenco


def tipi_visita_richiesti_per_dipendente(legacy_id: int) -> list[TipoVisitaMedica]:
    """Ritorna i ``TipoVisitaMedica`` obbligatori per il dipendente.

    Il match avviene sui ruoli operativi attualmente assegnati al dipendente:
    tutte le tipologie ``is_active=True, obbligatoria=True`` che hanno
    almeno uno dei ruoli del dipendente nel proprio M2M ``ruoli_operativi``.
    """
    ruoli_ids = list(
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("ruolo_id", flat=True)
    )
    tipi: dict[int, TipoVisitaMedica] = {}
    if ruoli_ids:
        for t in (
            TipoVisitaMedica.objects
            .filter(is_active=True, obbligatoria=True, ruoli_operativi__id__in=ruoli_ids)
            .distinct()
        ):
            tipi[t.id] = t

    # Sorgente MOD.128: visite richieste dai processi a cui la persona è abilitata.
    try:
        from .mpq_visite import tipi_visita_richiesti_da_processo
        extra_ids = tipi_visita_richiesti_da_processo(legacy_id) - set(tipi.keys())
    except Exception:
        extra_ids = set()
    if extra_ids:
        for t in TipoVisitaMedica.objects.filter(id__in=extra_ids, is_active=True):
            tipi[t.id] = t

    # Sorgente certificato: il protocollo sanitario dell'ultimo certificato di
    # idoneità, deciso dal medico competente (mansione, rischi, età).
    for t in tipi_visita_da_requisiti(legacy_id):
        tipi.setdefault(t.id, t)

    return sorted(tipi.values(), key=lambda t: t.nome)


def tipi_visita_da_requisiti(legacy_id: int) -> list[TipoVisitaMedica]:
    """Tipi di visita richiesti dal protocollo dell'ultimo certificato (requisiti attivi)."""
    try:
        return list(
            TipoVisitaMedica.objects
            .filter(
                is_active=True,
                requisiti_dipendente__legacy_anagrafica_id=legacy_id,
                requisiti_dipendente__attivo=True,
            )
            .distinct()
        )
    except Exception:
        return []


def ultime_visite_per_tipo(legacy_id: int) -> dict[int, VisitaMedica]:
    """Restituisce, per ogni ``TipoVisitaMedica``, l'ultima ``VisitaMedica``
    svolta dal dipendente (per data_svolgimento).

    Implementato SQL Server-safe via subquery ``Max('data_svolgimento')`` per
    (legacy, tipo).
    """
    qs = VisitaMedica.objects.filter(legacy_anagrafica_id=legacy_id)
    if not qs.exists():
        return {}

    # Per ogni tipo, prendiamo data massima e poi recuperiamo l'oggetto con
    # quella data; nei rari casi di pareggio teniamo il pk più alto.
    max_per_tipo = (
        qs.values("tipo_id")
        .annotate(max_data=Max("data_svolgimento"))
    )
    out: dict[int, VisitaMedica] = {}
    for row in max_per_tipo:
        candidate = (
            qs.filter(tipo_id=row["tipo_id"], data_svolgimento=row["max_data"])
            .order_by("-pk")
            .select_related("tipo")
            .first()
        )
        if candidate:
            out[row["tipo_id"]] = candidate
    return out


def stato_visite(legacy_id: int, soglia_giorni_avviso: int = 60) -> list[dict[str, Any]]:
    """Ritorna lo stato delle visite richieste dal ruolo del dipendente.

    Ogni elemento ha forma::

        {
            "tipo": TipoVisitaMedica,
            "ultima": VisitaMedica | None,
            "data_scadenza": date | None,
            "stato": "mancante" | "valida" | "in_scadenza" | "scaduta",
            "giorni_a_scadenza": int | None,
        }
    """
    tipi = tipi_visita_richiesti_per_dipendente(legacy_id)
    if not tipi:
        return []
    ultime = ultime_visite_per_tipo(legacy_id)
    oggi = timezone.localdate()
    out: list[dict[str, Any]] = []
    for tipo in tipi:
        ultima = ultime.get(tipo.id)
        if ultima is None:
            out.append({
                "tipo": tipo,
                "ultima": None,
                "data_scadenza": None,
                "stato": STATO_MANCANTE,
                "giorni_a_scadenza": None,
            })
            continue
        scadenza = ultima.data_scadenza
        if scadenza is None:
            stato = STATO_VALIDA
            giorni = None
        else:
            giorni = (scadenza - oggi).days
            if giorni < 0:
                stato = STATO_SCADUTA
            elif giorni <= soglia_giorni_avviso:
                stato = STATO_IN_SCADENZA
            else:
                stato = STATO_VALIDA
        out.append({
            "tipo": tipo,
            "ultima": ultima,
            "data_scadenza": scadenza,
            "stato": stato,
            "giorni_a_scadenza": giorni,
        })
    return out


def visite_storico(legacy_id: int) -> list[VisitaMedica]:
    """Storico completo delle visite del dipendente, più recenti prima."""
    return completa_referti_visite(
        VisitaMedica.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .select_related("tipo", "referto_documento")
        .order_by("-data_svolgimento", "-id")
    )


def ultime_visite_correnti_ids(
    legacy_ids: Iterable[int] | None = None,
    tipo_ids: Iterable[int] | None = None,
    includi_cessati: bool = False,
) -> set[int]:
    """Id delle ``VisitaMedica`` **correnti**: l'ultima per coppia
    ``(legacy_anagrafica_id, famiglia)``.

    La famiglia è ``TipoVisitaMedica.categoria`` quando valorizzata (es.
    «Visita medica» annuale/biennale/quinquennale: cambiando mansione cambia la
    periodicità, ma la visita nuova supera la vecchia), altrimenti il tipo
    stesso. Massima ``data_svolgimento``, a parità di data vince il ``pk`` più
    alto. Le righe storiche superate NON sono "correnti": una scadenza superata
    da una visita più recente non deve più comparire come scaduta in nessuna
    vista. Le visite segnate a mano come superate (``superata_il``) non sono
    mai correnti, e non restituiscono il posto alle precedenti.

    I dipendenti cessati (``data_cessazione`` valorizzata) sono esclusi: le loro
    scadenze sono congelate, non cancellate — le visite restano nel libretto e
    tornano correnti se la persona viene rimessa in forza.

    SQL Server-safe: niente window function, due query in tutto.
    """
    famiglia_di_tipo = {
        pk: (f"cat:{categoria.strip().lower()}" if (categoria or "").strip() else f"tipo:{pk}")
        for pk, categoria in TipoVisitaMedica.objects.values_list("id", "categoria")
    }
    qs = VisitaMedica.objects.all()
    if legacy_ids is not None:
        qs = qs.filter(legacy_anagrafica_id__in=list(legacy_ids))
    if not includi_cessati:
        qs = qs.exclude(legacy_anagrafica_id__in=DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=False,
        ).values("legacy_anagrafica_id"))
    tipi_richiesti = None
    if tipo_ids is not None:
        # Il filtro per tipo va allargato alla famiglia, altrimenti una visita
        # superata da un tipo fratello tornerebbe "corrente".
        tipi_richiesti = set(tipo_ids)
        famiglie = {famiglia_di_tipo.get(t) for t in tipi_richiesti}
        qs = qs.filter(tipo_id__in=[t for t, f in famiglia_di_tipo.items() if f in famiglie])

    correnti: dict[tuple[int, str], tuple] = {}
    for pk, lid, tid, data, superata in qs.order_by().values_list(
        "id", "legacy_anagrafica_id", "tipo_id", "data_svolgimento", "superata_il"
    ):
        chiave = (lid, famiglia_di_tipo.get(tid, f"tipo:{tid}"))
        prev = correnti.get(chiave)
        if prev is None or (data, pk) > (prev[0], prev[1]):
            correnti[chiave] = (data, pk, tid, superata)
    return {
        pk for _data, pk, tid, superata in correnti.values()
        if superata is None and (tipi_richiesti is None or tid in tipi_richiesti)
    }
