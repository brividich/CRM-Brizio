"""Copilota KICK-OFF: prepara un incontro partendo da cio' che e' successo nelle commesse simili.

Una commessa e' «simile» se ha lo stesso cliente, lo stesso P/N o una descrizione che si somiglia.
Da quelle commesse il portale riporta (senza AI) i problemi emersi e come sono finiti, le decisioni,
le azioni rimaste aperte, le attivita' slittate rispetto alla baseline del Gantt e i rischi VRF valutati
alti. L'AI propone i punti all'ordine del giorno; chi gestisce l'incontro li aggiunge con un clic.

Impara: alla chiusura della minuta si confrontano i punti proposti con l'ordine del giorno finale;
i punti tenuti e quelli scartati nelle commesse precedenti entrano nel contesto delle proposte successive.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from django.db.models import Q

logger = logging.getLogger(__name__)

MODULO = "kickoff"
AZIONE = "punti_odg"
_STOP = {"della", "delle", "dello", "degli", "commessa", "progetto", "kickoff", "cliente", "nuovo", "nuova", "fornitura"}


def _tokens(testo: str) -> set[str]:
    return {p for p in re.findall(r"[a-zà-ù0-9]+", (testo or "").lower()) if len(p) >= 4 and p not in _STOP}


def _rischi_alti(project) -> list[str]:
    """Sotto-parametri VRF valutati 3 (o 2) in almeno una fase."""
    try:
        from .vrf_catalog import iter_sub_parameters

        dati = ((project.vrf_assessment.data or {}).get("risks") or {})
    except Exception:  # noqa: BLE001 - commessa senza VRF
        return []
    alti = []
    for risk, sub in iter_sub_parameters():
        punteggi = (((dati.get(risk["code"]) or {}).get("subs") or {}).get(sub["code"]) or {}).values()
        valori = [float(v) for v in punteggi if v not in (None, "")]
        if valori and max(valori) >= 2:
            alti.append((max(valori), f"{risk['title'].replace('Rischio di ', '').replace('Rischio ', '')}: {sub['label'][:90]}"))
    return [testo for _, testo in sorted(alti, key=lambda x: -x[0])[:4]]


def _slittamenti(project) -> list[str]:
    try:
        baseline = project.gantt_baseline
    except Exception:  # noqa: BLE001 - commessa senza baseline
        return []
    out = []
    for task in project.tasks.exclude(due_date__isnull=True)[:200]:
        entry = (baseline.snapshot or {}).get(str(task.pk)) or {}
        try:
            fine = date.fromisoformat(entry.get("end") or "")
        except ValueError:
            continue
        ritardo = (task.due_date - fine).days
        if ritardo >= 5:
            out.append((ritardo, f"{task.title[:80]} (+{ritardo} giorni)"))
    return [testo for _, testo in sorted(out, key=lambda x: -x[0])[:3]]


def commesse_simili(project, *, limite: int = 4, candidati: int = 300) -> list[dict]:
    from .models import MeetingActionStatus, MeetingIssueStatus, Project

    base = _tokens(f"{project.name} {project.description}")
    cliente = (project.client_name or "").strip().lower()
    pn = (project.part_number or "").strip().lower()
    filtro = Q(meeting_issues__isnull=False) | Q(meeting_decisions__isnull=False) | Q(meeting_actions__isnull=False) | Q(vrf_assessment__isnull=False)
    altre = (Project.objects.exclude(pk=project.pk).filter(filtro).distinct()
             .prefetch_related("meeting_issues", "meeting_decisions", "meeting_actions").order_by("-id")[:candidati])
    out = []
    for other in altre:
        parole = _tokens(f"{other.name} {other.description}")
        score = len(base & parole) / len(base | parole) if base and parole else 0.0
        motivi = []
        if cliente and (other.client_name or "").strip().lower() == cliente:
            score += 0.4
            motivi.append("stesso cliente")
        if pn and (other.part_number or "").strip().lower() == pn:
            score += 0.5
            motivi.append("stesso P/N")
        if score < 0.2:
            continue
        problemi = [{"titolo": i.title[:160], "risolto": i.status == MeetingIssueStatus.RESOLVED} for i in other.meeting_issues.all()][:6]
        out.append({
            "pk": other.pk,
            "nome": other.name,
            "kickoff": other.kickoff_number,
            "motivi": motivi,
            "problemi": problemi,
            "decisioni": [d.testo[:160] for d in other.meeting_decisions.all()][:4],
            "azioni_aperte": [a.title[:160] for a in other.meeting_actions.all() if a.status == MeetingActionStatus.OPEN][:4],
            "slittamenti": _slittamenti(other),
            "rischi": _rischi_alti(other),
            "score": round(score, 2),
        })
    out.sort(key=lambda r: -r["score"])
    return out[:limite]


def punti_ricorrenti(simili: list[dict]) -> list[dict]:
    """Problemi che tornano in piu' commesse simili: candidati certi per l'ordine del giorno."""
    visti: dict[str, dict] = {}
    for caso in simili:
        for problema in caso["problemi"]:
            chiave = " ".join(sorted(_tokens(problema["titolo"]))[:6])
            if not chiave:
                continue
            voce = visti.setdefault(chiave, {"titolo": problema["titolo"], "commesse": []})
            if caso["nome"] not in voce["commesse"]:
                voce["commesse"].append(caso["nome"])
    return [v for v in visti.values() if len(v["commesse"]) >= 2][:5]


def esperienza_punti() -> dict:
    """Punti proposti dall'AI nei kickoff passati: quali sono stati tenuti e quali scartati."""
    try:
        from ai_assistant.apprendimento import stesso_valore
        from ai_assistant.models import AiProposta

        righe = AiProposta.objects.filter(modulo=MODULO, azione=AZIONE).exclude(esito__in=[AiProposta.IN_ATTESA, AiProposta.SUPERATA])[:40]
    except Exception:  # noqa: BLE001
        return {"tenuti": [], "scartati": []}
    tenuti, scartati = [], []
    for riga in righe:
        finali = riga.decisione.get("punti") or []
        for punto in riga.proposta.get("punti") or []:
            (tenuti if any(stesso_valore(punto, f) for f in finali) else scartati).append(punto)
    return {"tenuti": tenuti[:8], "scartati": scartati[:8]}


