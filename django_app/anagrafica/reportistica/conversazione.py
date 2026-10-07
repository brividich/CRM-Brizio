"""Report a conversazione: si chiede il report a parole, il portale lo compone.

L'AI **non scrive query e non vede dati del personale**: legge la richiesta e il
catalogo delle sezioni consentite all'utente e propone una *specifica* (quali
sezioni, colonne, opzioni, perimetro, periodo). La specifica viene poi validata
qui, voce per voce, contro il catalogo: tutto cio' che non esiste o non e'
consentito viene scartato e detto all'utente. I numeri li calcola sempre lo
stesso motore dei modelli salvati (:mod:`.motore`), con gli stessi permessi per
sezione, lo stesso archivio e lo stesso AuditLog.

Conseguenze volute:
- una richiesta «furba» nel testo (prompt injection) puo' al massimo scegliere
  sezioni che l'utente potrebbe comunque generare a mano;
- senza AI (Ollama spento) un interprete a parole chiave copre i casi comuni;
- ogni documento scaricato registra la specifica finale: le correzioni delle
  persone diventano lezioni per le proposte successive (``ai_assistant.apprendimento``).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from core import naming

from . import sezioni as catalogo
from .dati import Perimetro

logger = logging.getLogger(__name__)

MODULO_AI = "reportistica"
AZIONE_AI = "conversazione"
MAX_SEZIONI = 8
MAX_MESSAGGIO = 1500
MAX_STORICO = 12

PERIODI = {
    "ULTIMI_12_MESI": "Ultimi 12 mesi",
    "ANNO_CORRENTE": "Anno in corso",
    "ANNO_PRECEDENTE": "Anno precedente",
    "TRIMESTRE_PRECEDENTE": "Trimestre precedente",
    "MESE_PRECEDENTE": "Mese precedente",
    "PERSONALIZZATO": "Date personalizzate",
}
_CAMPI_PERIMETRO = ("reparti", "aree", "mansioni", "contratti", "livelli", "qualifiche")


def specifica_vuota() -> dict:
    return {
        "titolo": "", "destinatario": "", "formato": "pdf",
        "periodo": {"tipo": "ULTIMI_12_MESI", "da": "", "a": ""},
        "perimetro": {"includi_cessati": False, "persone": []},
        "sezioni": [],
    }


@dataclass
class Esito:
    specifica: dict
    risposta: str
    avvisi: list[str] = field(default_factory=list)
    ai: bool = True


# ═══════════════════════════════════════════════════════════════════════════
# Catalogo per l'AI
# ═══════════════════════════════════════════════════════════════════════════

def _scelte_compatte(scelte: list[tuple[str, str]], limite: int = 60) -> list[str]:
    voci = [k if k == v else f"{k}={v}" for k, v in scelte]
    return voci[:limite] + ([f"... altre {len(voci) - limite}"] if len(voci) > limite else [])


# Opzioni di sola impaginazione: l'utente le regola dal modello, all'AI non servono.
_OPZIONI_SOLO_IMPAGINAZIONE = ("ordine", "nascondi_se_vuota")


def catalogo_per_ai(request, scelte_perimetro: dict, *, limite: int = 60) -> dict:
    """Le sezioni che l'utente puo' generare, con colonne e opzioni: niente dati personali."""
    sezioni = []
    for s in catalogo.catalogo():
        if not s.consentita(request):
            continue
        voce = {"chiave": s.key, "titolo": s.titolo, "descrizione": s.descrizione[:160]}
        if s.colonne and not s.colonne_dinamiche:
            # Con l'etichetta: «voce» o «codice» da sole non dicono all'AI che cosa contengono.
            voce["colonne"] = _scelte_compatte(list(s.colonne), 100)
        opzioni = {}
        for o in s.tutte_le_opzioni():
            if o.nome in _OPZIONI_SOLO_IMPAGINAZIONE:
                continue
            descr = {"tipo": o.tipo}
            if o.nome in ("ordina_per", "raggruppa_per"):
                descr["valori"] = "una delle colonne, vuoto = nessuno"  # non ripete l'elenco colonne
            elif o.tipo in (catalogo.SCELTA, catalogo.MULTI):
                descr["valori"] = _scelte_compatte(o.elenco_scelte(), limite)
            if o.predefinito not in (None, "", [], ()):
                descr["predefinito"] = list(o.predefinito) if isinstance(o.predefinito, tuple) else o.predefinito
            opzioni[o.nome] = descr
        voce["opzioni"] = opzioni
        if not s.usa_perimetro:
            voce["nota"] = "tutta l'azienda, ignora il perimetro"
        sezioni.append(voce)
    return {
        "sezioni": sezioni,
        "perimetro": {
            "reparti": [v for _k, v in scelte_perimetro.get("reparti", [])],
            "aree": [v for _k, v in scelte_perimetro.get("aree", [])][:limite * 2],
            "mansioni": [v for _k, v in scelte_perimetro.get("mansioni", [])][:limite * 2],
            "contratti": [f"{k}={v}" for k, v in scelte_perimetro.get("contratti", [])],
            "qualifiche": [v for _k, v in scelte_perimetro.get("qualifiche", [])][:limite * 2],
        },
        "periodi": PERIODI,
    }


ISTRUZIONI = (
    "Sei l'assistente della reportistica del personale di un'azienda manifatturiera. "
    "Traduci la richiesta dell'utente nella SPECIFICA di un report usando SOLO le sezioni, le colonne, "
    "le opzioni e i valori del CATALOGO nel contesto. Non inventare sezioni né valori. "
    "Se l'utente chiede di modificare il report in corso, parti dalla SPECIFICA ATTUALE e cambia solo ciò che chiede. "
    "Rispondi SOLO con un oggetto JSON, senza testo prima o dopo, con questa forma: "
    '{"risposta": "una o due frasi in italiano che dicono cosa hai preparato o cosa manca", '
    '"specifica": {"titolo": "...", "destinatario": "", "formato": "pdf|xlsx", '
    '"periodo": {"tipo": "una chiave di periodi", "da": "AAAA-MM-GG o vuoto", "a": "AAAA-MM-GG o vuoto"}, '
    '"perimetro": {"reparti": [], "aree": [], "mansioni": [], "contratti": [], "qualifiche": [], '
    '"persone": ["COGNOME NOME"], "includi_cessati": false}, '
    '"sezioni": [{"sezione": "chiave", "colonne": ["chiavi colonna, vuoto = predefinite"], '
    '"opzioni": {"nome_opzione": valore}}]}}. '
    "Nei valori del catalogo «CHIAVE=Etichetta», scrivi solo la CHIAVE. "
    "Metti SOLO ciò che l'utente chiede: perimetro vuoto se non nomina reparti, aree, mansioni, contratti, "
    "qualifiche o persone; opzioni non nominate assenti (valgono i predefiniti); periodo PERSONALIZZATO solo "
    "con date esplicite. «matrice» = sezioni matrice_formazione o matrice_qualifiche (la matrice formazione ha "
    "l'opzione solo_sicurezza). "
    "«raggruppato/raggruppate per X» = opzione raggruppa_per con la colonna X; «ordinato per X» = ordina_per. "
    "Regole: «scaduti/scadute» = opzione stati con i valori di scadenza; «in Excel» = formato xlsx; "
    "«anno scorso» = ANNO_PRECEDENTE; persone e reparti vanno nel perimetro, non nelle opzioni; "
    "i numeri in perimetro.persone sono persone già scelte: conservali se l'utente non chiede di cambiarle. "
    "Colonne: scrivi la CHIAVE della colonna; in un elenco di persone metti sempre la colonna del nominativo. "
    "Ore di formazione per persona («dipendenti con meno di N ore», «chi ha fatto almeno N ore») = sezione "
    "formazione_erogata con opzioni dettaglio=persona, confronto_ore (meno_di, al_massimo, almeno, piu_di) e "
    "soglia_ore=N. Un anno solare («nel 2026») = ANNO_CORRENTE se è l'anno in corso, ANNO_PRECEDENTE se è "
    "il precedente, altrimenti PERSONALIZZATO dal 1° gennaio al 31 dicembre. "
    "Se la richiesta non è chiara, lascia sezioni vuote e chiedi in «risposta» cosa serve."
)


# ═══════════════════════════════════════════════════════════════════════════
# Validazione della specifica (qualunque sia la fonte)
# ═══════════════════════════════════════════════════════════════════════════

def _testo(valore, limite: int = 200) -> str:
    return re.sub(r"\s+", " ", str(valore or "")).strip()[:limite]


def _lista(valore) -> list:
    if valore is None or valore == "":
        return []
    return list(valore) if isinstance(valore, (list, tuple)) else [valore]


def _data(valore) -> date | None:
    try:
        return date.fromisoformat(str(valore)[:10]) if valore else None
    except ValueError:
        return None


def _abbina(valori, scelte: list[tuple[str, str]], cosa: str, avvisi: list[str]) -> list[str]:
    """Valori proposti -> chiavi valide, accettando chiave o etichetta (maiuscole/accenti indifferenti)."""
    per_chiave = {naming.chiave_testo(k): k for k, _l in scelte}
    per_etichetta = {naming.chiave_testo(lab): k for k, lab in scelte}
    out: list[str] = []
    for v in _lista(valori):
        chiave = naming.chiave_testo(str(v))
        # Anche la chiave vuota («— nessuno —») e' un valore valido: niente ``or``.
        trovato = per_chiave[chiave] if chiave in per_chiave else per_etichetta.get(chiave)
        if trovato is None and "=" in str(v):
            # L'AI ricopia spesso la voce del catalogo cosi' com'e': «CHIAVE=Etichetta».
            sinistra, destra = (naming.chiave_testo(x) for x in str(v).split("=", 1))
            trovato = per_chiave.get(sinistra, per_etichetta.get(destra))
        if trovato is None:
            if not chiave:
                continue  # voce vuota in un elenco: niente da segnalare

            avvisi.append(f"{cosa} «{_testo(v, 60)}» non trovato: ignorato.")
        elif trovato not in out:
            out.append(trovato)
    return out


def _opzioni_sezione(sezione, grezze, avvisi: list[str]) -> dict:
    grezze = grezze if isinstance(grezze, dict) else {}
    per_nome = {o.nome: o for o in sezione.tutte_le_opzioni()}
    out: dict = {}
    for nome, valore in grezze.items():
        o = per_nome.get(nome)
        if o is None:
            avvisi.append(f"Opzione «{_testo(nome, 40)}» non esiste in «{sezione.titolo}»: ignorata.")
            continue
        if o.tipo == catalogo.SCELTA and valore in ("", None):
            out[nome] = o.normalizza("")  # «— nessuno —» o predefinito: valore vuoto legittimo
            continue
        if o.tipo in (catalogo.SCELTA, catalogo.MULTI):
            scelte = o.elenco_scelte()
            chiavi = _abbina(valore, scelte, f"Valore di «{o.etichetta}»", avvisi)
            if (o.tipo == catalogo.MULTI and "vuoto = tutt" in o.aiuto.lower()
                    and scelte and set(chiavi) >= {k for k, _l in scelte}):
                chiavi = []  # «tutti i valori» e' il filtro vuoto: stessa cosa, detta come la dice il form
            valore = chiavi if o.tipo == catalogo.MULTI else (chiavi[0] if chiavi else "")
            if o.tipo == catalogo.SCELTA and not chiavi:
                continue
        elif o.tipo == catalogo.SI_NO and isinstance(valore, str):
            valore = naming.chiave_testo(valore) in ("SI", "YES", "VERO", "TRUE", "1", "ON")
        elif o.tipo == catalogo.INTERO and isinstance(valore, str):
            numero = re.search(r"\d+", valore)
            if numero is None:
                avvisi.append(f"«{o.etichetta}»: «{_testo(valore, 30)}» non è un numero, resta il predefinito.")
                continue
            valore = int(numero.group())
        out[nome] = o.normalizza(valore)
    return out


# Colonne che dicono di chi (o di che cosa) e' la riga, in ordine di preferenza.
_COLONNE_IDENTITA = ("voce", "nominativo")


def _colonne(sezione, grezze, avvisi: list[str]) -> list[str]:
    """Colonne proposte -> chiavi valide (chiave, etichetta o «chiave=Etichetta»).

    Una tabella senza la colonna che identifica la riga e' illeggibile (righe di sole
    ore o di soli reparti): se manca, si aggiunge in testa.
    """
    scelte = list(sezione.colonne)
    scartate: list[str] = []
    out = _abbina(grezze, scelte, "Colonna", scartate)
    if scartate:
        nomi = [m.split("«", 1)[1].split("»", 1)[0] for m in scartate if "«" in m]
        avvisi.append(f"Colonne non disponibili in «{sezione.titolo}»: {', '.join(nomi)}.")
    validi = dict(scelte)
    if out and not any(c in out for c in _COLONNE_IDENTITA):
        identita = next((c for c in _COLONNE_IDENTITA if c in validi), None)
        if identita:
            out.insert(0, identita)
    if "voce" in out and "nominativo" in out:
        out.remove("nominativo")  # stessa informazione due volte
    return out


def _persone(nomi, dipendenti, avvisi: list[str]) -> list[int]:
    """Nomi scritti dall'utente -> id. Ammette COGNOME NOME, NOME COGNOME, il solo cognome se
    univoco e gli id gia' validati (la specifica in corso li conserva come numeri)."""
    per_id = {d.id: d for d in dipendenti}
    indice: dict[str, list] = {}
    for d in dipendenti:
        parole = naming.chiave_testo(d.nominativo).split()
        for chiave in {" ".join(parole), " ".join(reversed(parole))} | ({parole[0]} if parole else set()):
            indice.setdefault(chiave, []).append(d)
    out: list[int] = []
    for nome in _lista(nomi):
        if isinstance(nome, int) or str(nome).strip().isdigit():
            pid = int(nome)
            if pid in per_id and pid not in out:
                out.append(pid)
            elif pid not in per_id:
                avvisi.append("Una persona scelta in precedenza non è più in anagrafica: tolta dal perimetro.")
            continue
        chiave = naming.chiave_testo(str(nome))
        trovati = {d.id: d for d in indice.get(chiave, [])}
        if len(trovati) == 1:
            pid = next(iter(trovati))
            if pid not in out:
                out.append(pid)
        elif not trovati:
            avvisi.append(f"Persona «{_testo(nome, 60)}» non trovata in anagrafica: ignorata.")
        else:
            avvisi.append(f"«{_testo(nome, 60)}» corrisponde a {len(trovati)} persone: indica nome e cognome.")
    return out


