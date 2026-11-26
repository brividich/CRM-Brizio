"""Motore di idoneità candidati alla formazione — NOVICROM HUB.

Risponde alla domanda: «chi ha senso (ri)formare per questo corso, e chi soddisfa
i requisiti per esservi iscritto?». È il cuore delle "regole non visibili" della
sezione formazione e generalizza ``views._candidati_rinnovo_corso``.

Per un corso (ed eventualmente una sessione/edizione) calcola, in poche query batch:

- **pertinenza** — chi è *tenuto* al corso secondo il motore dei requisiti
  (``services.requisiti.requisiti_formazione``: mansione e fattori di rischio, esposizioni,
  regole di obbligo in vigore, ruoli, aree, piani, processi MOD.128, «Obbligatorio per tutti»);
- **stato** dalla regola unica persona × corso (``formazione_completamento.stati_persona_corso``);
- **prerequisiti** (soft): prerequisiti ``obbligatorio=True`` non ancora completati
  (nessun :class:`TrainingEmployeeRecord` idoneo) → il candidato resta proponibile ma
  in coda, *non idoneo*, con il motivo, e l'editor può forzare;
- **esclusioni**: cessati, chi è già a posto (corso ``VALIDO`` / una tantum), chi è già
  iscritto a *questa* edizione; **segnala** chi è già iscritto ad altra edizione aperta.

Se il corso non ha alcuna regola di obbligatorietà la pertinenza non è applicabile e il
pool degrada al comportamento storico (candidati da scadenza: scaduti / in scadenza /
mai frequentati), così la pagina iscritti resta utile anche senza regole configurate.

Niente effetti collaterali: il motore **legge** soltanto. NON modifica ``TrainingDeadline``
(quella resta una cache ricalcolata da ``services.training_deadline_service``).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from core import naming

# Stati scadenza che rendono un dipendente candidato (da (ri)formare).
STATI_RILEVANTI = ("SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO")
# Stati che indicano "già a posto" → escluso dai candidati.
STATI_GIA_VALIDO = ("VALIDO", "UNA_TANTUM")
# Stati pre-spuntati di default (rinnovo vero e proprio; il "mai frequentato" è un
# primo rilascio, incluso ma non pre-selezionato).
STATI_PRESELECT = ("SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90")

_ORDER = {"SCADUTO": 0, "IN_SCADENZA_30": 1, "IN_SCADENZA_90": 2, "MAI_FREQUENTATO": 3}


def _cessati_ids() -> set[int]:
    """``legacy_anagrafica_id`` dei cessati (ex dipendenti). Specchio di
    ``views._cessati_legacy_ids`` ma senza dipendere dal modulo views."""
    from ..models import DipendenteAnagraficaAziendale

    return {
        int(lid)
        for lid in DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
        if lid
    }


def _dipendenti_attivi() -> dict[int, dict[str, str]]:
    """``{legacy_id: {"nome", "mansione", "reparto"}}`` dei dipendenti in forza.

    Usa l'accessor canonico ``core.legacy_anagrafica.fetch_anagrafica_rows`` (stessa
    fonte usata in tutta l'app per la tabella legacy ``anagrafica_dipendenti``).
    """
    from core.legacy_anagrafica import fetch_anagrafica_rows

    cessati = _cessati_ids()
    out: dict[int, dict[str, str]] = {}
    for r in fetch_anagrafica_rows():
        try:
            lid = int(r.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if lid <= 0 or lid in cessati:
            continue
        if r.get("attivo", True) is False:
            continue
        cognome = (r.get("cognome") or "").strip()
        nome = (r.get("nome") or "").strip()
        out[lid] = {
            "nome": naming.nome_completo(nome, cognome) or f"#{lid}",
            "mansione": (r.get("mansione") or "").strip(),
            "reparto": (r.get("reparto") or "").strip(),
        }
    return out


def _persone_motore(dipendenti: dict[int, dict], ctx, oggi: date) -> dict:
    """Le persone di ``dipendenti`` (in forza) come le vuole il motore dei requisiti.

    Si usa la scheda del motore (mansione, area, id delle anagrafiche doppie); una persona che il
    motore non conosce (riga non leggibile) entra con la mansione dell'elenco. Gli id dei doppioni
    fusi restano fuori: li rappresenta l'id principale, così nessuno compare due volte."""
    from ..reportistica.dati import Dipendente

    tutti = {p.id: p for p in ctx._tutti()}
    alias = ctx._alias()
    persone = {}
    for lid, dati in dipendenti.items():
        if alias.get(lid, lid) != lid:
            continue
        p = tutti.get(lid)
        if p is None:
            p = Dipendente(id=lid, nominativo=(dati or {}).get("nome") or f"#{lid}",
                           mansione=((dati or {}).get("mansione") or "").strip())
        elif not p.in_forza_al(oggi):
            continue
        persone[lid] = p
    return persone