def contesto(project, meeting, simili: list[dict]) -> str:
    righe = [
        f"Commessa: {project.name} · cliente {project.client_name or 'n.d.'} · P/N {project.part_number or 'n.d.'} · fase {project.get_phase_display()}",
        f"Descrizione: {(project.description or '(nessuna)')[:600]}",
        f"Incontro n. {meeting.numero}" + (f" «{meeting.titolo}»" if meeting.titolo else "") + ".",
        "Punti già in agenda: " + ("; ".join(str(i.get('titolo')) for i in (meeting.agenda_items or []) if isinstance(i, dict)) or "nessuno"),
        "Problemi aperti di questa commessa: " + ("; ".join(i.title for i in project.meeting_issues.filter(status="OPEN")[:6]) or "nessuno"),
        "COMMESSE SIMILI GIÀ FATTE:" if simili else "COMMESSE SIMILI: nessuna.",
    ]
    for caso in simili:
        problemi = "; ".join(f"{p['titolo']} ({'risolto' if p['risolto'] else 'aperto'})" for p in caso["problemi"]) or "nessuno"
        righe.append(f"- {caso['nome']} ({', '.join(caso['motivi']) or 'descrizione simile'}): problemi emersi: {problemi}"
                     + (f"; decisioni: {'; '.join(caso['decisioni'])}" if caso["decisioni"] else "")
                     + (f"; azioni rimaste aperte: {'; '.join(caso['azioni_aperte'])}" if caso["azioni_aperte"] else "")
                     + (f"; attività slittate: {'; '.join(caso['slittamenti'])}" if caso["slittamenti"] else "")
                     + (f"; rischi VRF alti: {'; '.join(caso['rischi'])}" if caso["rischi"] else ""))
    ricorrenti = punti_ricorrenti(simili)
    if ricorrenti:
        righe.append("PROBLEMI RICORRENTI (emersi in più commesse simili, vanno affrontati subito): " + "; ".join(r["titolo"] for r in ricorrenti))
    esperienza = esperienza_punti()
    if esperienza["tenuti"]:
        righe.append("Punti proposti in passato e TENUTI dai responsabili: " + "; ".join(esperienza["tenuti"]))
    if esperienza["scartati"]:
        righe.append("Punti proposti in passato e SCARTATI (non riproporli in forma simile): " + "; ".join(esperienza["scartati"]))
    return "\n".join(righe)[:7000]