def normalizza_specifica(grezza, request, scelte_perimetro: dict, dipendenti) -> tuple[dict, list[str]]:
    """Specifica proposta (AI, interprete semplice o sessione) -> specifica valida + avvisi."""
    grezza = grezza if isinstance(grezza, dict) else {}
    avvisi: list[str] = []
    spec = specifica_vuota()
    spec["titolo"] = _testo(grezza.get("titolo"))
    spec["destinatario"] = _testo(grezza.get("destinatario"))
    spec["formato"] = "xlsx" if str(grezza.get("formato") or "").lower() in ("xlsx", "excel") else "pdf"

    periodo = grezza.get("periodo")
    periodo = periodo if isinstance(periodo, dict) else ({"tipo": periodo} if isinstance(periodo, str) else {})
    grezzo = periodo.get("tipo") or "ULTIMI_12_MESI"
    trovati = _abbina(grezzo, list(PERIODI.items()), "Periodo", [])  # chiave o etichetta
    tipo = trovati[0] if trovati else "ULTIMI_12_MESI"
    if not trovati:
        avvisi.append(f"Periodo «{_testo(grezzo, 40)}» non riconosciuto: uso gli ultimi 12 mesi.")
    da, a = _data(periodo.get("da")), _data(periodo.get("a"))
    periodo_incompleto = tipo == "PERSONALIZZATO" and not (da and a)
    if periodo_incompleto:
        tipo, da, a = "ULTIMI_12_MESI", None, None
    spec["periodo"] = {"tipo": tipo, "da": da.isoformat() if da and tipo == "PERSONALIZZATO" else "",
                       "a": a.isoformat() if a and tipo == "PERSONALIZZATO" else ""}

    perimetro = grezza.get("perimetro") if isinstance(grezza.get("perimetro"), dict) else {}
    etichette = {"reparti": "Reparto", "aree": "Area", "mansioni": "Mansione", "contratti": "Contratto",
                 "livelli": "Livello", "qualifiche": "Qualifica"}
    for campo in _CAMPI_PERIMETRO:
        scelte = scelte_perimetro.get(campo, [])
        valori = _abbina(perimetro.get(campo), scelte, etichette[campo], avvisi)
        # Un filtro con TUTTI i valori del catalogo non e' una scelta dell'utente: per i reparti
        # equivale a nessun filtro, per le qualifiche escluderebbe chi non ne ha. Si toglie.
        # Con meno di 3 valori nel catalogo «tutti» puo' essere una richiesta vera: si tiene.
        if valori and len(scelte) >= 3 and set(valori) >= {k for k, _l in scelte}:
            continue
        if valori:
            spec["perimetro"][campo] = valori
    spec["perimetro"]["persone"] = _persone(perimetro.get("persone"), dipendenti, avvisi)
    spec["perimetro"]["includi_cessati"] = perimetro.get("includi_cessati") in (True, "true", "si", "sì", 1, "1")

    for voce in _lista(grezza.get("sezioni"))[:MAX_SEZIONI]:
        voce = voce if isinstance(voce, dict) else {"sezione": voce}
        chiave = str(voce.get("sezione") or "").strip()
        sezione = catalogo.get(chiave)
        if sezione is None:
            avvisi.append(f"Sezione «{_testo(chiave, 60)}» non esiste: ignorata.")
            continue
        if not sezione.consentita(request):
            avvisi.append(f"«{sezione.titolo}»: non hai i permessi per questi dati, sezione omessa.")
            continue
        colonne = []
        if sezione.colonne and not sezione.colonne_dinamiche:
            colonne = _colonne(sezione, voce.get("colonne"), avvisi)
        spec["sezioni"].append({"sezione": chiave, "colonne": colonne,
                                "opzioni": _opzioni_sezione(sezione, voce.get("opzioni"), avvisi)})
    if len(_lista(grezza.get("sezioni"))) > MAX_SEZIONI:
        avvisi.append(f"Al massimo {MAX_SEZIONI} sezioni per documento: le altre sono state tralasciate.")
    if periodo_incompleto and any(catalogo.get(s["sezione"]).usa_periodo for s in spec["sezioni"]):
        # Solo se il periodo conta davvero per qualche sezione: altrimenti e' un dettaglio irrilevante.
        avvisi.append("Per le date personalizzate servono inizio e fine: uso gli ultimi 12 mesi.")
    if not spec["titolo"] and spec["sezioni"]:
        spec["titolo"] = catalogo.get(spec["sezioni"][0]["sezione"]).titolo
    return spec, avvisi


