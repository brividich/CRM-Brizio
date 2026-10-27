"""Battito del SOC: ogni lettura e ogni lavoro automatico del SOC, se gira, quando ha girato e quando girerà.

Una riga per componente con tre domande: *ha girato quando doveva?* (ultimo giro rispetto al
calendario dello schedule django-q), *è andata bene?* (esito dell'ultimo giro), *quando riparte?*
(``Schedule.next_run``). Sotto, la mappa di calore degli ultimi 14 giorni: un quadretto per giorno,
colorato dalla quota di giri riusciti rispetto a quelli attesi.

Fonti, tutte già esistenti:

- **letture** (``SecurityLetturaLog``, scritto da ``services.letture``): un giro = una riga;
- **schedule** e **task** di django-q: prossimo giro, coda e fallimenti (i task riusciti salvati
  sono pochi, ``save_limit``: servono per l'ultimo giro, non per lo storico);
- **processi sempre accesi** con il loro segnale di vita (raccoglitore del Registro accessi).

Il calendario atteso viene dallo schedule: ``minutes`` per gli intervalli, ``cron`` letto con
croniter. Nel dubbio (schedule assente) il componente si mostra senza giudizio di ritardo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

GIORNI_MAPPA = 14
TOLLERANZA_MINUTI = 10

# lettura → schedule che la fa girare, ed eventuale intervallo reale se il ciclo la limita (es. Secure Score ogni 12 ore)
SCHEDULE_DI_LETTURA = {
    "caselle": ("security_cycle", None),
    "defender_alert": ("security_cycle", None),
    "entra": ("security_cycle", None),
    "veeam": ("security_cycle", None),
    "secure_score": ("security_cycle", 12 * 60),
    "defender_software": ("defender_software_sync", None),
    "defender_vuln": ("defender_vulnerabilita_sync", None),
    "intune": ("intune_sync", None),
    "m365_licenze": ("m365_licenze_sync", None),
    "watchguard": ("watchguard_api_sync", None),
    "cve": ("security_cve_enrichment", None),
    "tabella_mac": ("contatori_tabella_mac", None),
    "rete_windows": ("rete_windows_sync", None),
    "registro_ad": ("registro_log_ad", None),
    "registro_infra": ("registro_log_infra", None),
    "cpe_ai": ("security_ai_cpe", None),
    "pacchetto_iso": ("security_pacchetto_iso", None),
}


@dataclass(frozen=True)
class Lavoro:
    """Un lavoro pianificato del SOC che non è una lettura (non scrive ``SecurityLetturaLog``)."""

    codice: str
    nome: str
    gruppo: str
    descrizione: str
    schedule: str


LAVORI = (
    Lavoro("ciclo", "Ciclo del SOC", "Motore del SOC",
           "Ogni 15 minuti: legge caselle, Defender, Entra e Veeam, applica le regole, chiude gli alert rientrati, "
           "manda le notifiche.", "security_cycle"),
    Lavoro("ai_lettura", "Lettura assistita dall'AI", "Motore del SOC",
           "Rilegge con l'AI locale le mail che i parser non hanno capito.", "security_ai_lettura"),
    Lavoro("ai_sintesi", "Sintesi della giornata (AI)", "Motore del SOC",
           "Riassunto della situazione nella Panoramica.", "security_ai_sintesi"),
    Lavoro("registro_ciclo", "Controlli del Registro accessi", "Registro accessi",
           "Ogni 5 minuti: raccoglitore vivo, fonti mute, sigilli dell'archivio, invio al SOC.", "registro_log_ciclo"),
)


# --- Calendario ------------------------------------------------------------------------------

def _schedules() -> dict:
    try:
        from django_q.models import Schedule

        return {s.name: s for s in Schedule.objects.all()}
    except Exception:  # noqa: BLE001 - django-q assente o tabella non migrata: niente calendario
        return {}


def intervallo_minuti(s) -> int | None:
    """Minuti tra due giri per gli schedule a intervallo; None per i cron (vedi :func:`giri_attesi`)."""
    if s is None:
        return None
    tipo = (s.schedule_type or "").upper()
    if tipo == "I":
        return int(s.minutes or 0) or None
    return {"H": 60, "D": 1440, "W": 10080, "M": 43200}.get(tipo)


def giri_attesi(s, dal: datetime, al: datetime, massimo: int = 3000) -> list[datetime]:
    """Gli istanti in cui lo schedule doveva partire tra ``dal`` e ``al`` (al più ``massimo``)."""
    if s is None or dal >= al:
        return []
    tipo = (s.schedule_type or "").upper()
    if tipo == "C" and s.cron:
        try:
            from croniter import croniter
        except ImportError:
            return []
        it = croniter(s.cron, timezone.localtime(dal))
        out = []
        while len(out) < massimo:
            t = it.get_next(datetime)
            if t > timezone.localtime(al):
                break
            out.append(t)
        return out
    passo = intervallo_minuti(s)
    if not passo:
        return []
    out, t = [], dal
    while t < al and len(out) < massimo:
        t += timedelta(minutes=passo)
        if t <= al:
            out.append(t)
    return out


def doveva_partire_dopo(s, ora: datetime, ogni: int | None = None) -> datetime | None:
    """L'ultimo istante in cui lo schedule doveva già essere partito, con la tolleranza.

    Se l'ultimo giro è più vecchio di così, il componente è in ritardo.
    """
    if s is None:
        return None
    passo = ogni or intervallo_minuti(s)
    if passo:
        return ora - timedelta(minutes=2 * passo + TOLLERANZA_MINUTI)
    giri = giri_attesi(s, ora - timedelta(days=8), ora - timedelta(minutes=TOLLERANZA_MINUTI))
    return giri[-1] - timedelta(minutes=TOLLERANZA_MINUTI) if giri else None


# --- Componenti ------------------------------------------------------------------------------

def _giorni(ora):
    oggi = timezone.localdate(ora)
    return [oggi - timedelta(days=i) for i in range(GIORNI_MAPPA - 1, -1, -1)]


def _cella(giorno, giri: list, attesi: int | None, accesa: bool, oggi) -> dict:
    """Un quadretto della mappa: tono e testo del suggerimento."""
    ok = sum(1 for g in giri if g in ("ok",))
    parziali = sum(1 for g in giri if g == "parziale")
    ko = sum(1 for g in giri if g == "errore")
    fatti = ok + parziali + ko
    testo = f"{giorno:%d/%m}: {fatti} gir{'o' if fatti == 1 else 'i'}"
    if attesi:
        testo += f" su {attesi} attes{'o' if attesi == 1 else 'i'}"
    if ko:
        testo += f", {ko} non riuscit{'o' if ko == 1 else 'i'}"
    if parziali:
        testo += f", {parziali} in parte"
    if not accesa and not fatti:
        return {"tono": "spenta", "testo": f"{giorno:%d/%m}: spenta"}
    if not fatti:
        if attesi and giorno < oggi:
            return {"tono": "assente", "testo": testo + ": non ha girato"}
        return {"tono": "vuota", "testo": testo}
    if ko and not ok and not parziali:
        tono = "ko"
    elif ko or parziali or (attesi and giorno < oggi and fatti < attesi * 0.8):
        tono = "parziale"
    else:
        tono = "ok"
    return {"tono": tono, "testo": testo}


def _giudizio(accesa, mancante, ultimo_stato, ultimo_quando, ritardo_da, in_corso) -> tuple[str, str]:
    """(tono, frase) del componente: ok, ritardo, ko, warn, run, spenta, mai."""
    if mancante:
        return ("ko" if accesa else "spenta"), mancante
    if not accesa:
        return "spenta", "Spenta: si accende in Avvisi e automatismi."
    if in_corso:
        return "run", "Giro in corso."
    if ultimo_quando is None:
        return "mai", "Non ha mai girato."
    if ritardo_da and ultimo_quando < ritardo_da:
        return "ritardo", f"In ritardo: l'ultimo giro è del {timezone.localtime(ultimo_quando):%d/%m %H:%M}."
    if ultimo_stato == "errore":
        return "ko", "L'ultimo giro non è riuscito."
    if ultimo_stato == "parziale":
        return "warn", "L'ultimo giro è riuscito in parte."
    return "ok", "Regolare."


def _componente_lettura(lettura, logs, schedules, ora, giorni) -> dict:
    from security.models import SecurityLetturaLog
    from security.services import letture

    nome_schedule, ogni = SCHEDULE_DI_LETTURA.get(lettura.codice, ("", None))
    s = schedules.get(nome_schedule)
    accesa, mancante = letture.attiva(lettura), letture.manca(lettura)
    finiti = [x for x in logs if x.stato not in (SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO)]
    in_corso = any(x.stato in (SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO)
                   and x.avviata_il >= ora - timedelta(minutes=letture.BLOCCO_MINUTI) for x in logs[:3])
    ultimo = finiti[0] if finiti else None
    riuscito = next((x for x in finiti if x.stato in (SecurityLetturaLog.OK, SecurityLetturaLog.PARZIALE)), None)
    tono, frase = _giudizio(accesa, mancante, ultimo.stato if ultimo else "", ultimo.avviata_il if ultimo else None,
                            doveva_partire_dopo(s, ora, ogni), in_corso)
    if tono == "ko" and ultimo and ultimo.messaggio:
        frase = f"{frase} {ultimo.messaggio[:300]}"
    per_giorno: dict = {}
    for x in finiti:
        if not x.manuale:
            per_giorno.setdefault(timezone.localdate(x.avviata_il), []).append(x.stato)
    attesi = _attesi_per_giorno(s, ogni, giorni)
    oggi = timezone.localdate(ora)
    durate = [(x.finita_il - x.avviata_il).total_seconds() for x in finiti[:20] if x.finita_il]
    return {
        "codice": lettura.codice, "nome": lettura.nome, "gruppo": lettura.gruppo, "descrizione": lettura.descrizione,
        "quando": lettura.quando, "tipo": "lettura", "tono": tono, "frase": frase, "accesa": accesa,
        "ultimo": ultimo, "riuscito": riuscito if riuscito is not ultimo else None,
        "prossimo": s.next_run if s is not None and accesa and not mancante else None, "schedule": nome_schedule,
        "durata_media": round(sum(durate) / len(durate)) if durate else None,
        # Senza configurazione non si aspetta nessun giro: i giorni vuoti sono «spenta», non «non ha girato».
        "celle": [_cella(g, per_giorno.get(g, []), attesi.get(g), accesa and not mancante, oggi) for g in giorni],
        "giri": finiti[:10], "esegui": True,
    }


def _attesi_per_giorno(s, ogni, giorni) -> dict:
    if s is None:
        return {}
    out = {}
    for g in giorni:
        if ogni:
            out[g] = max(1, round(1440 / ogni))
            continue
        inizio = timezone.make_aware(datetime.combine(g, datetime.min.time()))
        out[g] = len(giri_attesi(s, inizio - timedelta(seconds=1), inizio + timedelta(days=1) - timedelta(seconds=1))) or None
    return out


def _task_di(func: str, ora) -> tuple:
    """(ultimo task finito, esito, fallimenti nelle 24 ore) di una funzione, dai task salvati da django-q."""
    try:
        from django_q.models import Task
    except Exception:  # noqa: BLE001
        return None, None, 0
    t = Task.objects.filter(func=func).exclude(stopped__isnull=True).order_by("-stopped").only(
        "stopped", "started", "success", "result").first()
    ko = Task.objects.filter(func=func, success=False, stopped__gte=ora - timedelta(hours=24)).count()
    return t, (t.success if t else None), ko


def _componente_lavoro(lavoro: Lavoro, schedules, ora, giorni) -> dict:
    s = schedules.get(lavoro.schedule)
    if s is None:
        return {"codice": lavoro.codice, "nome": lavoro.nome, "gruppo": lavoro.gruppo, "descrizione": lavoro.descrizione,
                "tipo": "lavoro", "tono": "spenta", "frase": "Schedule non registrato: lanciare setup_q_schedules.",
                "accesa": False, "celle": [], "giri": [], "quando": ""}
    t, riuscito, ko = _task_di(s.func, ora)
    ultimo_quando = t.stopped if t else None
    tono, frase = _giudizio(True, "", "" if riuscito is not False else "errore", ultimo_quando,
                            doveva_partire_dopo(s, ora), False)
    if ultimo_quando is None:
        # I task riusciti salvati sono pochi (save_limit): senza traccia non si dice «mai girato».
        tono, frase = "idle", "Nessuna traccia recente nella coda dei lavori (se ne tengono pochi): guardare il prossimo giro."
    if ko:
        frase += f" {ko} giri non riusciti nelle ultime 24 ore."
        tono = "ko" if tono == "ok" else tono
    if riuscito is False and t is not None:
        frase += f" Errore: {str(t.result)[:300]}"
    passo = intervallo_minuti(s)
    return {
        "codice": lavoro.codice, "nome": lavoro.nome, "gruppo": lavoro.gruppo, "descrizione": lavoro.descrizione,
        "quando": f"ogni {passo} minuti" if passo else (s.cron or ""), "tipo": "lavoro", "tono": tono, "frase": frase,
        "accesa": True, "ultimo_quando": ultimo_quando, "prossimo": s.next_run, "schedule": s.name, "celle": [], "giri": [],
    }


def _coda(ora) -> dict:
    """La coda dei lavori (qcluster): se si ferma, nel SOC non gira più niente."""
    try:
        from django_q.models import OrmQ, Schedule, Task
    except Exception:  # noqa: BLE001
        return {"tono": "spenta", "frase": "django-q non installato."}
    ultimo = Task.objects.exclude(stopped__isnull=True).order_by("-stopped").values_list("stopped", flat=True).first()
    in_coda = OrmQ.objects.count()
    falliti = Task.objects.filter(success=False, stopped__gte=ora - timedelta(hours=24)).count()
    in_ritardo = Schedule.objects.filter(next_run__lt=ora - timedelta(minutes=TOLLERANZA_MINUTI)).exclude(repeats=0).count()
    minuti = int((ora - ultimo).total_seconds() // 60) if ultimo else None
    if ultimo is None:
        tono, frase = "ko", "La coda dei lavori non ha mai completato un lavoro: il qcluster non è avviato."
    elif minuti > 30 or in_ritardo > 3:
        tono, frase = "ko", (f"Nessun lavoro completato da {minuti} minuti" if minuti > 30 else
                             f"{in_ritardo} lavori pianificati oltre l'orario previsto") + ": il qcluster sembra fermo, va riavviato."
    elif in_coda > 50:
        tono, frase = "warn", f"{in_coda} lavori in attesa: la coda è lenta."
    else:
        tono, frase = "ok", f"Ultimo lavoro completato {minuti} minuti fa."
    return {"tono": tono, "frase": frase, "ultimo": ultimo, "in_coda": in_coda, "falliti": falliti, "in_ritardo": in_ritardo}


def _raccoglitore(ora) -> dict | None:
    try:
        from registro_log import ciclo
        from registro_log.models import Impostazioni
    except Exception:  # noqa: BLE001
        return None
    if not Impostazioni.corrente().attivo:
        return {"tono": "spenta", "frase": "Registro accessi spento.", "at": None}
    b = ciclo.battito()
    if b["at"] is None:
        return {"tono": "mai", "frase": "Raccoglitore mai partito (task RegistroLog da installare).", "at": None}
    if not b["vivo"]:
        return {"tono": "ko", "frase": f"Raccoglitore fermo dal {timezone.localtime(b['at']):%d/%m %H:%M}.", "at": b["at"]}
    errore = b["stato"].errore if b["stato"] else ""
    return {"tono": "warn" if errore else "ok", "frase": errore or "Raccoglitore acceso.", "at": b["at"]}


def stato(ora: datetime | None = None) -> dict:
    """Tutto quello che serve alla pagina «Battito del SOC»."""
    from security.models import SecurityLetturaLog
    from security.services import letture

    ora = ora or timezone.now()
    giorni = _giorni(ora)
    dal = timezone.make_aware(datetime.combine(giorni[0], datetime.min.time()))
    schedules = _schedules()
    logs: dict = {}
    for x in (SecurityLetturaLog.objects.filter(avviata_il__gte=dal).only(
            "codice", "stato", "manuale", "avviata_il", "finita_il", "messaggio").order_by("-avviata_il")):
        logs.setdefault(x.codice, []).append(x)
    # Le letture senza giri negli ultimi 14 giorni: l'ultimo giro in assoluto, per dire da quando tace.
    for codice in [lt.codice for lt in letture.LETTURE if lt.codice not in logs]:
        x = SecurityLetturaLog.objects.filter(codice=codice).order_by("-avviata_il").first()
        if x is not None:
            logs[codice] = [x]
    componenti = [_componente_lettura(lt, logs.get(lt.codice, []), schedules, ora, giorni) for lt in letture.LETTURE]
    componenti += [_componente_lavoro(lv, schedules, ora, giorni) for lv in LAVORI]
    gruppi: list[dict] = []
    for c in componenti:
        g = next((x for x in gruppi if x["nome"] == c["gruppo"]), None)
        if g is None:
            g = {"nome": c["gruppo"], "componenti": []}
            gruppi.append(g)
        g["componenti"].append(c)
    problemi = [c for c in componenti if c["tono"] in ("ko", "ritardo")]
    avvisi = [c for c in componenti if c["tono"] in ("warn", "mai") and c.get("accesa")]
    coda = _coda(ora)
    raccoglitore = _raccoglitore(ora)
    if coda["tono"] == "ko":
        problemi.insert(0, {"nome": "Coda dei lavori (qcluster)", "frase": coda["frase"], "codice": "coda"})
    if raccoglitore and raccoglitore["tono"] == "ko":
        problemi.append({"nome": "Raccoglitore del Registro accessi", "frase": raccoglitore["frase"], "codice": "raccoglitore"})
    prossimi = sorted((c for c in componenti if c.get("prossimo")), key=lambda c: c["prossimo"])[:6]
    return {
        "ora": ora, "giorni": giorni, "gruppi": gruppi, "coda": coda, "raccoglitore": raccoglitore,
        "problemi": problemi, "avvisi": avvisi, "prossimi": prossimi,
        "conteggi": {
            "ok": sum(1 for c in componenti if c["tono"] in ("ok", "run")),
            "problemi": len(problemi), "avvisi": len(avvisi),
            "spente": sum(1 for c in componenti if c["tono"] == "spenta"),
            "totale": len(componenti),
        },
    }
