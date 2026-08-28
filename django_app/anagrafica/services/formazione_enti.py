"""Chi ci ha formato: aggregazione delle erogazioni per ente di formazione.

Un ente non eroga direttamente: erogano i suoi **docenti**. La formazione
svolta da un ente è quindi l'unione delle sessioni in cui uno dei suoi docenti
è titolare e di quelle in cui uno dei suoi docenti ha tenuto una lezione — le
due cose divergono, e chi legge il riepilogo vuole entrambe.

Le **ore** si attribuiscono per lezione, non per sessione: in una giornata con
due docenti di enti diversi ogni ente si prende le proprie ore. La lezione senza
docente proprio eredita il titolare della sessione, che è quello che succede in
pratica quando l'edizione ha un solo formatore.

Una sola scansione delle sessioni del periodo, con lezioni e docenti
precaricati: niente query per ente.
"""
from __future__ import annotations

from datetime import date

from django.db.models import Count

from ..models_formazione import TrainingProvider, TrainingSession

__all__ = ["sessioni_del_periodo", "riepilogo_enti", "erogazioni_di_ente"]


def _sessioni_qs(dal: date | None = None, al: date | None = None):
    """Sessioni del periodo con lezioni, docenti ed enti già caricati.

    Il periodo si misura sulla **data di inizio** della sessione: è la data che
    l'utente ha in mente quando chiede "cosa abbiamo fatto nel 2025", ed è
    quella mostrata ovunque negli elenchi.
    """
    qs = (
        TrainingSession.objects
        .select_related("corso", "docente", "docente__azienda")
        .annotate(n_iscritti=Count("iscrizioni", distinct=True))
        .prefetch_related("lezioni__docente__azienda")
    )
    if dal:
        qs = qs.filter(data_inizio__gte=dal)
    if al:
        qs = qs.filter(data_inizio__lte=al)
    return qs.order_by("-data_inizio")


def sessioni_del_periodo(dal: date | None = None, al: date | None = None) -> list[TrainingSession]:
    return list(_sessioni_qs(dal, al))


def _ore_per_ente(sessione: TrainingSession) -> dict[int, float]:
    """{azienda_id: ore} per una sessione. Le lezioni senza docente proprio
    vanno al titolare; ciò che non ha ente non compare."""
    ore: dict[int, float] = {}
    titolare_ente = sessione.docente.azienda_id if sessione.docente_id else None
    for lez in sessione.lezioni.all():
        if lez.docente_id:
            ente = lez.docente.azienda_id
        else:
            ente = titolare_ente
        if not ente:
            continue
        ore[ente] = ore.get(ente, 0.0) + lez.durata_ore
    return ore


def _enti_coinvolti(sessione: TrainingSession) -> set[int]:
    enti: set[int] = set()
    if sessione.docente_id and sessione.docente.azienda_id:
        enti.add(sessione.docente.azienda_id)
    for lez in sessione.lezioni.all():
        if lez.docente_id and lez.docente.azienda_id:
            enti.add(lez.docente.azienda_id)
    return enti


def riepilogo_enti(dal: date | None = None, al: date | None = None) -> list[dict]:
    """Una riga per ente che ha erogato qualcosa nel periodo.

    Gli enti a catalogo che nel periodo non hanno erogato niente compaiono lo
    stesso a zero: "questo fornitore non lo usiamo più" è un'informazione, e
    sparire dall'elenco la nasconderebbe.
    """
    aggregato: dict[int, dict] = {}
    for sess in _sessioni_qs(dal, al):
        ore = _ore_per_ente(sess)
        for ente_id in _enti_coinvolti(sess):
            riga = aggregato.setdefault(ente_id, {
                "n_sessioni": 0, "corsi": set(), "ore": 0.0,
                "discenti": 0, "ultima_data": None,
            })
            riga["n_sessioni"] += 1
            riga["corsi"].add(sess.corso_id)
            riga["ore"] += ore.get(ente_id, 0.0)
            riga["discenti"] += sess.n_iscritti
            if riga["ultima_data"] is None or sess.data_inizio > riga["ultima_data"]:
                riga["ultima_data"] = sess.data_inizio

    enti = (
        TrainingProvider.objects
        .annotate(n_docenti=Count("istruttori", distinct=True))
        .order_by("nome")
    )
    righe: list[dict] = []
    for ente in enti:
        dati = aggregato.get(ente.pk, {})
        righe.append({
            "ente": ente,
            "n_docenti": ente.n_docenti,
            "n_sessioni": dati.get("n_sessioni", 0),
            "n_corsi": len(dati.get("corsi", ())),
            "ore": round(dati.get("ore", 0.0), 2),
            "discenti": dati.get("discenti", 0),
            "ultima_data": dati.get("ultima_data"),
        })
    # Chi ha erogato di più sta in cima; a parità, ordine alfabetico stabile.
    righe.sort(key=lambda r: (-r["n_sessioni"], -r["ore"], r["ente"].nome.casefold()))
    return righe


def erogazioni_di_ente(azienda_id: int, dal: date | None = None, al: date | None = None) -> dict:
    """Sessioni erogate da un ente nel periodo, con i totali della sua riga.

    `per_corso` raggruppa le stesse sessioni per corso (albero corso → edizioni,
    come il catalogo corsi): un corso può avere più edizioni erogate dallo
    stesso ente, e vederle una sotto l'altra senza ripetere titolo/codice è
    più leggibile di una tabella piatta.
    """
    sessioni: list[TrainingSession] = []
    ore_totali = 0.0
    discenti = 0
    per_corso: dict[int, dict] = {}
    for sess in _sessioni_qs(dal, al):
        if azienda_id not in _enti_coinvolti(sess):
            continue
        sess.ore_ente = round(_ore_per_ente(sess).get(azienda_id, 0.0), 2)
        sessioni.append(sess)
        ore_totali += sess.ore_ente
        discenti += sess.n_iscritti

        gruppo = per_corso.setdefault(sess.corso_id, {
            "corso": sess.corso, "sessioni": [], "ore": 0.0,
            "discenti": 0, "ultima_data": None,
        })
        gruppo["sessioni"].append(sess)
        gruppo["ore"] += sess.ore_ente
        gruppo["discenti"] += sess.n_iscritti
        if gruppo["ultima_data"] is None or sess.data_inizio > gruppo["ultima_data"]:
            gruppo["ultima_data"] = sess.data_inizio

    for gruppo in per_corso.values():
        gruppo["ore"] = round(gruppo["ore"], 2)
        gruppo["n_sessioni"] = len(gruppo["sessioni"])
    gruppi = sorted(per_corso.values(), key=lambda g: g["ultima_data"], reverse=True)

    return {
        "sessioni": sessioni,
        "per_corso": gruppi,
        "ore": round(ore_totali, 2),
        "discenti": discenti,
        "n_corsi": len(per_corso),
    }