# ═══════════════════════════════════════════════════════════════════════════
# Interpretazione: AI, con ripiego a parole chiave
# ═══════════════════════════════════════════════════════════════════════════

def _json_da_testo(testo: str):
    """Primo oggetto JSON nel testo dell'AI (tollera ```json e testo attorno)."""
    inizio = testo.find("{")
    while inizio != -1:
        profondita = 0
        for i in range(inizio, len(testo)):
            if testo[i] == "{":
                profondita += 1
            elif testo[i] == "}":
                profondita -= 1
                if profondita == 0:
                    try:
                        return json.loads(testo[inizio:i + 1])
                    except ValueError:
                        break
        inizio = testo.find("{", inizio + 1)
    return None


MAX_CATALOGO_CARATTERI = 24000  # num_ctx di produzione 16384 token: il catalogo resta ben sotto


def catalogo_json(request, scelte_perimetro: dict) -> str:
    """Catalogo compatto per l'AI; se cresce troppo si accorciano gli elenchi di scelte."""
    for limite in (60, 25, 10):
        testo = json.dumps(catalogo_per_ai(request, scelte_perimetro, limite=limite),
                           ensure_ascii=False, separators=(",", ":"))
        if len(testo) <= MAX_CATALOGO_CARATTERI:
            return testo
    return testo


