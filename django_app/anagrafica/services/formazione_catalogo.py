"""Catalogo corsi: azioni in blocco dall'elenco Corsi (tipo, validità) e corsi una tantum da rivedere.

Analisi del 26/11/2026: nessun corso aveva un tipo (quindi nessuna valutazione di efficacia) e
molti corsi di «aggiornamento» o con rinnovo di legge erano una tantum (nessuna scadenza).
"""
from __future__ import annotations

import re

from django.db import transaction


class CatalogoError(Exception):
    pass


# Parole che fanno pensare a un corso con rinnovo periodico (da confermare con RSPP/Qualità).
_PAROLE_RINNOVO = re.compile(
    r"aggiornament|antincendio|primo\s+soccorso|carrell|muletti?\b|preposti?\b|\bple\b|piattaform"
    r"|\bgru\b|carroponte|\brls\b|\brspp\b|\baspp\b|spazi\s+confinati|lavori\s+in\s+quota|ponteggi"
    r"|\bdpi\b.*terza|blsd?\b|defibrillat",
    re.IGNORECASE,
)


def ids_una_tantum_da_rivedere() -> list[int]:
    """Corsi senza validità (una tantum) il cui titolo fa pensare a un rinnovo."""
    from django.db.models import Q

    from ..models_formazione import TrainingCourse

    out = []
    for pk, titolo in (TrainingCourse.objects.filter(Q(validita_mesi__isnull=True) | Q(validita_mesi=0))
                       .exclude(stato="ARCHIVIATO").filter(is_active=True).values_list("pk", "titolo")):
        if _PAROLE_RINNOVO.search(titolo or ""):
            out.append(pk)
    return out


# ── «Obbligatorio» nel catalogo: una regola sola ─────────────────────────────
# Prima elenco, scheda piano, tipi ed export leggevano solo la spunta «Obbligatorio per tutti»:
# un corso chiesto da una mansione, un ruolo o un processo risultava «facoltativo».
PER_TUTTI = "per tutti"
PER_MANSIONE = "per mansione/ruolo/processo"


def _q_regole_in_vigore(oggi):
    from django.db.models import Q

    return (Q(is_active=True, is_mandatory=True)
            & (Q(data_inizio_validita__isnull=True) | Q(data_inizio_validita__lte=oggi))
            & (Q(data_fine_validita__isnull=True) | Q(data_fine_validita__gte=oggi)))


def q_obbligatori(oggi=None):
    """``Q`` sui ``TrainingCourse`` obbligatori (stessa definizione di :func:`corsi_obbligatori`).

    Fonti: la spunta «Obbligatorio per tutti» (corso attivo), le righe della cache scadenze
    con ``is_required`` (scritte dal motore dei requisiti: mansione, fattori di rischio,
    esposizioni, regole, processi MOD.128) e le regole di obbligo in vigore sul corso o sul suo
    piano. Sottoquery, nessuna lista di id: regge anche su SQL Server con molti corsi."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingDeadline, TrainingRequirementRule

    oggi = oggi or timezone.localdate()
    regole = TrainingRequirementRule.objects.filter(_q_regole_in_vigore(oggi))
    return (Q(obbligatorio=True, is_active=True)
            | Q(pk__in=TrainingDeadline.objects.filter(is_required=True).values("corso_id"))
            | Q(pk__in=regole.filter(corso__isnull=False).values("corso_id"))
            | Q(is_active=True, piano_id__in=regole.filter(piano__isnull=False).values("piano_id")))


def corsi_obbligatori(ids=None, *, oggi=None) -> dict[int, str]:
    """``{corso_id: "per tutti" | "per mansione/ruolo/processo"}`` dei corsi obbligatori.

    «per tutti» = spunta «Obbligatorio per tutti i dipendenti» su un corso attivo (origine
    «Corso obbligatorio per tutti» del motore); gli altri obbligatori lo sono per chi ha una
    certa mansione, un ruolo, un'area o un processo. ``ids`` limita ai corsi indicati."""
    from ..models_formazione import TrainingCourse

    qs = TrainingCourse.objects.filter(q_obbligatori(oggi))
    voluti = None
    if ids is not None:
        voluti = {int(i) for i in ids}
        if not voluti:
            return {}
        if len(voluti) <= 1000:  # oltre: tutti e poi filtro in Python (limite parametri SQL Server)
            qs = qs.filter(pk__in=voluti)
    return {pk: PER_TUTTI if (tutti and attivo) else PER_MANSIONE
            for pk, tutti, attivo in qs.values_list("pk", "obbligatorio", "is_active").distinct()
            if voluti is None or pk in voluti}