ISTRUZIONI = (
    "Sei il project manager di un'officina meccanica di precisione che prepara un incontro di KICK-OFF di commessa. "
    "Dal contesto proponi da 3 a 6 punti per l'ordine del giorno che evitino di ripetere i problemi già visti nelle "
    "commesse simili. Rispondi SOLO con JSON: lista di oggetti {\"titolo\": massimo 80 caratteri, \"nota\": una frase "
    "con il fatto dello storico che lo giustifica (commessa e problema), \"durata_minuti\": 5-30}. Prima i problemi "
    "ricorrenti, poi attività slittate e rischi alti. Non ripetere punti già in agenda né punti già scartati in passato. "
    "Non inventare fatti."
)


def proponi_punti(project, meeting, *, user=None) -> dict:
    simili = commesse_simili(project)
    raw = ""
    try:
        from ai_assistant.services import chat_with_ollama

        raw = getattr(chat_with_ollama(ISTRUZIONI, runtime_context=contesto(project, meeting, simili), timeout=120), "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("copilota kickoff: AI non disponibile: %s", exc)
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    try:
        dati = json.loads(match.group(0)) if match else []
    except Exception:  # noqa: BLE001
        dati = []
    gia = {str(i.get("titolo") or "").strip().casefold() for i in (meeting.agenda_items or []) if isinstance(i, dict)}
    punti = []
    for voce in dati if isinstance(dati, list) else []:
        if not isinstance(voce, dict):
            continue
        titolo = str(voce.get("titolo") or "").strip()[:200]
        if not titolo or titolo.casefold() in gia:
            continue
        try:
            durata = int(voce.get("durata_minuti") or 0)
        except (TypeError, ValueError):
            durata = 0
        punti.append({"titolo": titolo, "nota": str(voce.get("nota") or "").strip()[:400], "durata_minuti": durata if 0 < durata <= 120 else None})
    proposta = {
        "ai_disponibile": bool(raw),
        "punti": punti[:6],
        "simili": simili,
        "ricorrenti": punti_ricorrenti(simili),
    }
    try:
        from ai_assistant.apprendimento import lezioni, registra_proposta

        if punti:
            registra_proposta(modulo=MODULO, azione=AZIONE, oggetto_ref=meeting.pk, proposta={"punti": [p["titolo"] for p in punti]}, user=user)
        proposta["apprendimento"] = lezioni(MODULO, AZIONE)
    except Exception:  # noqa: BLE001
        proposta["apprendimento"] = None
    return proposta


def registra_esito(meeting, user=None) -> None:
    """Minuta approvata: quali punti proposti sono rimasti nell'ordine del giorno."""
    try:
        from ai_assistant.apprendimento import registra_decisione

        finali = [str(i.get("titolo") or "") for i in (meeting.agenda_items or []) if isinstance(i, dict) and i.get("titolo")]
        registra_decisione(modulo=MODULO, azione=AZIONE, oggetto_ref=meeting.pk, decisione={"punti": finali}, user=user)
    except Exception:  # noqa: BLE001
        logger.exception("Esito copilota kickoff non registrato")