def _contesto_ai(request, scelte_perimetro: dict, specifica: dict) -> str:
    parti = [
        ISTRUZIONI,
        "CATALOGO (sezioni consentite all'utente, opzioni e valori ammessi):",
        catalogo_json(request, scelte_perimetro),
        "SPECIFICA ATTUALE (il report in corso, vuota se è la prima richiesta):",
        json.dumps(specifica, ensure_ascii=False, separators=(",", ":")),
        f"Oggi è il {timezone.localdate():%d/%m/%Y}.",
    ]
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lezioni = lezioni_testo(MODULO_AI, AZIONE_AI)
        if lezioni:
            parti.append(lezioni)
    except Exception:  # noqa: BLE001 - l'apprendimento non deve mai bloccare la richiesta
        logger.debug("reportistica: lezioni AI non disponibili", exc_info=True)
    return "\n".join(parti)


def interpreta(messaggio: str, *, request, specifica: dict, storico: list[dict],
               scelte_perimetro: dict, dipendenti) -> Esito:
    """Richiesta in linguaggio naturale -> specifica validata."""
    messaggio = _testo(messaggio, MAX_MESSAGGIO)
    grezza, risposta, ai = None, "", True
    try:
        from ai_assistant.services import chat_with_ollama

        # Il prompt utente e' troncato da ``build_ollama_messages`` (OLLAMA_CHAT_MAX_PROMPT_CHARS):
        # va solo la richiesta, istruzioni e catalogo stanno nel contesto.
        risultato = chat_with_ollama(
            messaggio,
            history=storico[-MAX_STORICO:],
            runtime_context=_contesto_ai(request, scelte_perimetro, specifica),
            timeout=120,
        )
        dati = _json_da_testo(getattr(risultato, "content", "") or "")
        if isinstance(dati, dict) and isinstance(dati.get("specifica"), dict):
            grezza = dati["specifica"]
            risposta = _testo(dati.get("risposta"), 600)
        else:
            logger.info("reportistica: risposta AI senza specifica valida")
    except Exception as exc:  # noqa: BLE001 - AI spenta o lenta: si ripiega
        logger.info("reportistica: AI non disponibile (%s)", exc)
    if grezza is None:
        ai = False
        grezza = interpreta_senza_ai(messaggio, specifica, scelte_perimetro)
        risposta = ("L'assistente AI non è raggiungibile: ho interpretato la richiesta con le parole chiave. "
                    "Controlla l'anteprima e correggi a parole o dal modello.")
    spec, avvisi = normalizza_specifica(grezza, request, scelte_perimetro, dipendenti)
    if not spec["sezioni"] and not risposta:
        risposta = "Non ho capito quali dati ti servono: prova a dire, per esempio, «matrice formazione del reparto Produzione»."
    return Esito(specifica=spec, risposta=risposta, avvisi=avvisi, ai=ai)


