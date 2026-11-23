"""«Cosa manca» della Panoramica: un solo elenco di quello che resta da fare.

Fonde quattro blocchi che dicevano la stessa cosa da angoli diversi: Prossimi
passi (incontri e consegna), Percorso (tappe), Prontezza all'avvio (VRF, team,
piano) e Prossime attività (quelle in ritardo). Ogni riga dice cosa manca e
porta dove si risolve; quello che è a posto si conta e si elenca a richiesta.
"""
from __future__ import annotations

from django.urls import reverse

from ..models import TaskStatus
from .filo import prossimi_passi

_ORDINE = {"danger": 0, "warn": 1, "info": 2}
MAX_IN_RITARDO = 5
MAX_TAPPE_SINGOLE = 3


def _riga(tono, titolo, dettaglio="", url="", azione="", *, pannello=False) -> dict:
    return {"tono": tono, "titolo": titolo, "dettaglio": dettaglio, "url": url, "azione": azione, "pannello": pannello}


def _voce_tappa(voce) -> str:
    """«Responsabile · entro gg/mm» della prima attività aperta di una tappa."""
    t = voce["task"]
    pezzi = []
    if t.assigned_to_id:
        pezzi.append((t.assigned_to.get_full_name() or t.assigned_to.get_username()).strip())
    if t.due_date:
        pezzi.append(f"entro {t.due_date:%d/%m}")
    return " · ".join(pezzi)


def cosa_manca(project, *, tappe: dict, readiness, azioni, can_manage: bool, puo_assegnare: bool) -> dict:
    """Righe ancora aperte (in ordine di urgenza) ed elenco di ciò che è a posto."""
    pid = project.pk
    righe: list[dict] = []
    a_posto: list[str] = []
    raggruppate = 0  # tappe contate in una riga sola: nel totale valgono una ciascuna
    if project.chiuso_il:
        return {"righe": [], "a_posto": [], "totale": 0, "percento": 100, "chiuso": True}

    # 1. Incontri e consegna: stesse regole dei «Prossimi passi», senza il riassunto delle tappe.
    passi = prossimi_passi(project, tappe=None, can_manage=can_manage, limite=20)
    for p in passi:
        righe.append(_riga(p["tono"], p["titolo"], p["dettaglio"], p["url"], p["azione"]))
    parla_di_incontri = any("incontro" in p["titolo"].lower() for p in passi)

    # 2. Tappe del Percorso: una riga per tappa non ancora a posto.
    id_di_tappa: set[int] = set()
    vuote: list[dict] = []
    for r in tappe.get("righe", []):
        stato = r["stato"]
        for v in r["voci"]:
            id_di_tappa.add(v["task"].pk)
        if stato in ("fatta", "esclusa"):
            a_posto.append(r["label"] + (" (non serve)" if stato == "esclusa" else ""))
            continue
        if stato == "vuota":
            vuote.append(r)
            continue
        aperte = [v for v in r["voci"] if v["task"].status != TaskStatus.DONE]
        voce = aperte[0] if aperte else r["voci"][0]
        # «Manca: programma CAM» resta com'è scritto (le sigle non si abbassano).
        cosa = r["stato_label"] if stato == "manca" else r["stato_label"].lower()
        dettaglio = " · ".join(x for x in ("Tappa del Percorso", cosa, _voce_tappa(voce)) if x)
        tono = "danger" if stato == "ritardo" else "warn" if stato == "manca" else "info"
        righe.append(_riga(tono, r["label"], dettaglio, voce["url"], "Apri", pannello=True))

    url_percorso = "#percorso" if puo_assegnare else ""
    if len(vuote) > MAX_TAPPE_SINGOLE:
        righe.append(_riga(
            "warn", f"{len(vuote)} tappe del Percorso da assegnare", ", ".join(r["label"] for r in vuote),
            url_percorso, "Assegna",
        ))
        raggruppate = len(vuote) - 1
    else:
        for r in vuote:
            righe.append(_riga("warn", r["label"], f"Tappa del Percorso · {r['stato_label'].lower()}", url_percorso, "Assegna"))

    # 3. Prontezza all'avvio: VRF, incontro di kickoff, team, piano.
    for c in readiness.criteria:
        if c.ok:
            a_posto.append(c.label)
            continue
        url = (c.action_url or "") if can_manage else ""
        if c.key == "vrf":
            righe.append(_riga("warn", "VRF da compilare", "MOD.073 · valutazione rischi e fornitura", url, "Compila"))
        elif c.key == "meeting":
            if not parla_di_incontri:
                righe.append(_riga("info", "Incontro di kickoff da svolgere", "Pianificato, non ancora svolto", url, "Incontri"))
        elif c.key == "team":
            righe.append(_riga("warn", "Team incompleto", "Servono PM, capocommessa e programmatore", url, "Completa"))
        elif c.key == "plan":
            righe.append(_riga(
                "warn", "Nessuna attività con scadenza", "Il piano non ha ancora date",
                reverse("tasks:project_attivita_pianifica", args=[pid]) if can_manage else "", "Pianifica",
            ))

    # 4. Attività in ritardo fuori dal Percorso (le tappe in ritardo sono già sopra).
    in_ritardo = [a for a in azioni if a.is_overdue and not (a.origin == "task" and a.obj_id in id_di_tappa)]
    for a in in_ritardo[:MAX_IN_RITARDO]:
        pezzi = [a.source_label, a.owner_label or "senza responsabile"]
        if a.due_date:
            pezzi.append(f"scaduta il {a.due_date:%d/%m}")
        righe.append(_riga("danger", a.title, " · ".join(x for x in pezzi if x), a.url, "Apri", pannello=a.origin == "task"))
    if len(in_ritardo) > MAX_IN_RITARDO:
        altre = len(in_ritardo) - MAX_IN_RITARDO
        righe.append(_riga(
            "danger", f"Altre {altre} attività in ritardo", "Nel Piano, filtro «In ritardo»",
            reverse("tasks:project_actions", args=[pid]) + "?vista=ritardo", "Vedi",
        ))

    righe.sort(key=lambda r: _ORDINE.get(r["tono"], 3))
    totale = len(righe) + raggruppate + len(a_posto)
    return {
        "righe": righe,
        "a_posto": a_posto,
        "totale": totale,
        "percento": round(len(a_posto) * 100 / totale) if totale else 100,
        "chiuso": False,
    }
