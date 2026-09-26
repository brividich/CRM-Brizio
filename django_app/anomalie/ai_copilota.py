"""Copilota AI per le anomalie / segnalazioni (Fase 2 - A3).

Usa l'AI on-premise gia' integrata nel portale (``ai_assistant.services
.chat_with_ollama``, Ollama). Dal testo di una segnalazione (descrizione) propone
in **triage**: stato superficie, se serve aprire un RDC / segnalare al cliente,
avanzamento suggerito e una bozza riformulata della descrizione.

VINCOLO INVALICABILE: l'AI **propone**, l'operatore rivede e firma. Questo modulo
non scrive nulla nel DB e non esegue transizioni: ogni output ha ``proposto=True``.
Tutto **fail-safe** (AI offline => proposta vuota, ``ai_disponibile=False``).

I valori proposti sono **validati** contro le liste reali del modulo
(``stati_superficie`` / ``avanzamenti`` da ``_load_anomalie_lists``): valori fuori
lista vengono scartati (campo vuoto), mai inventati.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("anomalie copilota AI non disponibile: %s", exc)
        return ""


def _parse_json_obj(raw: str) -> dict:
    """Estrae il primo oggetto JSON dal testo del modello (tollerante)."""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    blob = m.group(0) if m else raw
    try:
        data = json.loads(blob)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def proponi_triage_anomalia(*, descrizione: str, stati_superficie, avanzamenti) -> dict:
    """Proposta di triage dal testo della segnalazione. Sola lettura, niente DB.

    Args:
        descrizione: testo libero della segnalazione/anomalia.
        stati_superficie: iterabile di etichette ammesse (vocabolario controllato).
        avanzamenti: iterabile di etichette di avanzamento ammesse.
    """
    stati = [str(s).strip() for s in (stati_superficie or []) if str(s).strip()]
    avanz = [str(a).strip() for a in (avanzamenti or []) if str(a).strip()]
    stati_validi = {s.casefold(): s for s in stati}
    avanz_validi = {a.casefold(): a for a in avanz}

    stati_lines = "\n".join(f"- {s}" for s in stati) or "(nessuno)"
    avanz_lines = "\n".join(f"- {a}" for a in avanz) or "(nessuno)"

    prompt = (
        "Sei un assistente qualita' di produzione. Analizza la segnalazione di anomalia e "
        "proponi il triage come SOLO JSON (nessun testo fuori dal JSON), con queste chiavi:\n"
        '  "stato_superficie": una delle ETICHETTE elencate sotto (o stringa vuota se incerto),\n'
        '  "avanzamento": una delle ETICHETTE di avanzamento elencate (o stringa vuota),\n'
        '  "serve_rdc": true/false (true SOLO se l\'anomalia richiede di aprire un RDC o '
        "segnalare al cliente: pezzo non conforme, fuori tolleranza, difetto bloccante),\n"
        '  "bozza_descrizione": riformulazione chiara e sintetica della segnalazione,\n'
        '  "motivazione": una frase sul perche\' della proposta.\n\n'
        f"STATI SUPERFICIE AMMESSI:\n{stati_lines}\n\n"
        f"AVANZAMENTI AMMESSI:\n{avanz_lines}\n\n"
        f"SEGNALAZIONE\n{(descrizione or '').strip()[:3000]}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota anomalie: proposta di triage, l'operatore rivede e firma.",
    )
    data = _parse_json_obj(raw)

    stato = stati_validi.get(str(data.get("stato_superficie") or "").strip().casefold(), "")
    avanzamento = avanz_validi.get(str(data.get("avanzamento") or "").strip().casefold(), "")
    serve_rdc = bool(data.get("serve_rdc"))
    bozza = str(data.get("bozza_descrizione") or "").strip()[:1500]
    motivazione = str(data.get("motivazione") or "").strip()[:500]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "stato_superficie": stato,
        "avanzamento": avanzamento,
        "serve_rdc": serve_rdc,
        "bozza_descrizione": bozza,
        "motivazione": motivazione,
    }


# ── Classificazione qualita' (tipo difetto / gravita' / causa probabile) ────

_STOPWORDS = {
    "della", "delle", "dello", "degli", "sulla", "sulle", "nella", "nelle", "questo",
    "questa", "sono", "stato", "stata", "come", "anche", "dopo", "prima", "pezzo",
    "pezzi", "anomalia", "presenta", "presente", "rilevato", "rilevata",
}


def _tokens(testo: str) -> set[str]:
    parole = re.findall(r"[a-zà-ù0-9]+", (testo or "").lower())
    return {p for p in parole if len(p) >= 4 and p not in _STOPWORDS}


def casi_simili(*, descrizione: str, part_number: str = "", escludi_anomalia_id=None,
                limite: int = 5, candidati: int = 300) -> list[dict]:
    """Anomalie gia' classificate con descrizione simile (sovrapposizione di parole,
    +0.3 se stesso P/N). Nessun embedding: veloce, deterministico, fail-safe."""
    try:
        from .automazioni_service import _anomalie_cols, _fetch, _text
        from .quality_models import AnomaliaSchedaQualita

        schede = list(
            AnomaliaSchedaQualita.objects.filter(tipo_difetto__isnull=False)
            .exclude(anomalia_id=escludi_anomalia_id or 0)
            .select_related("tipo_difetto")
            .order_by("-id")[:candidati]
        )
        if not schede or "descrizione" not in _anomalie_cols():
            return []
        ids = [s.anomalia_id for s in schede]
        ph = ",".join(["%s"] * len(ids))
        testi = {
            int(r["id"]): str(r["d"] or "")
            for r in _fetch(f"SELECT id, {_text('descrizione')} AS d FROM anomalie WHERE id IN ({ph})", ids)
        }
    except Exception as exc:  # pragma: no cover - dipende dal DB legacy
        logger.debug("anomalie casi simili non disponibili: %s", exc)
        return []

    base = _tokens(descrizione)
    pn = (part_number or "").strip().lower()
    out = []
    for s in schede:
        testo = testi.get(s.anomalia_id, "")
        altri = _tokens(testo)
        score = (len(base & altri) / len(base | altri)) if (base and altri) else 0.0
        if pn and s.part_number.strip().lower() == pn:
            score += 0.3
        if score <= 0.05:
            continue
        out.append({
            "protocollo": s.protocollo,
            "tipo_difetto": s.tipo_difetto_id,
            "tipo_difetto_label": s.tipo_difetto.nome,
            "gravita": s.gravita,
            "disposizione": s.get_disposizione_display(),
            "part_number": s.part_number,
            "descrizione": testo.strip()[:160],
            "score": round(score, 2),
        })
    out.sort(key=lambda x: -x["score"])
    return out[:limite]


def proponi_classificazione_qualita(*, descrizione: str, note: str = "", part_number: str = "",
                                    anomalia_id=None, tipi_difetto, gravita) -> dict:
    """Propone tipo difetto, gravita' e causa probabile. Sola lettura, niente DB.

    Args:
        tipi_difetto: [(id, nome)] del catalogo attivo (vocabolario controllato).
        gravita: [(codice, etichetta)] ammessi.

    Se l'AI non risponde o non sceglie un difetto del catalogo, il difetto proposto
    e' il piu' frequente fra i casi simili (``fonte="simili"``).
    """
    tipi = [(int(i), str(n).strip()) for i, n in (tipi_difetto or []) if str(n).strip()]
    tipi_per_nome = {n.casefold(): i for i, n in tipi}
    grav_codici = [str(c).upper() for c, _ in (gravita or [])]
    grav_validi = {c.casefold(): c for c in grav_codici}
    grav_validi.update({str(l).casefold(): str(c).upper() for c, l in (gravita or [])})

    simili = casi_simili(descrizione=f"{descrizione}\n{note}", part_number=part_number,
                         escludi_anomalia_id=anomalia_id)

    tipi_lines = "\n".join(f"- {n}" for _, n in tipi) or "(nessuno)"
    grav_lines = "\n".join(f"- {c}" for c in grav_codici) or "(nessuno)"
    simili_lines = "\n".join(
        f"- {c['protocollo']}: {c['tipo_difetto_label']} (gravita' {c['gravita'] or 'n.d.'}, "
        f"{c['disposizione']}) - {c['descrizione']}"
        for c in simili
    ) or "(nessuno)"
    prompt = (
        "Sei un assistente qualita' di un'officina meccanica di precisione (ISO 9001 / EN 9100). "
        "Classifica la non conformita' e rispondi SOLO con JSON (nessun testo fuori), chiavi:\n"
        '  "tipo_difetto": una delle ETICHETTE del catalogo sotto (o stringa vuota se incerto),\n'
        '  "gravita": uno dei CODICI di gravita\' sotto (o stringa vuota),\n'
        '  "causa_probabile": ipotesi breve sulla causa (metodo, macchina, materiale, '
        "misura, operatore, ambiente); e' un'ipotesi da verificare, non una conclusione,\n"
        '  "motivazione": una frase sul perche\' della proposta.\n\n'
        "Gravita': MINORE = non compromette funzione o sicurezza; MAGGIORE = compromette la "
        "funzione o richiede deroga del cliente; CRITICA = rischio per la sicurezza.\n\n"
        f"CATALOGO DIFETTI:\n{tipi_lines}\n\nCODICI GRAVITA':\n{grav_lines}\n\n"
        f"CASI SIMILI GIA' CLASSIFICATI:\n{simili_lines}\n\n"
        f"SEGNALAZIONE\n{(descrizione or '').strip()[:3000]}\n"
        f"NOTE\n{(note or '').strip()[:1500]}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota anomalie: classificazione qualita', l'operatore rivede e conferma.",
    )
    data = _parse_json_obj(raw)

    tipo_id = tipi_per_nome.get(str(data.get("tipo_difetto") or "").strip().casefold())
    fonte = "ai"
    if tipo_id is None and simili:
        conteggi: dict[int, int] = {}
        for c in simili:
            conteggi[c["tipo_difetto"]] = conteggi.get(c["tipo_difetto"], 0) + 1
        tipo_id = max(conteggi, key=conteggi.get)
        fonte = "simili"

    return {
        "proposto": True,
        "fonte": fonte,
        "ai_disponibile": bool(raw),
        "tipo_difetto": tipo_id,
        "gravita": grav_validi.get(str(data.get("gravita") or "").strip().casefold(), ""),
        "causa_probabile": str(data.get("causa_probabile") or "").strip()[:600],
        "motivazione": str(data.get("motivazione") or "").strip()[:500],
        "simili": simili,
    }