# Parole chiave -> sezione. Ordine = priorità (le espressioni piu' specifiche prima).
_PAROLE_SEZIONI = (
    (("matrice formazione", "matrice corsi", "matrice della formazione"), "matrice_formazione"),
    (("matrice qualific", "matrice competenz", "matrice delle qualific"), "matrice_qualifiche"),
    (("scheda individual", "scheda competenz", "scheda per persona"), "scheda_individuale"),
    (("scadenzario", "scadenziario", "scadenze in arrivo", "prossime scadenze"), "scadenzario_unico"),
    (("formazione sicurezza", "corsi sicurezza", "81/08", "81/2008"), "sicurezza_formazione"),
    (("visite", "sorveglianza", "medico competente"), "sicurezza_sorveglianza"),
    (("attestat",), "attestati_formazione"),
    (("ore di formazione", "formazione erogata", "ore formazione"), "formazione_erogata"),
    (("formazione", "corsi"), "personale_formazione"),
    (("abilitazion", "processi special", "nadcap", "part 145"), "abilitazioni_processi"),
    (("qualific", "patentin", "certificazion"), "personale_qualifiche"),
    (("parità", "parita", "genere", "pdr 125", "pdr125"), "pdr125_indicatori"),
    (("assunzion", "cessazion", "movimenti", "entrati", "usciti"), "organico_movimenti"),
    (("organico", "turnover", "indicatori del personale", "età media", "anzianità"), "organico_indicatori"),
    (("organigramma", "responsabili di reparto", "responsabili d'area"), "organigramma"),
    (("elenco", "lista del personale", "anagrafica", "dipendenti"), "personale_elenco"),
)
# Sezioni chiamate con parole generiche: si saltano se c'e' gia' una delle sezioni
# piu' precise indicate (insieme vuoto = qualunque altra sezione).
_GENERICHE = {
    "personale_formazione": {"matrice_formazione", "sicurezza_formazione", "formazione_erogata",
                             "attestati_formazione", "scadenzario_unico", "scheda_individuale"},
    "personale_qualifiche": {"matrice_qualifiche", "scheda_individuale", "scadenzario_unico"},
    "personale_elenco": set(),
}
_PAROLE_PERIODO = (
    (("anno scorso", "anno precedente", "l'anno passato"), "ANNO_PRECEDENTE"),
    (("quest'anno", "anno in corso", "anno corrente", "da inizio anno"), "ANNO_CORRENTE"),
    (("mese scorso", "mese precedente"), "MESE_PRECEDENTE"),
    (("trimestre scorso", "trimestre precedente", "ultimo trimestre"), "TRIMESTRE_PRECEDENTE"),
    (("ultimi 12 mesi", "ultimo anno"), "ULTIMI_12_MESI"),
)