def _legacy_ids_pertinenti(corso, dipendenti: dict[int, dict], *, ctx=None,
                           oggi: date | None = None) -> tuple[set[int], bool]:
    """Insieme dei ``legacy_id`` *tenuti* al corso + flag ``has_rules``.

    Regola unica: il motore dei requisiti (``services.requisiti.requisiti_formazione``), lo
    stesso di scadenzario, conformità e cruscotto. Mansione e fattori di rischio, esposizioni,
    regole di obbligo in vigore (validità della regola, ruoli non chiusi, area, mansione
    lavorativa in lista, piano), processi MOD.128 e la spunta «Obbligatorio per tutti».
    Prima qui c'erano regole proprie (regole scadute, ruoli chiusi e doppioni contati).

    ``has_rules``: il corso è chiesto da qualcosa (anche se oggi non tocca nessuno in forza)."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingRequirementRule
    from . import requisiti

    oggi = oggi or timezone.localdate()
    ctx = ctx or requisiti.ambito(oggi)
    persone = _persone_motore(dipendenti, ctx, oggi)
    ids: set[int] = set()
    if persone:
        richiesti = requisiti.requisiti_formazione(ctx, persone)
        ids = {pid for pid, corsi in richiesti.items() if corso.pk in corsi}
    if ids or (getattr(corso, "obbligatorio", False) and getattr(corso, "is_active", True)):
        return ids, True
    cond = Q(corso=corso) | Q(piano_id=corso.piano_id) if corso.piano_id else Q(corso=corso)
    return ids, TrainingRequirementRule.objects.filter(cond, is_active=True, is_mandatory=True).exists()


def prerequisiti_mancanti(corso, legacy_id: int) -> list[str]:
    """Titoli dei prerequisiti ``obbligatorio=True`` del corso che ``legacy_id`` non
    ha mai completato (nessun :class:`TrainingEmployeeRecord` idoneo). Lista vuota =
    requisiti soddisfatti. Usato per l'enforcement *soft* in fase di iscrizione."""
    from ..models_formazione import TrainingCourseDependency, TrainingEmployeeRecord

    deps = list(
        TrainingCourseDependency.objects
        .filter(corso_principale=corso, obbligatorio=True)
        .select_related("prerequisito")
    )
    if not deps:
        return []
    fatti = set(
        TrainingEmployeeRecord.objects
        .filter(
            corso_id__in=[d.prerequisito_id for d in deps],
            legacy_anagrafica_id=legacy_id,
            idoneo=True,
        )
        .values_list("corso_id", flat=True)
    )
    return [d.prerequisito.titolo for d in deps if d.prerequisito_id not in fatti]


