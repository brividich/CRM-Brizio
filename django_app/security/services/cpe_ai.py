"""Proposte dell'AI locale (Ollama) sui casi «da verificare» del calcolo CVE.

Il motore degli impatti (``cve_impact``) dice «da verificare» quando non può dimostrare un esito:
software senza CPE confermato, versione non confrontabile, CVE valida solo con una piattaforma o
una configurazione. Sono i casi che bloccano la chiusura automatica delle CVE. Qui l'AI locale
**propone** e una persona decide; tre regole:

1. **Mai una decisione.** La proposta finisce in ``SecurityPropostaAi`` e a video, con «Accetta» e
   «Rifiuta». Accettare passa dallo stesso percorso della conferma a mano (audit, ricalcolo).
2. **Solo scelte fra dati reali.** Per i CPE il modello sceglie fra i candidati presi dalle CVE già
   nel sistema (``SecurityCveRecord.configurations``): un CPE fuori dall'elenco viene scartato. Per gli
   esiti riceve solo i dati del sistema (CVE, range, programma, versione, PC) e una motivazione che
   cita numeri di versione assenti dal contesto viene scartata.
3. **Con un budget.** Al massimo N casi per giro (``ai.cpe.max_per_giro``), nessuna nuova richiesta
   dopo il tempo concesso, niente richieste se Ollama non risponde. Ogni richiesta è nel registro AI
   del SOC (``SecurityAiInteractionLog``). I dati restano in rete locale.

Il modello (qwen2.5 14B in produzione) riceve un prompt in italiano a temperatura bassa, esempi
sintetici e l'istruzione esplicita «se non sei sicuro rispondi da_verificare».
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from security.models import (
    SecurityAiInteractionLog,
    SecurityCveImpact,
    SecurityPropostaAi,
    SoftwareCpeMapping,
    SoftwareInstallation,
)

logger = logging.getLogger(__name__)

ACTION_CPE = "cpe_proposta"
ACTION_ESITO = "esito_proposta"
MAX_CANDIDATI = 12
MAX_VERSIONI = 6
TEMPERATURA = 0.1
TIMEOUT_DISPONIBILE = 4
BUDGET_PIANIFICATO = 60   # secondi: il worker django-q ha 120 s, una risposta in produzione 15-40 s
BUDGET_MANUALE = 300      # «Proponi ora» gira in coda con TIMEOUT_CODA (600 s)

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_VERSIONE = re.compile(r"\d+(?:\.\d+)+")
_TOKEN = re.compile(r"[a-z0-9]+")

SISTEMA_CPE = (
    "Sei l'assistente del Security Center di una piccola azienda manifatturiera italiana. Devi dire a quale prodotto "
    "del dizionario CPE di NVD corrisponde un programma trovato nell'inventario dei PC. Puoi scegliere SOLO fra i "
    "candidati elencati (coppie produttore:prodotto che compaiono nelle CVE già presenti nel sistema). "
    "Rispondi «non_applicabile» solo se sei sicuro che il programma non è nessuno dei candidati (per esempio un driver, "
    "un runtime, un componente o un prodotto diverso con un nome simile). Se non sei sicuro rispondi «da_verificare». "
    "Non inventare mai un CPE che non è fra i candidati e non usare conoscenze su versioni o prodotti non scritti qui. "
    "Rispondi SOLO con un oggetto JSON, senza testo prima o dopo, con queste chiavi: "
    "\"scelta\" (uno fra \"cpe\", \"non_applicabile\", \"da_verificare\"), "
    "\"cpe\" (il candidato scelto copiato uguale, oppure null), "
    "\"confidenza\" (numero intero da 0 a 100), "
    "\"motivazione\" (una frase in italiano, al massimo 200 caratteri, che cita solo i dati forniti)."
)
ESEMPI_CPE = (
    ("Programma: produttore «igor pavlov», prodotto «7-zip», su 12 PC, versioni 23.01, 24.08.\nCandidati: 7-zip:7-zip, 7-zip:p7zip",
     {"scelta": "cpe", "cpe": "7-zip:7-zip", "confidenza": 95,
      "motivazione": "Il prodotto si chiama 7-zip come il candidato 7-zip:7-zip; p7zip è un'altra distribuzione."}),
    ("Programma: produttore «microsoft», prodotto «microsoft visual c++ 2015 redistributable», su 40 PC, versioni 14.0.24215.\n"
     "Candidati: microsoft:visual_studio, microsoft:visual_studio_code",
     {"scelta": "non_applicabile", "cpe": None, "confidenza": 85,
      "motivazione": "È il runtime ridistribuibile, non Visual Studio né Visual Studio Code."}),
    ("Programma: produttore «acme software», prodotto «acme viewer», su 3 PC, versioni 2.1.\nCandidati: acme:acme_reader, acme:acme_viewer_pro",
     {"scelta": "da_verificare", "cpe": None, "confidenza": 40,
      "motivazione": "Due candidati con nome simile (reader e viewer pro) e nessuno coincide con «acme viewer»."}),
)

SISTEMA_ESITO = (
    "Sei l'assistente del Security Center di una piccola azienda manifatturiera italiana. Ti vengono descritti una CVE "
    "e un programma installato su un PC che il sistema non è riuscito a giudicare da solo. Devi dire se la CVE riguarda "
    "quel PC: \"impatta\" se la versione installata rientra nel range vulnerabile e la condizione della CVE si applica, "
    "\"non_impatta\" se la versione è fuori dal range o la condizione della CVE sicuramente non si applica, "
    "\"da_verificare\" se i dati forniti non bastano. Usa SOLO i dati forniti: non conosci versioni, sistemi operativi, "
    "patch o correzioni che non sono scritti qui. Se devi fare un'ipotesi, rispondi «da_verificare». "
    "Rispondi SOLO con un oggetto JSON, senza testo prima o dopo, con queste chiavi: "
    "\"esito\" (uno fra \"impatta\", \"non_impatta\", \"da_verificare\"), "
    "\"confidenza\" (numero intero da 0 a 100), "
    "\"motivazione\" (una frase in italiano, al massimo 200 caratteri, che cita solo i dati forniti)."
)
ESEMPI_ESITO = (
    ("CVE-2099-0001 (CVSS 7.8): Heap overflow in 7-Zip before 24.07.\nRange vulnerabile per 7-zip:7-zip: vulnerabile < 24.07.\n"
     "Programma: 7-Zip versione «24.08 R2» su PC-DEMO-01; fonte: export WatchGuard del 10/10/2026.\n"
     "Perché è da verificare: Versione «24.08 R2» non confrontabile in modo affidabile.",
     {"esito": "non_impatta", "confidenza": 90,
      "motivazione": "La versione installata è la 24.08 (R2 è una revisione), superiore alla 24.07 da cui la CVE è corretta."}),
    ("CVE-2099-0002 (CVSS 8.1): Remote code execution in DemoSuite when the optional WebSync plug-in is enabled.\n"
     "Range vulnerabile per demo:demosuite: vulnerabile <= 5.2.\nProgramma: DemoSuite versione «5.1» su PC-DEMO-02; fonte: export Defender del 10/10/2026.\n"
     "Perché è da verificare: Versione nel range, ma la CVE vale solo con una piattaforma/configurazione specifica.",
     {"esito": "da_verificare", "confidenza": 45,
      "motivazione": "La versione 5.1 è nel range ma la CVE vale solo con il plug-in WebSync e i dati non dicono se è attivo."}),
    ("CVE-2099-0003 (CVSS 9.8): Buffer overflow in AcmeViewer 2.4.1 and earlier.\nRange vulnerabile per acme:acmeviewer: vulnerabile <= 2.4.1.\n"
     "Programma: AcmeViewer versione «2.4.1-build7» su PC-DEMO-03; fonte: export WatchGuard del 10/10/2026.\n"
     "Perché è da verificare: Versione «2.4.1-build7» non confrontabile in modo affidabile.",
     {"esito": "impatta", "confidenza": 85,
      "motivazione": "«2.4.1-build7» è la versione 2.4.1, che rientra nel range vulnerabile (fino alla 2.4.1 compresa)."}),
)


# --- Collegamento all'AI locale ------------------------------------------------------------------

def configurata() -> str:
    """'' se l'AI locale è configurata, altrimenti cosa manca (per la pagina Letture automatiche)."""
    if not getattr(settings, "OLLAMA_CHAT_ENABLED", True):
        return "Assistente AI spento (OLLAMA_CHAT_ENABLED)."
    if not str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip():
        return "OLLAMA_BASE_URL non configurato (Setup Wizard › Assistente AI)."
    if not str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip():
        return "OLLAMA_CHAT_MODEL non configurato (Setup Wizard › Assistente AI)."
    return ""