_SOGLIE_ORE = (
    (("MENO DI", "MINORE DI", "MINORI DI", "INFERIORE A", "INFERIORI A", "SOTTO LE", "SOTTO I", "SOTTO",
      "< "), "meno_di"),
    (("AL MASSIMO", "NON PIU DI", "FINO A"), "al_massimo"),
    (("ALMENO", "NON MENO DI", "MINIMO"), "almeno"),
    (("PIU DI", "OLTRE", "MAGGIORE DI", "MAGGIORI DI", "SUPERIORE A", "SUPERIORI A", "SOPRA LE", "> "), "piu_di"),
)


def _soglia_ore(testo: str) -> tuple[str, int] | None:
    """«meno di 5 ore», «minore di 5 ore», «almeno 8 ore»… -> (confronto, soglia)."""
    for parole, confronto in _SOGLIE_ORE:
        for parola in parole:
            # «non meno di» / «non più di» appartengono a un altro confronto: qui si saltano.
            m = re.search(rf"(?<![A-Z]){re.escape(parola.strip())}\s*(\d+)\s*(?:ORE|ORA|H)\b", testo)
            if m and not (confronto in ("meno_di", "piu_di") and testo[:m.start()].rstrip().endswith("NON")):
                return confronto, int(m.group(1))
    return None