def etichetta_obbligo(tipo: str | None) -> str:
    """«Sì · per tutti» / «Sì · per mansione/ruolo/processo» / «» (colonne ed export)."""
    return f"Sì · {tipo}" if tipo else ""


def filtra_obbligatorio(qs, valore: str):
    """Filtro «Solo obbligatori» (1) / «Solo facoltativi» (0) dell'elenco corsi e del suo export."""
    if valore == "1":
        return qs.filter(q_obbligatori())
    if valore == "0":
        return qs.exclude(q_obbligatori())
    return qs


# ── Elenco corsi: stessi filtri per pagina ed export ─────────────────────────
# «Come si fa» un corso: dalle modalità delle sue sessioni (annullate escluse) e dall'online
# sempre aperto. (chiave, etichetta della pastiglia, modalità della sessione o None)
MODI_CORSO = [
    ("aula", "In aula", "IN_SEDE"),
    ("esterno", "Ente esterno", "ESTERNO"),
    ("diretta", "Online in diretta", "REMOTO"),
    ("slide", "Slide + test", "ONLINE"),
    ("misto", "Misto", "MISTO"),
    ("sempre", "Online sempre aperto", None),
]
MODI_ETICHETTE = [("IN_SEDE", "In aula"), ("ESTERNO", "Ente esterno"), ("REMOTO", "Online in diretta"),
                  ("ONLINE", "Slide + test"), ("MISTO", "Misto"), ("sempre", "Sempre aperto")]


def q_modo(modalita):
    """``Q`` dei corsi con almeno una sessione non annullata nella modalità (None = online sempre aperto)."""
    from django.db.models import Q

    from ..models_formazione import TrainingSession

    if modalita is None:
        return Q(is_elearning=True)
    return Q(pk__in=TrainingSession.objects.filter(modalita=modalita).exclude(stato="ANNULLATA").values("corso_id"))


def filtri_corsi(get) -> dict:
    """Parametri GET dell'elenco corsi, ripuliti (pagina ed export leggono questi)."""
    return {
        "piano": (get.get("piano") or "").strip(),
        "stato": (get.get("stato") or "").strip(),
        "obbligatorio": (get.get("obbligatorio") or "").strip(),
        "attivi": (get.get("attivi") or "") == "1",
        "q": (get.get("q") or "").strip(),
        "modo": (get.get("modo") or "").strip(),
        "tipo": (get.get("tipo") or "").strip(),
        "rinnovo": get.get("rinnovo") == "1",
    }


def corsi_filtrati(get, *, con_conteggi: bool = False):
    """Queryset dell'elenco corsi con tutti i filtri della pagina; con ``con_conteggi`` anche i
    conteggi delle pastiglie «Come si fa» (calcolati sul resto dei filtri, prima di quello scelto).

    Ritorna ``(qs, filtri, modi_conteggi)``. Usato da ``formazione_corsi_list`` e dal suo export:
    stesse righe a video e nel file."""
    from django.db.models import Prefetch, Q

    from ..models_formazione import TrainingCourse, TrainingSession

    f = filtri_corsi(get)
    qs = TrainingCourse.objects.select_related("piano", "ente_formativo", "tipo").prefetch_related(
        Prefetch("sessioni",
                 queryset=TrainingSession.objects.select_related("docente__azienda").order_by("-data_inizio")))
    if f["piano"].isdigit():
        qs = qs.filter(piano_id=int(f["piano"]))
    if f["stato"]:
        qs = qs.filter(stato=f["stato"])
    if f["attivi"]:
        qs = qs.filter(is_active=True)
    qs = filtra_obbligatorio(qs, f["obbligatorio"])
    if f["q"]:
        qs = qs.filter(Q(titolo__icontains=f["q"]) | Q(codice__icontains=f["q"])
                       | Q(ente_formativo__nome__icontains=f["q"]))
    if f["tipo"] == "nessuno":
        qs = qs.filter(tipo__isnull=True)
    elif f["tipo"].isdigit():
        qs = qs.filter(tipo_id=int(f["tipo"]))
    if f["rinnovo"]:
        qs = qs.filter(pk__in=ids_una_tantum_da_rivedere())
    modi_conteggi = ([(chiave, etichetta, qs.filter(q_modo(mod)).count()) for chiave, etichetta, mod in MODI_CORSO]
                     if con_conteggi else [])
    for chiave, _etichetta, mod in MODI_CORSO:
        if f["modo"] == chiave:
            qs = qs.filter(q_modo(mod))
    return qs.order_by("piano__nome", "titolo"), f, modi_conteggi


