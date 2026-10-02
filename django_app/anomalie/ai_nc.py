"""Copilota AI per l'analisi delle non conformita' che impara dallo storico.

Prima di proporre, cerca le NC gia' lavorate con lo stesso P/N, gli stessi tipi di difetto o
descrizioni simili e ne riporta l'esito vero: causa radice, azioni fatte e soprattutto la
**verifica di efficacia** (efficace / non efficace) e se la NC si e' poi ripresentata
(ricaduta). L'AI riparte da cio' che ha funzionato ed evita cio' che non ha funzionato; in piu'
legge come le persone hanno trattato le sue proposte precedenti (``ai_assistant.apprendimento``).

VINCOLO: propone soltanto. Niente viene salvato nella NC finche' la persona non preme «Salva».
"""
from __future__ import annotations

import json
import logging
import re

from django.db.models import Q

logger = logging.getLogger(__name__)

MODULO = "anomalie"
AZIONE_CAUSA = "nc_causa_radice"
AZIONE_AZIONI = "nc_azioni"
_STOP = {"della", "delle", "dello", "degli", "sulla", "sulle", "nella", "nelle", "questo", "questa", "sono", "stato", "stata",
         "come", "anche", "dopo", "prima", "pezzo", "pezzi", "anomalia", "presenta", "presente", "rilevato", "rilevata"}


def _tokens(testo: str) -> set[str]:
    return {p for p in re.findall(r"[a-zà-ù0-9]+", (testo or "").lower()) if len(p) >= 4 and p not in _STOP}


def _descrizioni(ncs) -> dict[int, str]:
    """Testo delle anomalie di ogni NC (descrizione + note), letto in un colpo solo dalla tabella legacy."""
    try:
        from .qualita_service import legacy_rows

        schede = [(nc.pk, s.anomalia_id) for nc in ncs for s in nc.schede.all()]
        righe = legacy_rows([anomalia_id for _, anomalia_id in schede]) if schede else {}
    except Exception:  # noqa: BLE001 - tabella legacy assente o non leggibile: si lavora senza testi
        logger.debug("descrizioni anomalie non disponibili", exc_info=True)
        return {}
    testi: dict[int, list[str]] = {}
    for nc_pk, anomalia_id in schede:
        riga = righe.get(anomalia_id) or {}
        testi.setdefault(nc_pk, []).append(f"{riga.get('descrizione') or ''} {riga.get('note_capocommessa') or ''}".strip())
    return {pk: " ".join(t for t in parti if t)[:1500] for pk, parti in testi.items()}


def _tipi(nc) -> set[str]:
    return {s.tipo_difetto.nome for s in nc.schede.all() if s.tipo_difetto_id}


def nc_simili(nc, *, limite: int = 5, candidati: int = 300) -> list[dict]:
    """NC gia' analizzate simili a questa, con il loro esito. Deterministico, nessuna AI."""
    from .quality_models import AnomaliaNC as NC

    qs = (NC.objects.exclude(pk=nc.pk).filter(Q(causa_radice__gt="") | Q(azioni__isnull=False)).distinct()
          .prefetch_related("azioni", "schede__tipo_difetto", "ricadute").order_by("-id")[:candidati])
    altre = list(qs)
    if not altre:
        return []
    testi = _descrizioni([nc, *altre])
    base = _tokens(testi.get(nc.pk, "")) | {t.lower() for t in _tipi(nc)}
    pn = (nc.part_number or "").strip().lower()
    tipi = _tipi(nc)
    out = []
    for other in altre:
        parole = _tokens(testi.get(other.pk, "") + " " + (other.causa_radice or "")) | {t.lower() for t in _tipi(other)}
        score = len(base & parole) / len(base | parole) if base and parole else 0.0
        motivi = []
        if pn and (other.part_number or "").strip().lower() == pn:
            score += 0.4
            motivi.append("stesso P/N")
        comuni = tipi & _tipi(other)
        if comuni:
            score += 0.2
            motivi.append("stesso difetto: " + ", ".join(sorted(comuni)))
        if other.op_titolo.strip().lower() == nc.op_titolo.strip().lower():
            score += 0.2
            motivi.append("stesso OP")
        if score < 0.15:
            continue
        azioni = [a for a in other.azioni.all() if a.stato != a.Stato.ANNULLATA]
        ricaduta = any(True for _ in other.ricadute.all())
        out.append({
            "pk": other.pk,
            "protocollo": other.protocollo,
            "part_number": other.part_number,
            "motivi": motivi,
            "causa_radice": (other.causa_radice or "").strip()[:300],
            "azioni": [{"descrizione": a.descrizione.strip()[:200], "stato": a.get_stato_display(), "esito": (a.esito or "").strip()[:150]}
                       for a in azioni[:5]],
            "verifica": other.get_verifica_esito_display() if other.verifica_esito else "",
            "efficace": other.verifica_esito == NC.Esito.EFFICACE,
            "non_efficace": other.verifica_esito == NC.Esito.NON_EFFICACE,
            "ricaduta": ricaduta,
            "score": round(score, 2),
        })
    out.sort(key=lambda r: -r["score"])
    return out[:limite]