def _periodo_anno(anno: int) -> dict:
    """Un anno solare detto a parole («nel 2026») -> periodo della specifica."""
    corrente = timezone.localdate().year
    if anno == corrente:
        return {"tipo": "ANNO_CORRENTE", "da": "", "a": ""}
    if anno == corrente - 1:
        return {"tipo": "ANNO_PRECEDENTE", "da": "", "a": ""}
    return {"tipo": "PERSONALIZZATO", "da": f"{anno}-01-01", "a": f"{anno}-12-31"}


def _contiene(testo: str, voce: str) -> bool:
    """``voce`` compare in ``testo`` come parola intera (testo gia' in forma ``chiave_testo``)."""
    chiave = naming.chiave_testo(voce)
    return bool(chiave) and bool(re.search(rf"(?<![A-Z0-9]){re.escape(chiave)}(?![A-Z0-9])", testo))


def interpreta_senza_ai(messaggio: str, specifica: dict, scelte_perimetro: dict) -> dict:
    """Interprete deterministico per i casi comuni, usato quando l'AI non risponde."""
    testo = naming.chiave_testo(messaggio)
    spec = json.loads(json.dumps(specifica or specifica_vuota()))
    trovate: list[str] = []
    residuo = testo
    for parole, chiave in _PAROLE_SEZIONI:
        piu_specifiche = _GENERICHE.get(chiave)
        if piu_specifiche is not None and (not piu_specifiche or set(trovate) & piu_specifiche) and trovate:
            continue  # parola generica («corsi», «dipendenti»…) gia' coperta da una sezione piu' precisa
        for parola in parole:
            p = naming.chiave_testo(parola)
            if p in residuo:
                if chiave not in trovate:
                    trovate.append(chiave)
                # «matrice formazione sicurezza» non deve attivare anche «formazione» o «formazione sicurezza».
                residuo = residuo.replace(p, " ")
                break
    aggiungi = any(_contiene(testo, w) for w in ("aggiungi", "anche", "inoltre"))
    if trovate:
        esistenti = [s["sezione"] for s in spec.get("sezioni", [])] if aggiungi else []
        spec["sezioni"] = [s for s in spec.get("sezioni", []) if aggiungi] + [
            {"sezione": k, "colonne": [], "opzioni": {}} for k in trovate if k not in esistenti]

    for parole, tipo in _PAROLE_PERIODO:
        if any(naming.chiave_testo(p) in testo for p in parole):
            spec["periodo"] = {"tipo": tipo, "da": "", "a": ""}
            break
    else:
        anno = re.search(r"(?<!\d)(20\d\d)(?!\d)", testo)
        if anno:
            spec["periodo"] = _periodo_anno(int(anno.group(1)))
    perimetro = spec.setdefault("perimetro", {})
    for campo in ("reparti", "aree", "mansioni"):
        valori = [lab for _k, lab in scelte_perimetro.get(campo, []) if lab and _contiene(testo, lab)]
        if valori:
            perimetro[campo] = valori
    if any(_contiene(testo, w) for w in ("cessati", "cessate", "ex dipendenti")):
        perimetro["includi_cessati"] = True
    if _contiene(testo, "excel") or _contiene(testo, "xlsx"):
        spec["formato"] = "xlsx"
    elif _contiene(testo, "pdf"):
        spec["formato"] = "pdf"

    solo_scadute = any(_contiene(testo, w) for w in ("scaduti", "scadute", "scaduto", "scaduta"))
    solo_critiche = any(_contiene(testo, w) for w in ("critici", "critiche", "problemi", "mancanti", "lacune"))
    for voce in spec.get("sezioni", []):
        sezione = catalogo.get(voce.get("sezione"))
        if sezione is None:
            continue
        nomi = {o.nome for o in sezione.tutte_le_opzioni()}
        opzioni = voce.setdefault("opzioni", {})
        if _contiene(testo, "sicurezza") and "solo_sicurezza" in nomi:
            opzioni["solo_sicurezza"] = True
        soglia = _soglia_ore(testo)
        if soglia and "confronto_ore" in nomi:
            opzioni["confronto_ore"], opzioni["soglia_ore"] = soglia
            opzioni.setdefault("dettaglio", "persona")
        if solo_scadute and "stati" in nomi:
            stati = {k for k, _l in next(o for o in sezione.tutte_le_opzioni() if o.nome == "stati").elenco_scelte()}
            opzioni["stati"] = [s for s in ("scaduta", "SCADUTO") if s in stati]
        elif (solo_scadute or solo_critiche) and "solo_criticita" in nomi:
            opzioni["solo_criticita"] = True
    return spec