def disponibile() -> tuple[bool, str]:
    """Ollama risponde e ha il modello? (``/api/tags``, pochi secondi): niente richieste se è spento."""
    manca = configurata()
    if manca:
        return False, manca
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "")).strip().rstrip("/")
    if str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower() != "ollama":
        return True, ""  # Open WebUI: nessun catalogo; si prova la richiesta
    try:
        from monitoring.health import _model_present, _ollama_model_names

        names = _ollama_model_names(base_url)
    except Exception as exc:  # noqa: BLE001 - rete, timeout, JSON
        return False, f"AI locale non raggiungibile: {type(exc).__name__}: {str(exc)[:120]}"
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "")).strip()
    if not _model_present(names, model):
        return False, f"Il modello «{model}» non è caricato su Ollama."
    return True, ""


def _messaggi(sistema, esempi, domanda):
    out = [{"role": "system", "content": sistema}]
    for utente, risposta in esempi:
        out.append({"role": "user", "content": utente})
        out.append({"role": "assistant", "content": json.dumps(risposta, ensure_ascii=False)})
    out.append({"role": "user", "content": domanda})
    return out


def _chiedi(messaggi, *, action, object_type="", object_id=""):
    """Una richiesta JSON all'AI locale: stesse impostazioni e stesso limite di richieste dell'Assistente AI.

    Non passa da ``chat_with_ollama`` perché quello aggiunge il prompt di sistema del portale e il
    contesto RAG: qui serve un prompt proprio, temperatura bassa e risposta solo JSON.
    """
    from ai_assistant.services import OllamaChatError, _acquire_ai_slot

    started = time.monotonic()
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    timeout = int(getattr(settings, "SECURITY_AI_TIMEOUT_SECONDS", 120) or 120)
    status, text, error = "ok", "", ""
    try:
        if not base_url or not model:
            raise OllamaChatError("OLLAMA_BASE_URL o OLLAMA_CHAT_MODEL non configurati.")
        payload = {"model": model, "messages": messaggi, "stream": False}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if provider == "openwebui":
            payload["temperature"] = TEMPERATURA
            api_key = str(getattr(settings, "OPENWEBUI_API_KEY", "") or "").strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            endpoint = f"{base_url}/api/chat/completions"
        else:
            options = {"temperature": TEMPERATURA}
            num_ctx = int(getattr(settings, "OLLAMA_NUM_CTX", 0) or 0)
            if num_ctx > 0:
                options["num_ctx"] = num_ctx
            payload["options"] = options
            payload["format"] = "json"
            keep_alive = str(getattr(settings, "OLLAMA_KEEP_ALIVE", "") or "").strip()
            if keep_alive:
                payload["keep_alive"] = keep_alive
            endpoint = f"{base_url}/api/chat"
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        slots = _acquire_ai_slot()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise OllamaChatError(f"Ollama ha risposto con HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise OllamaChatError(f"Ollama non raggiungibile: {getattr(exc, 'reason', exc)}") from exc
        finally:
            slots.release()
        data = json.loads(raw)
        if provider == "openwebui":
            choices = data.get("choices") if isinstance(data, dict) else None
            message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
        else:
            message = data.get("message") if isinstance(data, dict) else None
        text = str((message or {}).get("content") or "").strip() if isinstance(message, dict) else ""
        if not text:
            status, error = "empty", "L'AI non ha restituito testo."
    except Exception as exc:  # noqa: BLE001 - AI spenta, timeout, configurazione, JSON
        status, error = "error", str(exc)[:300]
        logger.info("AI locale non disponibile per %s: %s", action, exc)
    ms = int((time.monotonic() - started) * 1000)
    try:
        SecurityAiInteractionLog.objects.create(
            action=action, provider="ollama", model=model[:160], status=status, page="soc", object_type=object_type,
            object_id=str(object_id)[:80], request_chars=sum(len(m["content"]) for m in messaggi),
            response_chars=len(text), latency_ms=ms, error_message=error,
        )
    except Exception:  # noqa: BLE001 - il registro non deve bloccare la risposta
        logger.exception("Registro AI non scritto")
    return {"ok": status == "ok", "data": _json(text) if status == "ok" else None, "error": error, "model": model, "ms": ms}


def _json(text):
    match = _JSON_BLOCK.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _hash(*parti):
    return hashlib.sha256("\n".join(str(p) for p in parti).encode()).hexdigest()


def _confidenza(valore):
    try:
        return max(0, min(100, int(valore)))
    except (TypeError, ValueError):
        return 0


def _motivazione(valore):
    return re.sub(r"\s+", " ", str(valore or "")).strip()[:300]


# --- Collegamento CPE ----------------------------------------------------------------------------

def candidati_cpe(vendor, product, pairs, by_token=None):
    """CPE fra cui scegliere: le proposte per nome di ``cpe_auto`` più le coppie con una parola in comune."""
    from security.services.cpe_auto import proposals

    out = list(proposals(vendor, product, pairs))
    if by_token is None:
        by_token = _per_token(pairs)
    for token in _tokens(f"{vendor} {product}"):
        for cv, cp in sorted(by_token.get(token, ())):
            cpe = f"{cv}:{cp}"
            if cpe not in out:
                out.append(cpe)
            if len(out) >= MAX_CANDIDATI:
                return out[:MAX_CANDIDATI]
    return out[:MAX_CANDIDATI]


def _tokens(text):
    return {t for t in _TOKEN.findall(str(text or "").lower()) if len(t) >= 4}


def _per_token(pairs):
    out = defaultdict(set)
    for cv, cp in pairs:
        for token in _tokens(cv.replace("_", " ")) | _tokens(cp.replace("_", " ")):
            out[token].add((cv, cp))
    return out


def casi_cpe(limit=50):
    """Software ancora senza decisione con almeno un CPE candidato, i più diffusi prima."""
    from security.services.cpe_auto import known_cpe_pairs

    pairs = known_cpe_pairs()
    if not pairs:
        return []
    by_token = _per_token(pairs)
    decisi = {}
    for m in SoftwareCpeMapping.objects.all():
        decisi[(m.vendor, m.product)] = m
    rows = (
        SoftwareInstallation.objects.filter(still_detected=True).values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True)).order_by("-hosts", "vendor", "product")
    )
    out = []
    for row in rows:
        mapping = decisi.get((row["vendor"], row["product"]))
        if mapping and (mapping.confirmed or mapping.not_applicable or mapping.origin == SoftwareCpeMapping.ORIGIN_AUTO_REJECTED):
            continue
        candidati = candidati_cpe(row["vendor"], row["product"], pairs, by_token)
        if not candidati:
            continue
        versioni = sorted({v for v in SoftwareInstallation.objects.filter(
            still_detected=True, vendor=row["vendor"], product=row["product"]).values_list("version_raw", flat=True) if v})[:MAX_VERSIONI]
        out.append({"vendor": row["vendor"], "product": row["product"], "hosts": row["hosts"], "versioni": versioni, "candidati": candidati})
        if len(out) >= limit:
            break
    return out