def arricchisci_corso(corso) -> None:
    """``corso.enti_formatori`` e ``corso.modi`` dalle sessioni già lette (prefetch).

    L'ente di riferimento del corso (esplicito) viene per primo; gli enti visti solo tramite i
    docenti delle sessioni completano l'elenco quando differiscono. Le sessioni annullate non
    dicono «come si fa» il corso."""
    nomi, visti = [], set()
    if corso.ente_formativo_id:
        nomi.append(corso.ente_formativo.nome)
        visti.add(corso.ente_formativo.nome)
    sessioni = list(corso.sessioni.all())
    for sessione in sessioni:
        docente = sessione.docente
        if not docente:
            continue
        nome = docente.azienda.nome if docente.azienda_id else docente.ragione_sociale
        if nome and nome not in visti:
            visti.add(nome)
            nomi.append(nome)
    corso.enti_formatori = nomi
    modi = {s.modalita for s in sessioni if s.stato != "ANNULLATA"}
    corso.modi = [(k, e) for k, e in MODI_ETICHETTE if (k == "sempre" and corso.is_elearning) or k in modi]


def n_corsi_senza_tipo() -> int:
    """Corsi senza tipo: lo stesso numero nella pastiglia «Senza tipo» dell'elenco e nei Tipi di corso."""
    from ..models_formazione import TrainingCourse

    return TrainingCourse.objects.filter(tipo__isnull=True).count()


# ── Persone con un'attività sul corso: scheda corso e CSV del report ───────────
def persone_del_corso(corso, *, oggi=None) -> dict:
    """Chi ha un'attività sul corso, da ogni strada, con lo stato della regola unica.

    Unisce gli id di iscrizioni alle edizioni, completamenti, assegnazioni, iscrizioni
    e-learning e partecipazioni al link aperto abbinate a un dipendente; lo stato viene da
    ``formazione_completamento.stati_persona_corso``. Ritorna::

        {"ids": set, "cessati": set, "stati": {lid: StatoPersonaCorso},
         "n_sessioni": Counter, "n_completamenti": Counter, "n_idonei": Counter,
         "presenza": {lid: ultima % presenza}, "iscrizioni": [TrainingEnrollment]}

    ``cessati``: ex dipendenti fra gli ``ids`` (``training_eligibility._cessati_ids``)."""
    from collections import Counter

    from ..models_elearning import TrainingElearningPartecipazioneAperta
    from ..models_formazione import (
        TrainingAssignment, TrainingElearningEnrollment, TrainingEmployeeRecord, TrainingEnrollment,
    )
    from .formazione_completamento import stati_persona_corso
    from .training_eligibility import _cessati_ids

    iscrizioni = list(TrainingEnrollment.objects.filter(sessione__corso=corso)
                      .select_related("avanzamento_online").order_by("pk"))
    n_sessioni, n_compl, n_idonei, presenza = Counter(), Counter(), Counter(), {}
    for e in iscrizioni:
        n_sessioni[e.legacy_anagrafica_id] += 1
        if e.percentuale_presenza is not None:
            presenza[e.legacy_anagrafica_id] = e.percentuale_presenza
    for lid, idoneo in TrainingEmployeeRecord.objects.filter(corso=corso).values_list("legacy_anagrafica_id", "idoneo"):
        n_compl[lid] += 1
        if idoneo:
            n_idonei[lid] += 1
    ids = set(n_sessioni) | set(n_compl)
    ids |= set(TrainingAssignment.objects.filter(corso=corso).values_list("legacy_anagrafica_id", flat=True))
    ids |= set(TrainingElearningEnrollment.objects.filter(corso=corso).values_list("legacy_anagrafica_id", flat=True))
    ids |= set(TrainingElearningPartecipazioneAperta.objects.filter(corso=corso, legacy_anagrafica_id__isnull=False)
               .values_list("legacy_anagrafica_id", flat=True))
    ids = {int(i) for i in ids if i and int(i) > 0}
    return {
        "ids": ids,
        "cessati": ids & _cessati_ids() if ids else set(),
        "stati": stati_persona_corso(corso, ids, iscrizioni=iscrizioni, oggi=oggi) if ids else {},
        "n_sessioni": n_sessioni, "n_completamenti": n_compl, "n_idonei": n_idonei,
        "presenza": presenza, "iscrizioni": iscrizioni,
    }