def candidati_corso(corso, *, sessione=None, oggi: date | None = None, ctx=None,
                    dipendenti: dict | None = None) -> dict[str, Any]:
    """Candidati alla (ri)formazione per ``corso``, divisi in ``idonei`` / ``non_idonei``.

    Ritorna un dict::

        {
          "idonei":      [voce, ...],   # proponibili, pre-spuntati se da rinnovare
          "non_idonei":  [voce, ...],   # in coda, disabilitati (prerequisiti mancanti)
          "pool_filtrato": bool,        # True se ristretto ai tenuti al corso
          "n_preselect": int,           # quanti idonei pre-selezionati
        }

    Ogni ``voce`` è::

        {legacy_id, nome, stato, stato_label, data_scadenza, idoneo,
         prerequisiti_mancanti: [titolo, ...], gia_iscritto_altrove: bool,
         warning: [str, ...], preselect: bool}

    Tenuti = motore dei requisiti (:func:`_legacy_ids_pertinenti`); lo stato viene dalla regola
    unica persona × corso (``formazione_completamento.stati_persona_corso``): Completato non in
    scadenza e Da registrare sono a posto; Completato entro la soglia di preavviso = in scadenza;
    Scaduto; tutto il resto da fare. Senza nessun tenuto restano i candidati da scadenza.
    ``ctx`` / ``dipendenti``: contesto e persone in forza già letti dal chiamante (facoltativi).
    """
    from django.utils import timezone

    from ..models_formazione import (
        TrainingCourseDependency,
        TrainingDeadline,
        TrainingEmployeeRecord,
        TrainingEnrollment,
        TrainingSession,
    )
    from ..scadenze_soglie import GIORNI_PREAVVISO, GIORNI_URGENTE
    from .formazione_completamento import COMPLETATO, DA_REGISTRARE, SCADUTO, stati_persona_corso

    oggi = oggi or timezone.localdate()
    dipendenti = _dipendenti_attivi() if dipendenti is None else dipendenti
    pertinenti, has_rules = _legacy_ids_pertinenti(corso, dipendenti, ctx=ctx, oggi=oggi)

    pool_filtrato = has_rules and bool(pertinenti)
    if pool_filtrato:
        base = set(pertinenti)
    else:
        # Nessun tenuto: degrada ai candidati da scadenza (cache e completamenti scaduti/in scadenza).
        base = {
            lid for lid, st in TrainingDeadline.objects.filter(corso=corso).values_list(
                "legacy_anagrafica_id", "stato_scadenza")
            if st in STATI_RILEVANTI and lid in dipendenti
        }
        soglia = oggi + timedelta(days=GIORNI_PREAVVISO)
        base |= {
            lid for lid in TrainingEmployeeRecord.objects.filter(
                corso=corso, idoneo=True, data_scadenza__isnull=False, data_scadenza__lte=soglia,
            ).values_list("legacy_anagrafica_id", flat=True)
            if lid in dipendenti
        }

    stati = stati_persona_corso(corso, base, oggi=oggi) if base else {}

    # Iscritti a questa edizione → esclusi.
    iscritti_sessione: set[int] = set()
    if sessione is not None:
        iscritti_sessione = set(
            TrainingEnrollment.objects.filter(sessione=sessione)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    # Iscritti ad altra edizione aperta dello stesso corso → segnalati (non esclusi).
    aperte = TrainingSession.objects.filter(
        corso=corso, stato__in=("PIANIFICATA", "IN_CORSO")
    )
    if sessione is not None:
        aperte = aperte.exclude(pk=sessione.pk)
    iscritti_altrove = set(
        TrainingEnrollment.objects.filter(sessione__in=aperte)
        .values_list("legacy_anagrafica_id", flat=True)
    )

    # Prerequisiti obbligatori del corso e chi li ha completati (almeno una volta).
    prereq_deps = list(
        TrainingCourseDependency.objects
        .filter(corso_principale=corso, obbligatorio=True)
        .select_related("prerequisito")
    )
    prereq_ids = [d.prerequisito_id for d in prereq_deps]
    prereq_titoli = {d.prerequisito_id: d.prerequisito.titolo for d in prereq_deps}
    completati_prereq: dict[int, set[int]] = {}
    if prereq_ids and base:
        for lid, cid in (
            TrainingEmployeeRecord.objects
            .filter(corso_id__in=prereq_ids, legacy_anagrafica_id__in=base, idoneo=True)
            .values_list("legacy_anagrafica_id", "corso_id")
        ):
            completati_prereq.setdefault(lid, set()).add(cid)

    idonei: list[dict] = []
    non_idonei: list[dict] = []
    for lid in base:
        if lid in iscritti_sessione:
            continue
        emp = dipendenti.get(lid)
        if emp is None:
            continue
        st = stati.get(lid)
        data_scadenza = None
        if st is not None and st.codice == DA_REGISTRARE:
            continue  # verifica superata: va registrata, non riassegnata
        if st is not None and st.codice == COMPLETATO:
            data_scadenza = st.record.data_scadenza if st.record is not None else None
            if data_scadenza is None:
                continue  # completato una tantum: a posto
            giorni = (data_scadenza - oggi).days
            if giorni > GIORNI_PREAVVISO:
                continue  # valido e non in scadenza: a posto
            stato = "IN_SCADENZA_30" if giorni <= GIORNI_URGENTE else "IN_SCADENZA_90"
            stato_label = "In scadenza"
        elif st is not None and st.codice == SCADUTO:
            stato, stato_label = "SCADUTO", "Scaduto"
            data_scadenza = st.data
        else:
            stato = "MAI_FREQUENTATO"
            dettaglio = st.etichetta if st is not None else ""
            stato_label = dettaglio if dettaglio and dettaglio != "Da fare" else "Mai frequentato"

        mancanti: list[str] = []
        if prereq_ids:
            fatti = completati_prereq.get(lid, set())
            mancanti = [prereq_titoli[pid] for pid in prereq_ids if pid not in fatti]
        idoneo = not mancanti

        gia_altrove = lid in iscritti_altrove
        warning: list[str] = []
        if gia_altrove:
            warning.append("Già iscritto ad altra edizione aperta")

        voce = {
            "legacy_id": lid,
            "nome": (emp or {}).get("nome") or f"#{lid}",
            "stato": stato,
            "stato_label": stato_label,
            "data_scadenza": data_scadenza,
            "idoneo": idoneo,
            "prerequisiti_mancanti": mancanti,
            "gia_iscritto_altrove": gia_altrove,
            "warning": warning,
            "preselect": idoneo and not gia_altrove and stato in STATI_PRESELECT,
        }
        (idonei if idoneo else non_idonei).append(voce)

    idonei.sort(key=lambda c: (_ORDER.get(c["stato"], 9), c["nome"].casefold()))
    non_idonei.sort(key=lambda c: c["nome"].casefold())

    return {
        "idonei": idonei,
        "non_idonei": non_idonei,
        "pool_filtrato": pool_filtrato,
        "n_preselect": sum(1 for c in idonei if c["preselect"]),
    }


def righe_gap_formativo(
    *, filtro_reparto: str = "", filtro_corso: str = "", filtro_stato: str = "", info: dict | None = None,
) -> tuple[list, list[str], list[dict]]:
    """Una riga per (dipendente in forza, corso obbligatorio) non in regola: scaduto, in scadenza o
    mai frequentato. Condivisa da `views.formazione_copertura` e dal suo export.

    «Obbligatorio» ha una definizione sola: quella del motore dei requisiti
    (``services.requisiti.formazione``), che unisce mansione, fattori di rischio, esposizioni, regole di
    obbligo e processi MOD.128 — la stessa di scadenzario, cruscotto HR e conformità. Prima la pagina
    leggeva solo le regole di obbligo (in produzione nessuna) e restava vuota (analisi 26/11/2026).

    ``info`` (facoltativo) riceve ``n_obblighi``: quante coppie persona × corso obbligatorio il motore
    trova in tutto. Zero vuol dire «nessun obbligo configurato», non «tutti in regola»."""
    from django.utils import timezone

    from ..models_formazione import TrainingDeadline
    from . import requisiti

    etichette = dict(TrainingDeadline.STATO_SCADENZA_CHOICES)
    etichette.setdefault("MAI_FREQUENTATO", "Mai frequentato")
    oggi = timezone.localdate()
    ctx = requisiti.ambito(oggi)
    persone = {p.id: p for p in ctx._tutti() if p.in_forza_al(oggi)}
    obbligatorie = [v for v in requisiti.formazione(ctx, persone) if v.obbligatorio]
    if info is not None:
        info["n_obblighi"] = len(obbligatorie)
    voci = [v for v in obbligatorie
            if v.stato in ("SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO")]
    corsi_all = sorted({v.corso.pk: v.corso for v in voci}.values(), key=lambda c: (c.titolo or "").casefold())
    _ord = {"SCADUTO": 0, "IN_SCADENZA_30": 1, "IN_SCADENZA_90": 2, "MAI_FREQUENTATO": 3}
    righe: list[dict] = []
    for v in voci:
        p = persone.get(v.persona)
        if p is None:
            continue
        if filtro_corso.isdigit() and str(v.corso.pk) != filtro_corso:
            continue
        if filtro_stato and v.stato != filtro_stato:
            continue
        reparto = (p.reparto or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        righe.append({
            "legacy_id": p.id,
            "nome": p.nominativo,
            "reparto": reparto or "—",
            "mansione": (p.mansione or "").strip() or "—",
            "corso": v.corso,
            "stato": v.stato,
            "stato_label": etichette.get(v.stato, v.stato),
            "data_scadenza": v.scadenza,
            "perche": ", ".join(v.origini[:3]),
        })
    righe.sort(key=lambda r: (r["reparto"].casefold(), r["nome"].casefold(), _ord.get(r["stato"], 9)))
    reparti = sorted({(p.reparto or "").strip() for p in persone.values() if (p.reparto or "").strip()})
    return corsi_all, reparti, righe