def contesto_cpe(caso):
    versioni = ", ".join(caso["versioni"]) or "non rilevate"
    return (f"Programma: produttore «{caso['vendor'] or 'sconosciuto'}», prodotto «{caso['product']}», su {caso['hosts']} PC, "
            f"versioni {versioni}.\nCandidati: {', '.join(caso['candidati'])}")


def proponi_cpe(caso, *, confidenza_minima=0):
    """Chiede e valida: (proposta dict | None, errore). La coppia scelta deve essere fra i candidati."""
    risposta = _chiedi(_messaggi(SISTEMA_CPE, ESEMPI_CPE, contesto_cpe(caso)), action=ACTION_CPE,
                       object_type="software", object_id=f"{caso['vendor']}/{caso['product']}")
    if not risposta["ok"]:
        return None, risposta["error"] or "AI non disponibile"
    data = risposta["data"]
    if data is None:
        return None, "risposta non in JSON"
    scelta = str(data.get("scelta") or "").strip().lower()
    proposta = None
    if scelta == "cpe":
        cpe = str(data.get("cpe") or "").strip().lower()
        if cpe not in caso["candidati"]:
            return None, f"CPE «{cpe[:60]}» non fra i candidati"
        proposta = cpe
    elif scelta in (SecurityPropostaAi.NON_APPLICABILE, SecurityPropostaAi.DA_VERIFICARE):
        proposta = scelta
    else:
        return None, f"scelta «{scelta[:40]}» non prevista"
    confidenza = _confidenza(data.get("confidenza"))
    if proposta != SecurityPropostaAi.DA_VERIFICARE and confidenza < confidenza_minima:
        return None, f"confidenza {confidenza} sotto la soglia {confidenza_minima}"
    return {"proposta": proposta, "confidenza": confidenza, "motivazione": _motivazione(data.get("motivazione")),
            "modello": risposta["model"], "ms": risposta["ms"]}, ""


