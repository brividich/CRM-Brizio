"""Fascicolo di conformità dipendente — "è in regola con la sua mansione?".

Aggrega in un semaforo unico quattro domini già gestiti dai rispettivi moduli:

- **Formazione obbligatoria** e **visite mediche**: dal motore unico
  ``services.requisiti`` (requisiti da mansione e rischi, area, ruoli operativi,
  regole in vigore, protocollo sanitario, processi MOD.128; stato alla data;
  visite per famiglia con il ricalcolo prudente della periodicita'). Prima la
  formazione leggeva la cache ``TrainingDeadline`` mai ricalcolata e le visite
  solo i ruoli operativi, valutate per tipo.
- **Qualifiche professionali**: qualifica corrente per persona e tipo.
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
from ..models import DipendenteQualifica, VisitaMedica

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


def _persone(legacy_ids: list[int], mansioni_per_legacy: dict[int, str] | None = None):
    """(contesto, ``{id richiesto: Dipendente}``) dal motore unico.

    Gli id richiesti vengono ricondotti alla persona (anagrafiche doppie). Con
    ``mansioni_per_legacy`` si simula un'altra mansione (cambio mansione): i
    requisiti seguono la mansione indicata, il resto resta quello della persona.
    """
    from dataclasses import replace

    from anagrafica.reportistica.dati import Dipendente

    from . import requisiti

    ctx = requisiti.ambito()
    tutti = {d.id: d for d in ctx._tutti()}
    out = {}
    for lid in legacy_ids:
        pid = ctx.canonico(lid)
        persona = tutti.get(pid) or Dipendente(id=pid, nominativo=f"Dipendente #{pid}")
        if mansioni_per_legacy and lid in mansioni_per_legacy:
            persona = replace(persona, mansione=(mansioni_per_legacy.get(lid) or "").strip())
        out[lid] = persona
    return ctx, out


def _per_persona(voci, richiesti: dict) -> dict[int, list]:
    """Voci del motore raggruppate per id richiesto (piu' id possono puntare alla stessa persona)."""
    per_pid: dict[int, list] = {}
    for v in voci:
        per_pid.setdefault(v.persona, []).append(v)
    return {lid: per_pid.get(p.id, []) for lid, p in richiesti.items()}


def _voci_formazione(ctx, richiesti: dict) -> dict[int, list]:
    from . import requisiti

    persone = {p.id: p for p in richiesti.values()}
    return _per_persona([v for v in requisiti.formazione(ctx, persone) if v.obbligatorio], richiesti)


def _voci_visite(ctx, richiesti: dict) -> dict[int, list]:
    from . import requisiti

    persone = {p.id: p for p in richiesti.values()}
    return _per_persona([v for v in requisiti.visite(ctx, persone) if v.richiesta], richiesti)


def _formazione_batch(legacy_ids: list[int], voci: dict[int, list] | None = None) -> dict[int, dict[str, Any]]:
    if voci is None:
        ctx, richiesti = _persone(legacy_ids)
        voci = _voci_formazione(ctx, richiesti)
    out: dict[int, dict[str, Any]] = {}
    for legacy_id, elenco in voci.items():
        if not elenco:
            continue
        esiti, dettagli = [], []
        for v in elenco:
            if v.stato == "SCADUTO":
                esiti.append(ESITO_KO)
                dettagli.append(f"{v.corso.titolo}: scaduto")
            elif v.stato == "MAI_FREQUENTATO":
                # Mai frequentato = dato non registrato, non non-conformità.
                esiti.append(ESITO_NA)
            elif v.stato in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
                esiti.append(ESITO_WARN)
                dettagli.append(f"{v.corso.titolo}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _ultime_visite_map(legacy_ids: list[int]) -> dict[tuple[int, int], VisitaMedica]:
    """Ultima ``VisitaMedica`` per ``(legacy_id, tipo_id)`` — 1 query (usata dai DPI/altri chiamanti)."""
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


def _visite_batch(legacy_ids: list[int], include_dettaglio: bool,
                  voci: dict[int, list] | None = None) -> dict[int, dict[str, Any]]:
    """Visite dovute per persona dal motore unico (per famiglia, scadenza effettiva)."""
    oggi = timezone.localdate()
    if voci is None:
        ctx, richiesti = _persone(legacy_ids)
        voci = _voci_visite(ctx, richiesti)
    out: dict[int, dict[str, Any]] = {}
    for legacy_id, elenco in voci.items():
        if not elenco:
            continue
        esiti, dettagli = [], []
        for v in elenco:
            etichetta = v.tipo_da_mostrare.nome if include_dettaglio else "Visita richiesta"
            if v.ultima is None:
                # Visita mai registrata = dato mancante, non scaduto.
                esiti.append(ESITO_NA)
            elif v.scadenza is None:
                esiti.append(ESITO_OK)
            elif v.scadenza < oggi:
                esiti.append(ESITO_KO)
                dettagli.append(f"{etichetta}: scaduta")
            elif (v.scadenza - oggi).days <= SOGLIA_WARN_GIORNI:
                esiti.append(ESITO_WARN)
                dettagli.append(f"{etichetta}: in scadenza")
            else:
                esiti.append(ESITO_OK)
        out[legacy_id] = _dominio(_peggiore(esiti), dettagli)
    return out


def _qualifiche_batch(legacy_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Qualifica corrente per persona e tipo: una qualifica rinnovata non lascia la vecchia «scaduta»."""
    from . import requisiti

    oggi = timezone.localdate()
    soglia = oggi + timedelta(days=SOGLIA_WARN_GIORNI)
    ctx, richiesti = _persone(legacy_ids)
    persone = {p.id: p for p in richiesti.values()}
    correnti, _sostituite = requisiti.qualifiche_correnti(ctx, DipendenteQualifica.objects.all(), persone)
    per_pid: dict[int, list] = {}
    for (pid, _tipo), q in correnti.items():
        per_pid.setdefault(pid, []).append(q)
    out: dict[int, dict[str, Any]] = {}
    for legacy_id, persona in richiesti.items():
        qualifiche = per_pid.get(persona.id)
        if not qualifiche:
            continue
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
    """Idoneità alla mansione: requisiti della mansione (anche solo ipotizzata) vs posseduti.

    Corsi e visite dal motore unico calcolato **sulla mansione indicata** (requisiti
    da mansione e rischi, area, ruoli, regole, protocollo, processi); DPI dalla
    mansione e dai processi come prima.

    - requisito **mancante** (mai registrato) → WARN (avviso, da soddisfare);
    - requisito **scaduto** → KO;
    - requisito valido (o in scadenza) → OK (o WARN).

    Verdetto = peggiore; nessuna mansione / nessun requisito → NA.
    Privacy visite: nessun esito/prescrizione, solo lo stato; etichetta col nome
    tipologia solo se ``include_visite_dettaglio``.
    """
    oggi = timezone.localdate()
    ctx, richiesti = _persone(legacy_ids, mansioni_per_legacy)
    corsi = _voci_formazione(ctx, richiesti)
    visite = _voci_visite(ctx, richiesti)

    # DPI: mansione + processi qualificati (stesso resolver di prima).
    req_dpi_nome = mansionario.requisiti_per_nome({p.mansione for p in richiesti.values() if p.mansione})
    try:
        from .mpq_idoneita import requisiti_processo_per_legacy
        proc_req = requisiti_processo_per_legacy(legacy_ids)
    except Exception:
        proc_req = {}
    dpi_req: dict[int, list] = {}
    for legacy_id, persona in richiesti.items():
        voci_dpi = list((req_dpi_nome.get(persona.mansione.casefold()) or {}).get("dpi") or [])
        voci_dpi += list((proc_req.get(legacy_id) or {}).get("dpi") or [])
        visti, unici = set(), []
        for categoria in voci_dpi:
            if categoria.pk not in visti:
                visti.add(categoria.pk)
                unici.append(categoria)
        dpi_req[legacy_id] = unici
    consegne = _consegne_dpi_map([lid for lid, v in dpi_req.items() if v]) or {}

    out: dict[int, dict[str, Any]] = {}
    for legacy_id in richiesti:
        if not (dpi_req.get(legacy_id) or corsi.get(legacy_id) or visite.get(legacy_id)):
            continue
        esiti: list[str] = []
        mancanti: list[str] = []
        scaduti: list[str] = []

        for categoria in dpi_req.get(legacy_id, []):
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

        for v in visite.get(legacy_id, []):
            etichetta = v.tipo_da_mostrare.nome if include_visite_dettaglio else "Visita richiesta"
            if v.ultima is None:
                esiti.append(ESITO_WARN)
                mancanti.append(f"Visita: {etichetta}")
            elif v.scadenza is None:
                esiti.append(ESITO_OK)
            elif v.scadenza < oggi:
                esiti.append(ESITO_KO)
                scaduti.append(f"Visita: {etichetta}")
            elif (v.scadenza - oggi).days <= SOGLIA_WARN_GIORNI:
                esiti.append(ESITO_WARN)
            else:
                esiti.append(ESITO_OK)

        for v in corsi.get(legacy_id, []):
            if v.stato == "MAI_FREQUENTATO":
                esiti.append(ESITO_WARN)
                mancanti.append(f"Corso: {v.corso.titolo}")
            elif v.stato == "SCADUTO":
                esiti.append(ESITO_KO)
                scaduti.append(f"Corso: {v.corso.titolo}")
            elif v.stato in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
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

    # Un solo calcolo del motore per formazione e visite, condiviso dai due domini.
    ctx, richiesti = _persone(legacy_ids)
    formazione = _formazione_batch(legacy_ids, _voci_formazione(ctx, richiesti))
    visite = _visite_batch(legacy_ids, include_visite_dettaglio, _voci_visite(ctx, richiesti))
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
