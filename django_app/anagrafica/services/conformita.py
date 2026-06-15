"""Fascicolo di conformità dipendente — "è in regola con la sua mansione?".

Aggrega in un semaforo unico quattro domini già gestiti dai rispettivi moduli:

- **Formazione obbligatoria**: cache ``TrainingDeadline`` (``is_required=True``).
- **Visite mediche**: stesse regole di ``services.visite.stato_visite`` ma in
  versione batch (le visite richieste derivano dai ruoli operativi).
- **Qualifiche professionali**: ``DipendenteQualifica`` con scadenza.
- **DPI**: consegne per categoria obbligatoria da mansionario (stessa logica
  del report conformità del modulo ``dpi``; import difensivo, il modulo può
  non essere migrato in dev).

Esiti per dominio: ``ok`` / ``warn`` (in scadenza) / ``ko`` (record esistente
e scaduto) / ``na`` (nessun requisito **oppure** dato non ancora registrato).
Il semaforo complessivo è il peggiore dei domini applicabili.

Nota (dipendenti già in forza): un requisito **mai registrato** (visita/DPI/
corso assente) NON è una non conformità — è un dato che sarà popolato in
seguito; per i nuovi ingressi l'adempimento è guidato dalla pratica di
onboarding. Perciò il "mancante" vale ``na`` (neutro), mentre solo un record
realmente scaduto vale ``ko``.

Privacy: per le visite mediche i dettagli (nomi tipologia) sono inclusi solo
se ``include_visite_dettaglio=True`` — il chiamante deve passarci l'esito di
``_can_view_visite_mediche``. Esito e prescrizioni non sono MAI esposti qui.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

from django.utils import timezone

from . import mansionario
from ..models import DipendenteQualifica, DipendenteRuoloOperativo, TipoVisitaMedica, VisitaMedica
from ..models_formazione import TrainingDeadline

ESITO_OK = "ok"
ESITO_WARN = "warn"
ESITO_KO = "ko"
ESITO_NA = "na"

_PESO = {ESITO_NA: 0, ESITO_OK: 1, ESITO_WARN: 2, ESITO_KO: 3}

SOGLIA_WARN_GIORNI = 60


def _peggiore(esiti: Iterable[str]) -> str:
    esiti = list(esiti)
    if not esiti:
        return ESITO_NA
    return max(esiti, key=lambda e: _PESO.get(e, 0))


def _dominio(esito: str, dettagli: list[str]) -> dict[str, Any]:
    return {"esito": esito, "dettagli": dettagli}


def _formazione_batch(legacy_ids: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    per_dip: dict[int, list[TrainingDeadline]] = {}
    qs = (
        TrainingDeadline.objects
        .filter(is_required=True, legacy_anagrafica_id__in=legacy_ids)
        .select_related("corso")
    )
    for d in qs:
        per_dip.setdefault(d.legacy_anagrafica_id, []).append(d)

    for legacy_id, deadlines in per_dip.items():
        esiti, dettagli = [], []
        for d in deadlines:
            if d.stato_scadenza == "SCADUTO":
                esiti.append(ESITO_KO)
                dettagli.append(f"{d.corso.titolo}: scaduto")
            elif d.stato_scadenza == "MAI_FREQUENTATO":
                # Mai frequentato = dato non registrato, non non-conformità.
                esiti.append(ESITO_NA)
            elif d.stato_scadenza in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
                esiti.append(ESITO_WARN)
                dettagli.append(f"{d.corso.titolo}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _ultime_visite_map(legacy_ids: list[int]) -> dict[tuple[int, int], VisitaMedica]:
    """Ultima ``VisitaMedica`` per ``(legacy_id, tipo_id)`` — 1 query."""
    ultima: dict[tuple[int, int], VisitaMedica] = {}
    for visita in (
        VisitaMedica.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .order_by("-data_svolgimento", "-pk")
    ):
        ultima.setdefault((visita.legacy_anagrafica_id, visita.tipo_id), visita)
    return ultima


def _consegne_dpi_map(legacy_ids: list[int]) -> dict[tuple[int, int], Any] | None:
    """Consegna DPI più recente per ``(legacy_id, categoria_id)`` — 1 query.

    Ritorna ``None`` se il modulo ``dpi`` non è disponibile/migrato.
    """
    try:
        from dpi.models import ConsegnaDPI, StatoRichiesta
    except Exception:
        return None
    consegna_per_dip_cat: dict[tuple[int, int], Any] = {}
    for consegna in (
        ConsegnaDPI.objects
        .filter(
            richiesta__richiedente_legacy_id__in=legacy_ids,
            richiesta__stato=StatoRichiesta.CONSEGNATA,
        )
        .select_related("richiesta")
        .order_by("-data_consegna", "-created_at")
    ):
        key = (consegna.richiesta.richiedente_legacy_id, consegna.richiesta.categoria_id)
        consegna_per_dip_cat.setdefault(key, consegna)
    return consegna_per_dip_cat


def _visite_batch(legacy_ids: list[int], include_dettaglio: bool) -> dict[int, dict[str, Any]]:
    """Versione batch delle regole di ``stato_visite`` (4 query totali)."""
    oggi = timezone.localdate()

    ruoli_per_dip: dict[int, set[int]] = {}
    for legacy_id, ruolo_id in (
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .values_list("legacy_anagrafica_id", "ruolo_id")
    ):
        ruoli_per_dip.setdefault(legacy_id, set()).add(ruolo_id)

    tipi_per_ruolo: dict[int, list[TipoVisitaMedica]] = {}
    for tipo in (
        TipoVisitaMedica.objects
        .filter(is_active=True, obbligatoria=True)
        .prefetch_related("ruoli_operativi")
    ):
        for ruolo in tipo.ruoli_operativi.all():
            tipi_per_ruolo.setdefault(ruolo.id, []).append(tipo)

    ultima_per_dip_tipo = _ultime_visite_map(legacy_ids)

    out: dict[int, dict[str, Any]] = {}
    for legacy_id, ruoli in ruoli_per_dip.items():
        tipi_richiesti: dict[int, TipoVisitaMedica] = {}
        for ruolo_id in ruoli:
            for tipo in tipi_per_ruolo.get(ruolo_id, []):
                tipi_richiesti[tipo.id] = tipo
        if not tipi_richiesti:
            continue
        esiti, dettagli = [], []
        for tipo in tipi_richiesti.values():
            etichetta = tipo.nome if include_dettaglio else "Visita richiesta"
            ultima = ultima_per_dip_tipo.get((legacy_id, tipo.id))
            if ultima is None:
                # Visita mai registrata = dato mancante, non scaduto.
                esiti.append(ESITO_NA)
            elif ultima.data_scadenza is None:
                esiti.append(ESITO_OK)
            elif ultima.data_scadenza < oggi:
                esiti.append(ESITO_KO)
                dettagli.append(f"{etichetta}: scaduta")
            elif (ultima.data_scadenza - oggi).days <= SOGLIA_WARN_GIORNI:
                esiti.append(ESITO_WARN)
                dettagli.append(f"{etichetta}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _qualifiche_batch(legacy_ids: list[int]) -> dict[int, dict[str, Any]]:
    oggi = timezone.localdate()
    soglia = oggi + timedelta(days=SOGLIA_WARN_GIORNI)
    out: dict[int, dict[str, Any]] = {}
    per_dip: dict[int, list[DipendenteQualifica]] = {}
    for q in (
        DipendenteQualifica.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .select_related("tipo")
    ):
        per_dip.setdefault(q.legacy_anagrafica_id, []).append(q)

    for legacy_id, qualifiche in per_dip.items():
        esiti, dettagli = [], []
        for q in qualifiche:
            if q.data_scadenza is None:
                esiti.append(ESITO_OK)
            elif q.data_scadenza < oggi:
                esiti.append(ESITO_KO)
                dettagli.append(f"{q.tipo.nome}: scaduta")
            elif q.data_scadenza <= soglia:
                esiti.append(ESITO_WARN)
                dettagli.append(f"{q.tipo.nome}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _dpi_batch(legacy_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Conformità DPI: categoria obbligatoria da mansionario → consegna valida.

    Stessa logica del report conformità del modulo ``dpi`` (consegna più
    recente per categoria; scaduta se ``data_scadenza_stimata`` passata).
    """
    try:
        from dpi.models import CategoriaDPI
    except Exception:
        return {}

    categorie = list(
        CategoriaDPI.objects.filter(is_active=True, obbligatoria_mansionario=True)
        .order_by("order_index", "nome")
    )
    if not categorie:
        return {}

    consegna_per_dip_cat = _consegne_dpi_map(legacy_ids)
    if consegna_per_dip_cat is None:
        return {}

    oggi = timezone.localdate()
    out: dict[int, dict[str, Any]] = {}
    for legacy_id in legacy_ids:
        esiti, dettagli = [], []
        for categoria in categorie:
            consegna = consegna_per_dip_cat.get((legacy_id, categoria.pk))
            if consegna is None:
                # DPI mai consegnato = dato mancante, non scaduto.
                esiti.append(ESITO_NA)
            elif consegna.data_scadenza_stimata and consegna.data_scadenza_stimata < oggi:
                esiti.append(ESITO_KO)
                dettagli.append(f"{categoria.nome}: scaduto")
            elif (
                consegna.data_scadenza_stimata
                and (consegna.data_scadenza_stimata - oggi).days <= SOGLIA_WARN_GIORNI
            ):
                esiti.append(ESITO_WARN)
                dettagli.append(f"{categoria.nome}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _idoneita_vuota() -> dict[str, Any]:
    return {"esito": ESITO_NA, "mancanti": [], "scaduti": []}


def _idoneita_batch(
    legacy_ids: list[int],
    mansioni_per_legacy: dict[int, str],
    *,
    include_visite_dettaglio: bool,
) -> dict[int, dict[str, Any]]:
    """Idoneità alla mansione: requisiti della "mansione di rischio" vs posseduti.

    Per i domini DPI / visite / formazione confronta i requisiti risolti dalla
    mansione del dipendente (``services.mansionario``) con i record effettivi:

    - requisito **mancante** (mai registrato) → WARN (avviso, da soddisfare);
    - requisito **scaduto** → KO;
    - requisito valido (o in scadenza) → OK (o WARN).

    Verdetto = peggiore; nessuna mansione / nessun requisito → NA.
    Privacy visite: nessun esito/prescrizione, solo lo stato; etichetta col nome
    tipologia solo se ``include_visite_dettaglio``.
    """
    oggi = timezone.localdate()

    req_per_nome = mansionario.requisiti_per_nome(set(mansioni_per_legacy.values()))
    if not req_per_nome:
        return {}

    req_per_legacy: dict[int, dict[str, list]] = {}
    for legacy_id in legacy_ids:
        nome = (mansioni_per_legacy.get(legacy_id) or "").strip().casefold()
        req = req_per_nome.get(nome)
        if req and (req["dpi"] or req["visite"] or req["corsi"]):
            req_per_legacy[legacy_id] = req
    if not req_per_legacy:
        return {}

    coinvolti = list(req_per_legacy.keys())
    consegne = _consegne_dpi_map(coinvolti) or {}
    ultime_visite = _ultime_visite_map(coinvolti)

    corso_ids = {c.pk for req in req_per_legacy.values() for c in req["corsi"]}
    deadline_per_dip_corso: dict[tuple[int, int], TrainingDeadline] = {}
    if corso_ids:
        for d in (
            TrainingDeadline.objects
            .filter(legacy_anagrafica_id__in=coinvolti, corso_id__in=corso_ids)
        ):
            deadline_per_dip_corso[(d.legacy_anagrafica_id, d.corso_id)] = d

    out: dict[int, dict[str, Any]] = {}
    for legacy_id, req in req_per_legacy.items():
        esiti: list[str] = []
        mancanti: list[str] = []
        scaduti: list[str] = []

        for categoria in req["dpi"]:
            consegna = consegne.get((legacy_id, categoria.pk))
            if consegna is None:
                esiti.append(ESITO_WARN)
                mancanti.append(f"DPI: {categoria.nome}")
            elif consegna.data_scadenza_stimata and consegna.data_scadenza_stimata < oggi:
                esiti.append(ESITO_KO)
                scaduti.append(f"DPI: {categoria.nome}")
            elif (
                consegna.data_scadenza_stimata
                and (consegna.data_scadenza_stimata - oggi).days <= SOGLIA_WARN_GIORNI
            ):
                esiti.append(ESITO_WARN)
            else:
                esiti.append(ESITO_OK)

        for tipo in req["visite"]:
            etichetta = tipo.nome if include_visite_dettaglio else "Visita richiesta"
            ultima = ultime_visite.get((legacy_id, tipo.pk))
            if ultima is None:
                esiti.append(ESITO_WARN)
                mancanti.append(f"Visita: {etichetta}")
            elif ultima.data_scadenza is None:
                esiti.append(ESITO_OK)
            elif ultima.data_scadenza < oggi:
                esiti.append(ESITO_KO)
                scaduti.append(f"Visita: {etichetta}")
            elif (ultima.data_scadenza - oggi).days <= SOGLIA_WARN_GIORNI:
                esiti.append(ESITO_WARN)
            else:
                esiti.append(ESITO_OK)

        for corso in req["corsi"]:
            d = deadline_per_dip_corso.get((legacy_id, corso.pk))
            if d is None or d.stato_scadenza == "MAI_FREQUENTATO":
                esiti.append(ESITO_WARN)
                mancanti.append(f"Corso: {corso.titolo}")
            elif d.stato_scadenza == "SCADUTO":
                esiti.append(ESITO_KO)
                scaduti.append(f"Corso: {corso.titolo}")
            elif d.stato_scadenza in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
                esiti.append(ESITO_WARN)
            else:
                esiti.append(ESITO_OK)

        out[legacy_id] = {
            "esito": _peggiore(esiti),
            "mancanti": mancanti,
            "scaduti": scaduti,
        }
    return out


def stato_conformita_batch(
    legacy_ids: list[int],
    *,
    include_visite_dettaglio: bool = False,
    mansioni_per_legacy: dict[int, str] | None = None,
) -> dict[int, dict[str, Any]]:
    """Stato conformità per più dipendenti con un numero costante di query.

    Ritorna ``{legacy_id: {"complessivo": esito, "idoneita": {...},
    "formazione": {...}, "visite": {...}, "qualifiche": {...}, "dpi": {...}}}``.
    I dipendenti senza alcun requisito in nessun dominio hanno complessivo "na".

    Se ``mansioni_per_legacy`` (``{legacy_id: nome_mansione}``) è passato, viene
    calcolata anche la lente ``idoneita`` (requisiti della mansione di rischio vs
    posseduti); altrimenti ``idoneita`` resta "na".
    """
    legacy_ids = [int(i) for i in legacy_ids if int(i or 0) > 0]
    if not legacy_ids:
        return {}

    formazione = _formazione_batch(legacy_ids)
    visite = _visite_batch(legacy_ids, include_visite_dettaglio)
    qualifiche = _qualifiche_batch(legacy_ids)
    dpi = _dpi_batch(legacy_ids)
    idoneita = (
        _idoneita_batch(
            legacy_ids, mansioni_per_legacy,
            include_visite_dettaglio=include_visite_dettaglio,
        )
        if mansioni_per_legacy else {}
    )

    na = _dominio(ESITO_NA, [])
    na_idoneita = _idoneita_vuota()
    out: dict[int, dict[str, Any]] = {}
    for legacy_id in legacy_ids:
        domini = {
            "formazione": formazione.get(legacy_id, na),
            "visite": visite.get(legacy_id, na),
            "qualifiche": qualifiche.get(legacy_id, na),
            "dpi": dpi.get(legacy_id, na),
        }
        complessivo = _peggiore(
            d["esito"] for d in domini.values() if d["esito"] != ESITO_NA
        )
        out[legacy_id] = {
            "complessivo": complessivo,
            "idoneita": idoneita.get(legacy_id, na_idoneita),
            **domini,
        }
    return out


def stato_conformita(
    legacy_id: int,
    *,
    include_visite_dettaglio: bool = False,
    mansione: str | None = None,
) -> dict[str, Any]:
    """Stato conformità di un singolo dipendente (wrapper del batch)."""
    mansioni = {int(legacy_id): mansione} if mansione else None
    return stato_conformita_batch(
        [legacy_id],
        include_visite_dettaglio=include_visite_dettaglio,
        mansioni_per_legacy=mansioni,
    ).get(int(legacy_id), {
        "complessivo": ESITO_NA,
        "idoneita": _idoneita_vuota(),
        "formazione": _dominio(ESITO_NA, []),
        "visite": _dominio(ESITO_NA, []),
        "qualifiche": _dominio(ESITO_NA, []),
        "dpi": _dominio(ESITO_NA, []),
    })