# --- Esito CVE su un PC --------------------------------------------------------------------------

# Spiegazioni del motore in cui l'AI non può aiutare: serve una mappatura o un inventario nuovo.
_NON_AIUTABILI = ("mappatura CPE non è confermata", "Inventario vecchio")


def casi_esito(limit=50):
    """Righe «da verificare» con il CPE confermato: versione non confrontabile o CVE condizionata."""
    qs = (SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.TO_VERIFY, installation__isnull=False)
          .select_related("cve", "installation").order_by("-cve__kev", "-cve__cvss", "cve__cve_id", "host"))
    out = []
    for impact in qs[:limit * 4]:
        if any(testo in impact.explanation for testo in _NON_AIUTABILI):
            continue
        out.append(impact)
        if len(out) >= limit:
            break
    return out


def _range_text(c):
    from security.services.cve_impact import _range_text

    return _range_text(c)


def contesto_esito(impact):
    record, install = impact.cve, impact.installation
    pair = _coppia_mappata(install)
    criteri = [c for c in (record.configurations or []) if pair and (c.get("vendor", "").lower(), c.get("product", "").lower()) == pair]
    righe = [f"{record.cve_id} (CVSS {record.cvss if record.cvss is not None else 'n.d.'}): {(record.description or 'descrizione non disponibile')[:700]}"]
    for c in criteri[:6]:
        righe.append(f"Range vulnerabile per {c.get('vendor')}:{c.get('product')}: {_range_text(c)}"
                     + ("; vale solo con una piattaforma specifica" if c.get("requires_platform") else ""))
    if record.ambiguous_configuration:
        righe.append("NVD segnala che la CVE vale solo in una configurazione specifica.")
    righe.append(f"Programma: {install.product_raw} versione «{install.version_raw or 'non rilevata'}» su {install.host_display or install.host}; "
                 f"fonte: {' + '.join(install.fonti_etichette)} del {install.last_inventory_date:%d/%m/%Y}.")
    motivo = impact.explanation.split(". ", 1)[-1] if ". " in impact.explanation else impact.explanation
    righe.append(f"Perché è da verificare: {motivo[:300]}")
    return "\n".join(righe)