def _esito_testo(caso: dict) -> str:
    if caso["non_efficace"]:
        return "azioni NON EFFICACI alla verifica"
    if caso["ricaduta"]:
        return "si è RIPRESENTATA dopo la chiusura"
    if caso["efficace"]:
        return "azioni EFFICACI alla verifica"
    return "efficacia non ancora verificata"


def azioni_da_riusare(simili: list[dict], limite: int = 4) -> list[dict]:
    """Azioni fatte su NC simili la cui verifica di efficacia e' positiva e che non si sono ripresentate."""
    out, viste = [], set()
    for caso in simili:
        if not caso["efficace"] or caso["ricaduta"]:
            continue
        for azione in caso["azioni"]:
            chiave = azione["descrizione"].casefold()
            if azione["stato"].lower() == "fatta" and chiave not in viste:
                viste.add(chiave)
                out.append({"descrizione": azione["descrizione"], "protocollo": caso["protocollo"], "causa": caso["causa_radice"]})
    return out[:limite]


def contesto_nc(nc, simili: list[dict]) -> str:
    """La NC e il suo storico in righe di testo: niente nomi di persone, solo fatti tecnici."""
    testi = _descrizioni([nc])
    righe = [
        f"NC {nc.protocollo} · OP {nc.op_titolo} · P/N {nc.part_number or 'n.d.'}" + (f" · ricaduta di {nc.precedente.protocollo}" if nc.precedente_id else ""),
        "Tipi di difetto: " + (", ".join(sorted(_tipi(nc))) or "non classificati"),
        "Descrizione delle anomalie: " + (testi.get(nc.pk) or "(nessuna)"),
    ]
    if nc.contenimento:
        righe.append(f"Contenimento già fatto: {nc.contenimento[:500]}")
    if nc.causa_radice:
        righe.append(f"Causa radice già scritta: {nc.causa_radice[:500]}")
    if nc.precedente_id:
        prec = nc.precedente
        righe.append(f"Questa NC è una ricaduta di {prec.protocollo}: allora la causa indicata fu «{(prec.causa_radice or 'n.d.')[:200]}» "
                     "e il problema si è ripresentato, quindi quella causa era probabilmente SBAGLIATA. Cerca un'altra causa, "
                     "partendo dalle azioni risultate efficaci su NC simili.")
    righe.append("NC SIMILI GIÀ LAVORATE (con l'esito reale):" if simili else "NC SIMILI GIÀ LAVORATE: nessuna.")
    for caso in simili:
        azioni = "; ".join(f"{a['descrizione']} [{a['stato']}{', esito: ' + a['esito'] if a['esito'] else ''}]" for a in caso["azioni"]) or "nessuna azione"
        righe.append(f"- {caso['protocollo']} ({', '.join(caso['motivi']) or 'descrizione simile'}): causa «{caso['causa_radice'] or 'n.d.'}»; "
                     f"azioni: {azioni}; {_esito_testo(caso)}.")
    riuso = azioni_da_riusare(simili)
    if riuso:
        righe.append("DA RIUSARE (azioni risultate EFFICACI su NC simili, proponile per prime se il difetto è lo stesso):")
        righe += [f"- {a['descrizione']} (da {a['protocollo']}, causa: {a['causa'] or 'n.d.'})" for a in riuso]
    escluse = [c for c in simili if c["non_efficace"] or c["ricaduta"]]
    if escluse:
        righe.append("DA NON RIPROPORRE (cause e azioni che NON hanno funzionato):")
        righe += [f"- {c['protocollo']}: causa «{c['causa_radice'] or 'n.d.'}», azioni: " + "; ".join(a["descrizione"] for a in c["azioni"])
                  for c in escluse]
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lezioni = lezioni_testo(MODULO, AZIONE_CAUSA)
        if lezioni:
            righe.append(lezioni)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(righe)[:7000]