# ═══════════════════════════════════════════════════════════════════════════
# Dalla specifica al documento
# ═══════════════════════════════════════════════════════════════════════════

def modello_e_blocchi(specifica: dict):
    """Modello e blocchi *non salvati* per il motore (la conversazione non crea record)."""
    from anagrafica.models import ReportBlocco, ReportModello

    modello = ReportModello(
        nome="Report da conversazione", titolo_documento=specifica.get("titolo") or "Report del personale",
        destinatario=specifica.get("destinatario") or "", periodo_tipo=specifica["periodo"]["tipo"],
        data_da=_data(specifica["periodo"].get("da")), data_a=_data(specifica["periodo"].get("a")),
        filtri=perimetro_di(specifica).as_dict(), formato_predefinito=specifica.get("formato") or "pdf",
        riservatezza=ReportModello.RISERVATEZZA_PERSONALE,
    )
    blocchi = [
        ReportBlocco(modello=modello, ordine=(i + 1) * 10, tipo=ReportBlocco.TIPO_SEZIONE, sezione=v["sezione"],
                     opzioni={"colonne": list(v.get("colonne") or []), "valori": dict(v.get("opzioni") or {})})
        for i, v in enumerate(specifica.get("sezioni") or [])
    ]
    return modello, blocchi


def perimetro_di(specifica: dict) -> Perimetro:
    return Perimetro.from_dict(specifica.get("perimetro") or {})


def componi(specifica: dict, request):
    from . import motore

    modello, blocchi = modello_e_blocchi(specifica)
    parametri = motore.Parametri(
        periodo_tipo=modello.periodo_tipo, data_da=modello.data_da, data_a=modello.data_a,
        perimetro=perimetro_di(specifica), titolo=modello.titolo_documento, destinatario=modello.destinatario,
    )
    return modello, motore.componi(modello, parametri, request, blocchi=blocchi)


def salva_come_modello(specifica: dict, *, nome: str, user):
    """Trasforma la conversazione in un modello salvato, modificabile dall'editor."""
    from django.db import transaction

    modello, blocchi = modello_e_blocchi(specifica)
    with transaction.atomic():
        modello.nome = _testo(nome, 150) or modello.titolo_documento[:150]
        modello.descrizione = "Creato da una richiesta a conversazione."
        modello.created_by = modello.updated_by = user
        modello.save()
        for blocco in blocchi:
            blocco.modello = modello
            blocco.save()
    return modello


def riassunto_decisione(specifica: dict) -> dict:
    """Valori corti confrontabili fra proposta e documento scaricato (apprendimento)."""
    p = specifica.get("perimetro") or {}
    return {
        "sezioni": [s["sezione"] for s in specifica.get("sezioni") or []],
        "periodo": (specifica.get("periodo") or {}).get("tipo", ""),
        "reparti": list(p.get("reparti") or []),
        "mansioni": list(p.get("mansioni") or []),
        "formato": specifica.get("formato", "pdf"),
        "includi_cessati": bool(p.get("includi_cessati")),
    }