def _coppia_mappata(install):
    m = SoftwareCpeMapping.objects.filter(vendor=install.vendor, product=install.product, confirmed=True).first()
    return (m.cpe_vendor.lower(), m.cpe_product.lower()) if m else None


def proponi_esito(impact, *, confidenza_minima=0):
    """Chiede e valida: l'esito deve essere uno dei tre e i numeri di versione citati devono stare nel contesto."""
    contesto = contesto_esito(impact)
    risposta = _chiedi(_messaggi(SISTEMA_ESITO, ESEMPI_ESITO, contesto), action=ACTION_ESITO,
                       object_type="SecurityCveImpact", object_id=impact.pk)
    if not risposta["ok"]:
        return None, risposta["error"] or "AI non disponibile"
    data = risposta["data"]
    if data is None:
        return None, "risposta non in JSON"
    esito = str(data.get("esito") or "").strip().lower()
    if esito not in (SecurityPropostaAi.IMPATTA, SecurityPropostaAi.NON_IMPATTA, SecurityPropostaAi.DA_VERIFICARE):
        return None, f"esito «{esito[:40]}» non previsto"
    motivazione = _motivazione(data.get("motivazione"))
    estranei = [v for v in _VERSIONE.findall(motivazione) if v not in contesto]
    if estranei and esito != SecurityPropostaAi.DA_VERIFICARE:
        return None, f"cita versioni non presenti nei dati ({', '.join(estranei[:3])})"
    confidenza = _confidenza(data.get("confidenza"))
    if esito != SecurityPropostaAi.DA_VERIFICARE and confidenza < confidenza_minima:
        return None, f"confidenza {confidenza} sotto la soglia {confidenza_minima}"
    return {"proposta": esito, "confidenza": confidenza, "motivazione": motivazione, "modello": risposta["model"], "ms": risposta["ms"]}, ""