def nomi_e_ordine() -> tuple[dict[int, str], dict[int, str]]:
    """Una sola lettura dell'anagrafica: ``({id: "Nome Cognome"}, {id: chiave per cognome})``."""
    import logging

    from core import naming
    from core.legacy_models import AnagraficaDipendente

    nomi, ordine = {}, {}
    try:
        for lid, cognome, nome in AnagraficaDipendente.objects.values_list("id", "cognome", "nome"):
            if not lid:
                continue
            nomi[int(lid)] = naming.nome_completo(nome, cognome) or f"#{lid}"
            ordine[int(lid)] = naming.chiave_ordinamento(nome, cognome) or f"#{lid}"
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Anagrafica non leggibile per i nomi del corso")
    return nomi, ordine


def motivi_blocco_eliminazione(corso) -> list[str]:
    """Cosa impedisce di eliminare il corso (vuoto = si può): sessioni, completamenti, assegnazioni,
    iscrizioni e-learning, partecipazioni al link aperto, uso come modulo di un altro corso.

    Le prime tre sono PROTECT (prima: errore 500), le altre CASCADE (prima: cancellate in silenzio)."""
    from ..models_formazione import TrainingElearningEnrollment

    controlli = [
        (corso.sessioni.exists(), "sessioni"),
        (corso.record_completamenti.exists(), "completamenti registrati"),
        (corso.assegnazioni.exists(), "assegnazioni"),
        (TrainingElearningEnrollment.objects.filter(corso=corso).exists(), "iscrizioni e-learning"),
        (corso.partecipazioni_aperte.exists(), "partecipazioni dal link aperto"),
        (corso.usato_come_modulo.exists(), "un uso come modulo di un altro corso"),
    ]
    return [testo for presente, testo in controlli if presente]


def assegna_tipo(ids: list[int], tipo_id: str) -> tuple[int, str]:
    from ..models_formazione import TrainingCourse, TrainingCourseType

    if tipo_id == "nessuno":
        n = TrainingCourse.objects.filter(pk__in=ids).update(tipo=None)
        return n, "nessuno"
    tipo = TrainingCourseType.objects.filter(pk=int(tipo_id) if str(tipo_id).isdigit() else 0).first()
    if tipo is None:
        raise CatalogoError("Scegli il tipo da assegnare.")
    n = TrainingCourse.objects.filter(pk__in=ids).update(tipo=tipo)
    return n, tipo.nome


def imposta_validita(ids: list[int], mesi: str, *, riempi_scadenze: bool = False, user=None) -> dict:
    """Cambia la validità dei corsi. Con ``riempi_scadenze`` i completamenti validi senza data di
    scadenza ricevono completamento + validità; le scadenze già scritte (attestato) non cambiano.

    Ogni corso toccato riceve la sua versione (``corso_versioni.registra``: la validità fa parte
    della fotografia del corso) e le scadenze del cruscotto si ricalcolano **una volta sola** a
    blocco concluso (prima: un ricalcolo completo per ogni corso selezionato)."""
    from ..models_formazione import TrainingCourse, TrainingDeadline, TrainingEmployeeRecord
    from ..views._helpers import _add_months
    from .scadenze import ricalcola_dopo_commit

    if not str(mesi).strip().isdigit():
        raise CatalogoError("Scrivi la validità in mesi (0 = una tantum).")
    mesi = min(int(mesi), 240)
    n_scadenze = 0
    with transaction.atomic():
        toccati = list(TrainingCourse.objects.filter(pk__in=ids).exclude(validita_mesi=mesi))
        n = TrainingCourse.objects.filter(pk__in=ids).update(validita_mesi=mesi)
        if riempi_scadenze and mesi:
            for r in TrainingEmployeeRecord.objects.filter(corso_id__in=ids, data_scadenza__isnull=True,
                                                           idoneo=True).only("pk", "data_completamento"):
                TrainingEmployeeRecord.objects.filter(pk=r.pk).update(
                    data_scadenza=_add_months(r.data_completamento, mesi))
                n_scadenze += 1
        TrainingDeadline.objects.filter(corso_id__in=ids).update(needs_refresh=True)
        _registra_versioni(toccati, user)
        # update() non manda segnali: il ricalcolo va chiesto, uno solo per tutto il blocco.
        ricalcola_dopo_commit(None)
    return {"corsi": n, "mesi": mesi, "scadenze": n_scadenze}


def _registra_versioni(corsi, user) -> None:
    """Versione automatica dei corsi cambiati in blocco (mai bloccante: lo dice il log)."""
    import logging

    from . import corso_versioni

    for corso in corsi:
        try:
            corso_versioni.registra(corso, user=user)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Versione non registrata per il corso %s", corso.pk)
