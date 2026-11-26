"""Motore di idoneità candidati alla formazione — NOVICROM HUB.

Risponde alla domanda: «chi ha senso (ri)formare per questo corso, e chi soddisfa
i requisiti per esservi iscritto?». È il cuore delle "regole non visibili" della
sezione formazione e generalizza ``views._candidati_rinnovo_corso``.

Per un corso (ed eventualmente una sessione/edizione) calcola, in poche query batch:

- **pertinenza** — chi è *tenuto* al corso secondo le ``TrainingRequirementRule``
  (regola diretta per dipendente, per ``RuoloOperativo``, per ``AreaAziendale`` o per
  ``Mansione``, quest'ultima anche **ereditata** dai fattori di rischio tramite
  l'inversione di :func:`services.mansionario.requisiti_per_nome`);
- **stato scadenza** dalla cache :class:`TrainingDeadline`;
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

from datetime import date
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
    ``views._cessati_legacy_ids``: regola unica ``services.in_forza.cessati_ids``."""
    from .in_forza import cessati_ids

    return cessati_ids()


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


def _legacy_ids_pertinenti(corso, dipendenti: dict[int, dict]) -> tuple[set[int], bool]:
    """Insieme dei ``legacy_id`` *tenuti* al corso + flag ``has_rules``.

    Considera le ``TrainingRequirementRule`` attive e obbligatorie che riguardano il
    corso o il suo piano, sui quattro target (diretto / ruolo / area / mansione) più
    l'ereditarietà mansione→corso dai fattori di rischio (via ``mansionario``).
    """
    from django.db.models import Q

    from ..models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo
    from ..models_formazione import TrainingRequirementRule
    from . import mansionario

    rules = list(
        TrainingRequirementRule.objects
        .filter(is_active=True, is_mandatory=True)
        .filter(Q(corso=corso) | Q(piano_id=corso.piano_id))
        .select_related("area", "ruolo_operativo")
    )
    has_rules = bool(rules)
    ids: set[int] = set()

    # 0) spunta «Obbligatorio per tutti i dipendenti»: tenuti tutti quelli in forza
    #    (stessa regola del motore dei requisiti, origine «Corso obbligatorio per tutti»).
    if getattr(corso, "obbligatorio", False) and getattr(corso, "is_active", True):
        has_rules = True
        ids.update(dipendenti.keys())

    # 1) regole dirette per singolo dipendente
    ids.update(int(r.legacy_anagrafica_id) for r in rules if r.legacy_anagrafica_id)

    # 2) regole per ruolo operativo
    ruolo_ids = [r.ruolo_operativo_id for r in rules if r.ruolo_operativo_id]
    if ruolo_ids:
        ids.update(
            int(lid) for lid in DipendenteRuoloOperativo.objects
            .filter(ruolo_id__in=ruolo_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    # 2b) regole per mansione lavorativa: chi è in lista sulla mansione (skill matrix)
    competenza_ids = [r.competenza_id for r in rules if r.competenza_id]
    if competenza_ids:
        from ..models import AbilitazioneMacchina
        ids.update(
            int(lid) for lid in AbilitazioneMacchina.objects
            .filter(competenza_id__in=competenza_ids, in_lista=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    # 3) regole per area aziendale (match per FK area_aziendale, non più per nome)
    area_ids = {r.area_id for r in rules if r.area_id}
    if area_ids:
        ids.update(
            int(lid) for lid in DipendenteAnagraficaAziendale.objects
            .filter(area_aziendale_id__in=area_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    # 4) regole per mansione di rischio + ereditarietà da fattori di rischio.
    #    Inverte mansionario: per ogni mansione di rischio presente in organico
    #    (anagrafica + mansioni svolte + aggiunte − esclusioni), se i suoi
    #    requisiti includono questo corso, chi la ha è "tenuto" al corso.
    nomi_per_persona = mansionario.nomi_mansioni_rischio(
        list(dipendenti), mansioni_per_legacy={lid: e["mansione"] for lid, e in dipendenti.items()})
    mansioni_presenti = {n for nomi in nomi_per_persona.values() for n in nomi}
    if mansioni_presenti:
        req_per_nome = mansionario.requisiti_per_nome(mansioni_presenti)
        mansioni_obbligate = {
            nome for nome, req in req_per_nome.items()
            if any(c.pk == corso.pk for c in req.get("corsi", []))
        }
        if mansioni_obbligate:
            has_rules = True
            for lid, nomi in nomi_per_persona.items():
                if any(n.casefold() in mansioni_obbligate for n in nomi):
                    ids.add(lid)

    # 5) requisiti MOD.128: abilitati (ATTIVA) a processi che richiedono il corso.
    try:
        from .mpq_formazione import legacy_ids_richiesti_da_processo
        proc_ids = legacy_ids_richiesti_da_processo(corso.pk)
    except Exception:
        proc_ids = set()
    if proc_ids:
        has_rules = True
        ids.update(proc_ids)

    # Restringi ai dipendenti effettivamente in forza.
    ids &= set(dipendenti.keys())
    return ids, has_rules


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


def candidati_corso(corso, *, sessione=None, oggi: date | None = None) -> dict[str, Any]:
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
    """
    from django.utils import timezone

    from ..models_formazione import (
        TrainingCourseDependency,
        TrainingDeadline,
        TrainingEmployeeRecord,
        TrainingEnrollment,
        TrainingSession,
    )

    oggi = oggi or timezone.localdate()
    dipendenti = _dipendenti_attivi()
    pertinenti, has_rules = _legacy_ids_pertinenti(corso, dipendenti)

    deadlines = {
        d.legacy_anagrafica_id: d
        for d in TrainingDeadline.objects.filter(corso=corso)
    }

    pool_filtrato = has_rules and bool(pertinenti)
    if pool_filtrato:
        base = set(pertinenti)
        # Includi anche chi ha una scadenza rilevante pur non risultando più tenuto.
        base |= {
            lid for lid, d in deadlines.items()
            if d.stato_scadenza in STATI_RILEVANTI and lid in dipendenti
        }
    else:
        # Nessuna regola: degrada ai candidati da scadenza (comportamento storico).
        base = {
            lid for lid, d in deadlines.items()
            if d.stato_scadenza in STATI_RILEVANTI and lid in dipendenti
        }

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

    # Completamento idoneo non scaduto (qualunque strada): già a posto anche se la scadenza
    # in TrainingDeadline non è ancora stata ricalcolata.
    from django.db.models import Q as _Q
    validi = set(
        TrainingEmployeeRecord.objects.filter(corso=corso, idoneo=True, legacy_anagrafica_id__in=base)
        .filter(_Q(data_scadenza__isnull=True) | _Q(data_scadenza__gte=oggi))
        .values_list("legacy_anagrafica_id", flat=True)
    ) if base else set()

    idonei: list[dict] = []
    non_idonei: list[dict] = []
    for lid in base:
        if lid in iscritti_sessione:
            continue
        emp = dipendenti.get(lid)
        if emp is None:
            continue
        d = deadlines.get(lid)
        stato = d.stato_scadenza if d else "MAI_FREQUENTATO"
        if stato in STATI_GIA_VALIDO:
            continue  # già a posto
        if d is None and lid in validi:
            continue  # completamento valido, scadenza non ancora ricalcolata

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
            "nome": emp["nome"],
            "stato": stato,
            "stato_label": d.get_stato_scadenza_display() if d else "Mai frequentato",
            "data_scadenza": d.data_scadenza if d else None,
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
    visibili: set[int] | None = None,
) -> tuple[list, list[str], list[dict]]:
    """Una riga per (dipendente in forza, corso obbligatorio) non in regola: scaduto, in scadenza o
    mai frequentato. Condivisa da `views.formazione_copertura` e dal suo export.

    «Obbligatorio» ha una definizione sola: quella del motore dei requisiti
    (``services.requisiti.formazione``), che unisce mansione, fattori di rischio, esposizioni, regole di
    obbligo e processi MOD.128 — la stessa di scadenzario, cruscotto HR e conformità. Prima la pagina
    leggeva solo le regole di obbligo (in produzione nessuna) e restava vuota (analisi 26/11/2026).

    ``info`` (facoltativo) riceve ``n_obblighi``: quante coppie persona × corso obbligatorio il motore
    trova in tutto. Zero vuol dire «nessun obbligo configurato», non «tutti in regola».

    ``visibili`` = id anagrafica delle schede che il ruolo vede (None = tutte)."""
    from django.utils import timezone

    from ..models_formazione import TrainingDeadline
    from . import requisiti

    etichette = dict(TrainingDeadline.STATO_SCADENZA_CHOICES)
    etichette.setdefault("MAI_FREQUENTATO", "Mai frequentato")
    oggi = timezone.localdate()
    ctx = requisiti.ambito(oggi)
    persone = {p.id: p for p in ctx._tutti() if p.in_forza_al(oggi)}
    if visibili is not None:
        ammessi = {ctx.canonico(i) for i in visibili}
        persone = {pid: p for pid, p in persone.items() if pid in ammessi}
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