# --- Giro -----------------------------------------------------------------------------------------

def chiave_cpe(vendor, product):
    return f"cpe|{vendor}|{product}"[:300]


def chiave_esito(cve_id, host):
    return f"esito|{cve_id.upper()}|{host}"[:300]


def _da_saltare(esistente, contesto_hash):
    """Una proposta aperta non si rifà; una decisa o superata solo se i dati del caso sono cambiati."""
    return esistente is not None and (esistente.stato == SecurityPropostaAi.APERTA or esistente.contesto_hash == contesto_hash)


def _salva(chiave, tipo, contesto_hash, proposta, **campi):
    riga, _ = SecurityPropostaAi.objects.update_or_create(chiave=chiave, defaults={
        "tipo": tipo, "contesto_hash": contesto_hash, "proposta": proposta["proposta"], "confidenza": proposta["confidenza"],
        "motivazione": proposta["motivazione"], "modello": proposta["modello"][:160], "stato": SecurityPropostaAi.APERTA,
        "creata_il": timezone.now(), "decisa_il": None, "decisa_da": None, **campi,
    })
    return riga


def aggiorna_superate():
    """Le proposte aperte il cui caso non esiste più (software deciso, PC non più da verificare) diventano «superate»."""
    n = 0
    decisi = {(m.vendor, m.product) for m in SoftwareCpeMapping.objects.filter(confirmed=True) | SoftwareCpeMapping.objects.filter(not_applicable=True)}
    for p in SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.APERTA, tipo=SecurityPropostaAi.TIPO_CPE):
        if (p.vendor, p.product) in decisi:
            p.stato = SecurityPropostaAi.SUPERATA
            p.save(update_fields=["stato"])
            n += 1
    aperte = SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.APERTA, tipo=SecurityPropostaAi.TIPO_ESITO).select_related("cve")
    for p in aperte:
        impact = SecurityCveImpact.objects.filter(cve=p.cve, host=p.host, outcome=SecurityCveImpact.TO_VERIFY).select_related("installation").first()
        if impact is None or (impact.installation and impact.installation.version_raw != p.versione):
            p.stato = SecurityPropostaAi.SUPERATA
            p.save(update_fields=["stato"])
            n += 1
    return n