ISTRUZIONI = (
    "Sei un ingegnere qualità di un'officina meccanica di precisione (ISO 9001 / EN 9100). Dal contesto proponi l'analisi "
    "della non conformità. Rispondi SOLO con JSON, chiavi: \"perche\" (lista di 5 frasi brevi, catena dei 5 perché dal "
    "sintomo alla causa), \"causa_radice\" (una o due frasi), \"azioni\" (lista di massimo 4 oggetti {\"descrizione\": "
    "frase all'infinito, \"tipo\": \"CORRETTIVA\" o \"PREVENTIVA\", \"da_storico\": protocollo della NC simile da cui la "
    "riprendi oppure \"\"}), \"motivazione\" (una frase). Regole, in ordine: 1) se c'è la sezione DA RIUSARE e il difetto è "
    "lo stesso, la causa radice e la prima azione vanno prese da lì; 2) la sezione DA NON RIPROPORRE elenca cause e azioni "
    "che non hanno funzionato: non usarle come causa radice; 3) se è una ricaduta, la causa trovata la volta prima era "
    "sbagliata. È un'ipotesi da verificare: non inventare misure o dati."
)


def _json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    try:
        data = json.loads(match.group(0) if match else raw)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def proponi_analisi_nc(nc, *, user=None) -> dict:
    """Proposta di 5 perché, causa radice e azioni. Non scrive nulla nella NC."""
    from .quality_models import AnomaliaNCAzione

    simili = nc_simili(nc)
    contesto = contesto_nc(nc, simili)
    raw = ""
    try:
        from ai_assistant.services import chat_with_ollama

        raw = getattr(chat_with_ollama(ISTRUZIONI, runtime_context=contesto, timeout=120), "content", "") or ""
    except Exception as exc:  # noqa: BLE001 - AI spenta: restano i casi simili
        logger.info("copilota NC: AI non disponibile: %s", exc)
    data = _json(raw)
    tipi = dict(AnomaliaNCAzione.Tipo.choices)
    protocolli = {c["protocollo"] for c in simili}
    perche = [str(p).strip()[:300] for p in (data.get("perche") or []) if str(p).strip()][:5] if isinstance(data.get("perche"), list) else []
    azioni = []
    for item in data.get("azioni") or []:
        if not isinstance(item, dict) or not str(item.get("descrizione") or "").strip():
            continue
        tipo = str(item.get("tipo") or "").upper()
        origine = str(item.get("da_storico") or "").strip()
        azioni.append({
            "descrizione": str(item["descrizione"]).strip()[:500],
            "tipo": tipo if tipo in tipi else AnomaliaNCAzione.Tipo.CORRETTIVA,
            "da_storico": origine if origine in protocolli else "",
        })
    proposta = {
        "proposto": True,
        "ai_disponibile": bool(raw),
        "perche": perche,
        "causa_radice": str(data.get("causa_radice") or "").strip()[:800],
        "azioni": azioni[:4],
        "motivazione": str(data.get("motivazione") or "").strip()[:400],
        "simili": simili,
        "riuso": azioni_da_riusare(simili),
    }
    try:
        from ai_assistant.apprendimento import lezioni, registra_proposta

        if proposta["causa_radice"]:
            registra_proposta(modulo=MODULO, azione=AZIONE_CAUSA, oggetto_ref=nc.pk, proposta={"causa_radice": proposta["causa_radice"]}, user=user)
        if azioni:
            registra_proposta(modulo=MODULO, azione=AZIONE_AZIONI, oggetto_ref=nc.pk,
                              proposta={"azioni": [a["descrizione"] for a in azioni]}, user=user)
        proposta["apprendimento"] = lezioni(MODULO, AZIONE_CAUSA)
    except Exception:  # noqa: BLE001
        proposta["apprendimento"] = None
    return proposta


def registra_esito_analisi(nc, user=None) -> None:
    """Dopo «Salva analisi»: la causa radice scritta e' quella proposta, corretta o un'altra?"""
    from ai_assistant.apprendimento import registra_decisione

    if nc.causa_radice:
        registra_decisione(modulo=MODULO, azione=AZIONE_CAUSA, oggetto_ref=nc.pk, decisione={"causa_radice": nc.causa_radice}, user=user)


def registra_esito_azioni(nc, user=None) -> None:
    """Alla verifica: le azioni realmente fatte coincidono con quelle proposte?"""
    from ai_assistant.apprendimento import registra_decisione

    fatte = [a.descrizione for a in nc.azioni.all() if a.stato != a.Stato.ANNULLATA]
    if fatte:
        registra_decisione(modulo=MODULO, azione=AZIONE_AZIONI, oggetto_ref=nc.pk, decisione={"azioni": fatte}, user=user)