def giro(*, limit, time_budget_seconds=BUDGET_PIANIFICATO, confidenza_minima=0):
    """Un giro: superate, poi al massimo ``limit`` casi (prima i CPE, poi gli esiti) entro il tempo concesso."""
    superate = aggiorna_superate()
    ok, motivo = disponibile()
    if not ok:
        return {"ok": False, "errore": motivo}
    started = time.monotonic()
    esito = {"superate": superate, "cpe": {"casi": 0, "proposte": 0, "scartate": 0}, "esiti": {"casi": 0, "proposte": 0, "scartate": 0}}
    tempi, fatti, fermo = [], 0, ""

    def _tempo():
        return time.monotonic() - started > time_budget_seconds

    esistenti = {p.chiave: p for p in SecurityPropostaAi.objects.all()}
    for caso in casi_cpe(limit=limit * 3):
        if fatti >= limit or _tempo() or fermo:
            break
        chiave = chiave_cpe(caso["vendor"], caso["product"])
        contesto_hash = _hash(contesto_cpe(caso))
        if _da_saltare(esistenti.get(chiave), contesto_hash):
            continue
        esito["cpe"]["casi"] += 1
        fatti += 1
        proposta, errore = proponi_cpe(caso, confidenza_minima=confidenza_minima)
        if proposta is None:
            esito["cpe"]["scartate"] += 1
            if _ai_ferma(errore):
                fermo = errore
            continue
        tempi.append(proposta["ms"])
        _salva(chiave, SecurityPropostaAi.TIPO_CPE, contesto_hash, proposta, vendor=caso["vendor"], product=caso["product"],
               candidati=caso["candidati"], cve=None, host="", versione="")
        esito["cpe"]["proposte"] += 1
    for impact in casi_esito(limit=limit * 3):
        if fatti >= limit or _tempo() or fermo:
            break
        chiave = chiave_esito(impact.cve.cve_id, impact.host)
        contesto_hash = _hash(contesto_esito(impact))
        if _da_saltare(esistenti.get(chiave), contesto_hash):
            continue
        esito["esiti"]["casi"] += 1
        fatti += 1
        proposta, errore = proponi_esito(impact, confidenza_minima=confidenza_minima)
        if proposta is None:
            esito["esiti"]["scartate"] += 1
            if _ai_ferma(errore):
                fermo = errore
            continue
        tempi.append(proposta["ms"])
        _salva(chiave, SecurityPropostaAi.TIPO_ESITO, contesto_hash, proposta, vendor=impact.installation.vendor,
               product=impact.installation.product, cve=impact.cve, host=impact.host, versione=impact.installation.version_raw[:120],
               candidati=[])
        esito["esiti"]["proposte"] += 1
    if tempi:
        esito["ms_medi"] = int(sum(tempi) / len(tempi))
    if fermo:
        esito["errore"] = f"AI locale non ha risposto: {fermo}"
    return esito


def _ai_ferma(errore):
    """Errore di collegamento (non di contenuto): inutile insistere nel giro."""
    testo = str(errore or "").lower()
    return any(s in testo for s in ("non raggiungibile", "http ", "timeout", "occupato", "non configurat", "ai non disponibile"))


def _limiti():
    from security.services import soc_settings

    return {"limit": soc_settings.value("ai.cpe.max_per_giro"), "confidenza_minima": soc_settings.value("ai.cpe.confidenza_minima")}


def giro_lettura():
    """Giro pianificato (lettura ``cpe_ai``): solo con l'interruttore acceso."""
    from security.services import soc_settings

    if not soc_settings.value("ai.cpe.attivo"):
        return {"skipped": "proposte AI su CPE ed esiti spente"}
    return giro(time_budget_seconds=BUDGET_PIANIFICATO, **_limiti())


def giro_manuale():
    """«Proponi ora» / «Esegui ora»: gira anche con l'interruttore spento, con più tempo."""
    return giro(time_budget_seconds=BUDGET_MANUALE, **_limiti())


# --- Decisioni e lettura per le pagine -----------------------------------------------------------

def segna_decisa(proposta, utente, *, accettata):
    proposta.stato = SecurityPropostaAi.ACCETTATA if accettata else SecurityPropostaAi.RIFIUTATA
    proposta.decisa_il = timezone.now()
    proposta.decisa_da = utente if getattr(utente, "pk", None) else None
    proposta.save(update_fields=["stato", "decisa_il", "decisa_da"])
    return proposta


def proposte_cpe_aperte():
    """{(vendor, product): proposta} per la pagina Software e CPE."""
    return {(p.vendor, p.product): p for p in SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.APERTA, tipo=SecurityPropostaAi.TIPO_CPE)}


def proposte_esito_aperte(record):
    """{host: proposta} per la scheda CVE."""
    return {p.host: p for p in SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.APERTA, tipo=SecurityPropostaAi.TIPO_ESITO, cve=record)}


def verifiche_accettate():
    """{(cve_id, host): proposta} accettate da una persona: il ricalcolo le applica finché la versione resta quella."""
    qs = (SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.ACCETTATA, tipo=SecurityPropostaAi.TIPO_ESITO)
          .exclude(proposta=SecurityPropostaAi.DA_VERIFICARE).select_related("cve", "decisa_da"))
    return {(p.cve.cve_id.upper(), p.host.lower()): p for p in qs if p.cve_id}


def conteggio_aperte():
    return SecurityPropostaAi.objects.filter(stato=SecurityPropostaAi.APERTA).count()
