"""Riconoscimento degli eventi importanti: registro eventi di Windows e syslog.

Tutto ciò che arriva finisce nell'archivio; qui si decide cosa entra anche nell'indice
(:class:`~registro_log.models.EventoRegistro`) e con quale etichetta in italiano.
Le funzioni sono pure (niente database) per poterle provare con esempi sintetici.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

# (etichetta per le persone, gravità di partenza)
CATEGORIE: dict[str, tuple[str, str]] = {
    "accesso": ("Accesso", "info"),
    "accesso_privilegiato": ("Accesso con privilegi di amministratore", "info"),
    "accesso_fallito": ("Accesso non riuscito", "warning"),
    "uscita": ("Uscita", "info"),
    "account_bloccato": ("Account bloccato per troppi tentativi", "warning"),
    "account_creato": ("Account creato", "warning"),
    "account_eliminato": ("Account eliminato", "warning"),
    "account_modificato": ("Account modificato", "info"),
    "gruppo_privilegiato": ("Aggiunta a un gruppo di amministratori", "high"),
    "gruppo_modificato": ("Modifica di un gruppo", "info"),
    "registro_cancellato": ("Registro eventi cancellato", "high"),
    "audit_modificato": ("Criteri di registrazione (audit) modificati", "high"),
    "servizio_installato": ("Servizio installato", "warning"),
    "attivita_pianificata": ("Attività pianificata creata", "warning"),
    "ora_modificata": ("Orologio di sistema cambiato", "warning"),
    "avvio_arresto": ("Avvio o arresto del sistema", "info"),
    "configurazione": ("Configurazione dell'apparato modificata", "warning"),
    "comando_privilegiato": ("Comando eseguito come amministratore", "info"),
}

# Gruppi i cui membri sono amministratori (nomi in inglese e italiano dei gruppi predefiniti).
GRUPPI_PRIVILEGIATI = {
    "domain admins", "enterprise admins", "schema admins", "administrators", "account operators",
    "backup operators", "server operators", "print operators", "dnsadmins", "group policy creator owners",
    "key admins", "enterprise key admins", "hyper-v administrators", "esx admins",
    "admins. del dominio", "administrators dell'organizzazione", "admins. schema",
    "operatori account", "operatori di backup", "operatori server", "operatori di stampa",
    "proprietari autori criteri di gruppo",
}

ACCOUNT_DI_SISTEMA = {"system", "sistema", "local service", "network service", "anonymous logon", "-", ""}

TIPI_ACCESSO = {
    "2": "Interattivo (alla console)", "3": "Di rete", "4": "Processo pianificato", "5": "Servizio",
    "7": "Sblocco della sessione", "8": "Di rete (password in chiaro)", "9": "Nuove credenziali",
    "10": "Desktop remoto", "11": "Interattivo (credenziali in cache)",
}
ACCESSI_INTERATTIVI = {"2", "7", "10", "11"}

# Event ID letti in modalità «Accessi e amministrazione», come intervalli per la query XPath
# di wevtutil (Windows accetta poche condizioni in OR: gli intervalli le tengono sotto il limite).
EVENTI_SECURITY = [
    (1102, 1102), (4616, 4616), (4624, 4625), (4634, 4634), (4647, 4648), (4672, 4672),
    (4697, 4698), (4719, 4720), (4722, 4726), (4728, 4729), (4732, 4733), (4738, 4738),
    (4740, 4740), (4756, 4757), (4767, 4767), (4771, 4771), (4776, 4776),
]
EVENTI_SYSTEM = [(104, 104), (6005, 6006), (6008, 6008), (7045, 7045)]


def xpath(canale: str, dopo_record: int | None, *, tutto: bool, prima_volta_ms: int = 0,
          fino_a: int | None = None) -> str:
    """Filtro XPath per ``wevtutil qe``: solo i record dopo il segnalibro, solo gli Event ID utili."""
    condizioni = []
    if fino_a is not None:
        condizioni.append(f"EventRecordID <= {int(fino_a)}")
    if dopo_record is not None:
        condizioni.append(f"EventRecordID > {int(dopo_record)}")
    elif prima_volta_ms:
        condizioni.append(f"TimeCreated[timediff(@SystemTime) <= {int(prima_volta_ms)}]")
    if not tutto:
        intervalli = EVENTI_SECURITY if canale.lower() == "security" else EVENTI_SYSTEM if canale.lower() == "system" else []
        if intervalli:
            parti = [f"EventID={a}" if a == b else f"(EventID >= {a} and EventID <= {b})" for a, b in intervalli]
            condizioni.append("(" + " or ".join(parti) + ")")
    return "*[System[" + " and ".join(condizioni) + "]]" if condizioni else "*"


# ── Windows ───────────────────────────────────────────────────────────────────

NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def normalizza_windows(ev) -> dict:
    """Un ``<Event>`` (ElementTree) → dati da archiviare (tutti i campi, niente testo tradotto)."""
    s = ev.find(f"{NS}System")

    def testo(tag):
        el = s.find(f"{NS}{tag}") if s is not None else None
        return (el.text or "").strip() if el is not None and el.text else ""

    def attr(tag, nome):
        el = s.find(f"{NS}{tag}") if s is not None else None
        return el.get(nome, "") if el is not None else ""

    dati: dict[str, str] = {}
    ed = ev.find(f"{NS}EventData")
    if ed is not None:
        for i, d in enumerate(ed.findall(f"{NS}Data")):
            dati[d.get("Name") or f"_{i}"] = (d.text or "").strip()
    ud = ev.find(f"{NS}UserData")
    if ud is not None:
        for figlio in ud.iter():
            if figlio is not ud and len(figlio) == 0 and figlio.text and figlio.text.strip():
                dati[figlio.tag.split("}")[-1]] = figlio.text.strip()
    try:
        event_id = int(testo("EventID") or 0)
    except ValueError:
        event_id = 0
    try:
        record = int(testo("EventRecordID") or 0)
    except ValueError:
        record = 0
    return {
        "id": event_id, "rec": record, "t": attr("TimeCreated", "SystemTime"), "canale": testo("Channel"),
        "pc": testo("Computer"), "prov": attr("Provider", "Name"), "kw": testo("Keywords"), "dati": dati,
    }


@dataclass
class Indice:
    categoria: str
    descrizione: str
    account: str = ""
    dominio: str = ""
    account_target: str = ""
    ip_origine: str = ""
    tipo_accesso: str = ""
    esito: str = ""
    gravita: str = ""
    dedup: str = ""

    def campi(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "dedup"}


def _account_reale(nome: str) -> bool:
    n = (nome or "").strip().lower()
    return bool(n) and n not in ACCOUNT_DI_SISTEMA and not n.endswith("$") and not n.startswith(("dwm-", "umfd-"))


def _ip(v: str) -> str:
    v = (v or "").strip()
    return "" if v in ("-", "::1", "127.0.0.1") else v.removeprefix("::ffff:")


def classifica_windows(d: dict, privilegiati: set[str] | frozenset = frozenset()) -> Indice | None:
    """Dati di un evento Windows → voce d'indice, oppure None se basta l'archivio."""
    eid, x = d.get("id"), d.get("dati") or {}
    utente, dominio = x.get("TargetUserName", ""), x.get("TargetDomainName", "")
    soggetto, dom_sogg = x.get("SubjectUserName", ""), x.get("SubjectDomainName", "")
    ip = _ip(x.get("IpAddress", "") or x.get("Workstation", ""))
    tipo = x.get("LogonType", "")
    tipo_txt = TIPI_ACCESSO.get(tipo, f"Tipo {tipo}" if tipo else "")
    priv = (utente or "").lower() in privilegiati

    if eid == 4624:
        if not _account_reale(utente) or not (tipo in ACCESSI_INTERATTIVI or (tipo == "3" and priv)):
            return None
        return Indice("accesso", f"Accesso {tipo_txt.lower()}", utente, dominio, ip_origine=ip,
                      tipo_accesso=tipo_txt, esito="ok", dedup=f"4624|{utente}|{tipo}|{ip}")
    if eid == 4625:
        if not _account_reale(utente) and utente.lower() not in ("", "-"):
            return None
        motivo = MOTIVI_FALLIMENTO.get((x.get("SubStatus") or x.get("Status") or "").lower(), "")
        return Indice("accesso_fallito", "Accesso non riuscito" + (f": {motivo}" if motivo else ""), utente, dominio,
                      ip_origine=ip, tipo_accesso=tipo_txt, esito="ko")
    if eid == 4771:
        nome = x.get("TargetUserName", "")
        if not _account_reale(nome):
            return None
        return Indice("accesso_fallito", "Accesso al dominio non riuscito (Kerberos)", nome,
                      ip_origine=_ip(x.get("IpAddress", "")), esito="ko")
    if eid == 4776:
        if (x.get("Status") or "0x0").lower() in ("0x0", "0"):
            return None
        nome = x.get("TargetUserName", "")
        motivo = MOTIVI_FALLIMENTO.get((x.get("Status") or "").lower(), "")
        if not _account_reale(nome):
            return None
        return Indice("accesso_fallito", "Accesso al dominio non riuscito (NTLM)" + (f": {motivo}" if motivo else ""),
                      nome, ip_origine=_ip(x.get("Workstation", "")), esito="ko")
    if eid in (4634, 4647):
        if not _account_reale(utente) or (eid == 4634 and tipo not in ACCESSI_INTERATTIVI):
            return None
        return Indice("uscita", "Uscita dalla sessione", utente, dominio, tipo_accesso=tipo_txt,
                      dedup=f"{eid}|{utente}|{tipo}")
    if eid == 4672:
        if not _account_reale(soggetto):
            return None
        return Indice("accesso_privilegiato", "Accesso con privilegi di amministratore", soggetto, dom_sogg,
                      esito="ok", dedup=f"4672|{soggetto}")
    if eid == 4740:
        # Nel 4740 TargetDomainName è il PC da cui arrivavano i tentativi.
        pc = x.get("TargetDomainName", "")
        return Indice("account_bloccato", "Account bloccato per troppi tentativi" + (f" (da {pc})" if pc else ""),
                      utente, ip_origine=pc, esito="ko")
    if eid == 4720:
        return Indice("account_creato", f"Account {utente} creato da {soggetto}", soggetto, dom_sogg, account_target=utente)
    if eid == 4726:
        return Indice("account_eliminato", f"Account {utente} eliminato da {soggetto}", soggetto, dom_sogg, account_target=utente)
    if eid in (4722, 4725, 4767, 4723, 4724):
        azione = {4722: "abilitato", 4725: "disabilitato", 4767: "sbloccato", 4723: "password cambiata",
                  4724: "password reimpostata"}[eid]
        return Indice("account_modificato", f"Account {utente}: {azione}" + (f" da {soggetto}" if eid != 4723 else ""),
                      soggetto, dom_sogg, account_target=utente)
    if eid in (4728, 4732, 4756, 4729, 4733, 4757):
        gruppo = x.get("TargetUserName", "")
        membro = x.get("MemberName", "") or x.get("MemberSid", "")
        membro_breve = membro.split(",")[0].removeprefix("CN=") if membro.startswith("CN=") else membro
        aggiunta = eid in (4728, 4732, 4756)
        privil = gruppo.lower() in GRUPPI_PRIVILEGIATI
        if aggiunta and privil:
            return Indice("gruppo_privilegiato", f"{membro_breve} aggiunto al gruppo «{gruppo}» da {soggetto}",
                          soggetto, dom_sogg, account_target=membro_breve, gravita="high")
        verbo = "aggiunto al" if aggiunta else "tolto dal"
        return Indice("gruppo_modificato", f"{membro_breve} {verbo} gruppo «{gruppo}» da {soggetto}", soggetto, dom_sogg,
                      account_target=membro_breve, gravita="warning" if privil else "info")
    if eid == 4738:
        if not _account_reale(soggetto):
            return None
        return Indice("account_modificato", f"Account {utente} modificato da {soggetto}", soggetto, dom_sogg,
                      account_target=utente, dedup=f"4738|{utente}|{soggetto}")
    if eid == 1102 or (eid == 104 and "eventlog" in (d.get("prov") or "").lower()):
        chi = x.get("SubjectUserName", "") or soggetto
        canale = x.get("Channel", "") or ("Security" if eid == 1102 else "")
        return Indice("registro_cancellato", f"Registro {canale or 'eventi'} cancellato" + (f" da {chi}" if chi else ""), chi,
                      x.get("SubjectDomainName", ""))
    if eid == 4719:
        return Indice("audit_modificato", f"Criteri di audit modificati da {soggetto}", soggetto, dom_sogg)
    if eid in (4697, 7045):
        servizio = x.get("ServiceName", "") or x.get("_0", "")
        file_ = x.get("ServiceFileName", "") or x.get("ImagePath", "") or x.get("_1", "")
        chi = soggetto if eid == 4697 else x.get("AccountName", "")
        return Indice("servizio_installato", f"Servizio «{servizio}» installato" + (f" ({file_[:150]})" if file_ else ""),
                      chi, dom_sogg, dedup=f"svc|{servizio}")
    if eid == 4698:
        return Indice("attivita_pianificata", f"Attività pianificata «{x.get('TaskName', '')}» creata da {soggetto}",
                      soggetto, dom_sogg)
    if eid == 4648:
        return None  # solo archivio: troppo frequente, l'accesso vero è già nel 4624
    if eid == 4616:
        if not _account_reale(soggetto):
            return None
        return Indice("ora_modificata", f"Orologio cambiato da {soggetto}", soggetto, dom_sogg)
    if eid in (6005, 6006, 6008):
        testo = {6005: "Sistema avviato (registro eventi partito)", 6006: "Sistema arrestato correttamente",
                 6008: "Arresto imprevisto del sistema"}[eid]
        return Indice("avvio_arresto", testo, gravita="warning" if eid == 6008 else "info")
    return None


MOTIVI_FALLIMENTO = {
    "0xc000006a": "password sbagliata", "0xc0000064": "utente inesistente", "0xc0000234": "account bloccato",
    "0xc0000072": "account disabilitato", "0xc000006f": "fuori dall'orario consentito",
    "0xc0000070": "postazione non consentita", "0xc0000071": "password scaduta", "0xc0000193": "account scaduto",
    "0xc0000224": "password da cambiare", "0xc000015b": "tipo di accesso non concesso",
}


def quando_windows(d: dict) -> datetime | None:
    t = (d.get("t") or "").strip()
    if not t:
        return None
    t = re.sub(r"(\.\d{6})\d+", r"\1", t)  # Windows dà 7-9 decimali, Python ne vuole 6
    dt = parse_datetime(t)
    if dt and timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


# ── Syslog ────────────────────────────────────────────────────────────────────

_PRI = re.compile(rb"^<(\d{1,3})>")
_RFC5424 = re.compile(r"^1 (\S+) (\S+) (\S+) (\S+) (\S+) (?:-|(?:\[.*?\])+) ?(.*)$", re.S)
_RFC3164 = re.compile(r"^([A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d) (\S+) ([^:\[\s]+)(?:\[\d+\])?: ?(.*)$", re.S)
# ESXi e molti apparati: come RFC 3164 ma con l'ora ISO 8601 (senza il «1» di RFC 5424).
_ISO3164 = re.compile(r"^(\d{4}-\d\d-\d\dT\S+) (\S+) ([^:\[\s]+)(?:\[\d+\])?: ?(.*)$", re.S)


def parse_syslog(raw: bytes, ip: str) -> dict:
    """Un messaggio syslog (RFC 5424 o 3164) → dati da archiviare. Il testo originale resta in ``raw``."""
    testo = raw.decode("utf-8", errors="replace").strip("\x00\r\n ")
    d: dict = {"ip": ip, "raw": testo[:8000]}
    m = _PRI.match(raw)
    corpo = testo
    if m:
        pri = int(m.group(1))
        d.update(pri=pri, fac=pri >> 3, sev=pri & 7)
        corpo = testo[m.end():]
    r = _RFC5424.match(corpo)
    if r:
        d.update(t=r.group(1), host=r.group(2) if r.group(2) != "-" else "", app=r.group(3) if r.group(3) != "-" else "",
                 msg=r.group(6))
        return d
    r = _RFC3164.match(corpo) or _ISO3164.match(corpo)
    if r:
        d.update(t=r.group(1), host=r.group(2), app=r.group(3), msg=r.group(4))
        return d
    d["msg"] = corpo
    return d


@dataclass(frozen=True)
class RegolaSyslog:
    regex: re.Pattern
    categoria: str
    descrizione: str
    esito: str = ""


def _r(pattern):
    return re.compile(pattern, re.I)


# Gruppi con nome: utente, ip. L'ordine conta: la prima che corrisponde vince.
REGOLE_SYSLOG: tuple[RegolaSyslog, ...] = (
    # ESXi / vCenter (hostd, vpxa, sshd)
    RegolaSyslog(_r(r"Accepted (?:password|keyboard-interactive/pam|publickey) for (?:user )?(?P<utente>\S+) from (?P<ip>[\d.:a-f]+)"), "accesso", "Accesso SSH", "ok"),
    RegolaSyslog(_r(r"User (?P<utente>\S+?)@(?P<ip>[\d.:a-f]+) logged in"), "accesso", "Accesso alla console di gestione", "ok"),
    RegolaSyslog(_r(r"User (?P<utente>\S+?)@(?P<ip>[\d.:a-f]+) logged out"), "uscita", "Uscita dalla console di gestione"),
    RegolaSyslog(_r(r"Rejected password for user (?P<utente>\S+) from (?P<ip>[\d.:a-f]+)"), "accesso_fallito", "Password rifiutata", "ko"),
    RegolaSyslog(_r(r"Failed (?:password|keyboard-interactive/pam|publickey) for (?:invalid user )?(?P<utente>\S+) from (?P<ip>[\d.:a-f]+)"), "accesso_fallito", "Accesso SSH non riuscito", "ko"),
    RegolaSyslog(_r(r"Invalid user (?P<utente>\S+) from (?P<ip>[\d.:a-f]+)"), "accesso_fallito", "Accesso SSH con utente inesistente", "ko"),
    RegolaSyslog(_r(r"(?:SSH|ESXi Shell)(?: access| login)? (?:has been |is )?enabled"), "configurazione", "Accesso SSH o shell abilitato sull'host"),
    RegolaSyslog(_r(r"lockdown mode (?:disabled|has been disabled)"), "configurazione", "Modalità lockdown disattivata"),
    # Cisco IOS / Catalyst
    RegolaSyslog(_r(r"LOGIN_SUCCESS: Login Success \[user: (?P<utente>[^\]]+)\] \[Source: (?P<ip>[^\]]+)\]"), "accesso", "Accesso all'apparato", "ok"),
    RegolaSyslog(_r(r"LOGIN_FAILED: Login failed \[user: (?P<utente>[^\]]*)\] \[Source: (?P<ip>[^\]]+)\]"), "accesso_fallito", "Accesso all'apparato non riuscito", "ko"),
    RegolaSyslog(_r(r"CONFIG_I: Configured from \S+ by (?P<utente>\S+?)(?: on \S+)?(?: \((?P<ip>[\d.:a-f]+)\))?$"), "configurazione", "Configurazione dell'apparato modificata"),
    # HPE Aruba / ProCurve
    RegolaSyslog(_r(r"(?:User|Operator|Manager) (?P<utente>\S+)? ?logged in (?:via|from) (?P<ip>\S+)"), "accesso", "Accesso all'apparato", "ok"),
    RegolaSyslog(_r(r"Invalid (?:user name|username)/password on (?P<ip>\S+)"), "accesso_fallito", "Accesso all'apparato non riuscito", "ko"),
    # WatchGuard Firebox
    RegolaSyslog(_r(r"Authentication of \S+ user \[(?P<utente>[^@\]]+)(?:@[^\]]*)?\] from (?P<ip>[\d.]+) was accepted"), "accesso", "Accesso autenticato sul firewall", "ok"),
    RegolaSyslog(_r(r"Authentication of \S+ user \[(?P<utente>[^@\]]+)(?:@[^\]]*)?\] from (?P<ip>[\d.]+) was rejected"), "accesso_fallito", "Accesso al firewall rifiutato", "ko"),
    RegolaSyslog(_r(r"Management user (?P<utente>\S+?)(?:@\S+)? from (?P<ip>[\d.]+) log(?:ged)? in"), "accesso", "Accesso alla gestione del firewall", "ok"),
    # Synology DSM / QNAP
    RegolaSyslog(_r(r"User \[(?P<utente>[^\]]+)\] from \[(?P<ip>[^\]]+)\] signed in to \[[^\]]+\] successfully"), "accesso", "Accesso al NAS", "ok"),
    RegolaSyslog(_r(r"User \[(?P<utente>[^\]]+)\] from \[(?P<ip>[^\]]+)\] failed to sign in"), "accesso_fallito", "Accesso al NAS non riuscito", "ko"),
    # Linux
    RegolaSyslog(_r(r"^\s*(?P<utente>\S+) : .*COMMAND=(?P<comando>.+)$"), "comando_privilegiato", "Comando eseguito con sudo"),
    RegolaSyslog(_r(r"session opened for user root by (?P<utente>\S+?)\(?"), "accesso_privilegiato", "Sessione da root aperta"),
    # Generiche, per gli apparati senza una regola dedicata
    RegolaSyslog(_r(r"(?:login|log-in|authentication|sign-in)\s+(?:failed|failure|rejected|denied)(?:.*?user[\s:=\[\"']+(?P<utente>[\w.@\\-]+))?(?:.*?from\s+(?P<ip>[\d.:a-f]{7,}))?"), "accesso_fallito", "Accesso non riuscito", "ko"),
    RegolaSyslog(_r(r"(?:user[\s:=\[\"']+(?P<utente>[\w.@\\-]+).{0,40})?(?:logged in|login success(?:ful)?|logon success)(?:.*?from\s+(?P<ip>[\d.:a-f]{7,}))?"), "accesso", "Accesso", "ok"),
)


def classifica_syslog(d: dict) -> Indice | None:
    msg = (d.get("msg") or d.get("raw") or "")[:2000]
    for regola in REGOLE_SYSLOG:
        m = regola.regex.search(msg)
        if not m:
            continue
        g = m.groupdict()
        utente = (g.get("utente") or "").strip("'\"[] ")
        descr = regola.descrizione
        if g.get("comando"):
            descr += f": {g['comando'].strip()[:200]}"
        return Indice(regola.categoria, descr, utente, ip_origine=_ip(g.get("ip") or ""), esito=regola.esito,
                      dedup=f"sys|{regola.categoria}|{utente}|{g.get('ip') or ''}" if regola.categoria in ("accesso", "uscita") else "")
    return None


_MESI = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def quando_syslog(d: dict, ricevuto: datetime) -> datetime:
    """Ora del messaggio; se manca o non si legge, l'ora di ricezione (gli apparati spesso non hanno l'anno)."""
    t = (d.get("t") or "").strip()
    if not t:
        return ricevuto
    dt = parse_datetime(t) if "T" in t else None
    if dt:
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
    m = re.match(r"([A-Za-z]{3}) +(\d{1,2}) (\d\d):(\d\d):(\d\d)", t)
    if m and m.group(1).lower() in _MESI:
        locale = timezone.localtime(ricevuto)
        try:
            dt = locale.replace(month=_MESI[m.group(1).lower()], day=int(m.group(2)), hour=int(m.group(3)),
                                minute=int(m.group(4)), second=int(m.group(5)), microsecond=0)
        except ValueError:
            return ricevuto
        if dt - locale > timedelta(days=2):  # dicembre letto a gennaio
            dt = dt.replace(year=dt.year - 1)
        return dt
    return ricevuto


# ── Orario di lavoro ──────────────────────────────────────────────────────────


def fuori_orario(quando: datetime, inizio: time, fine: time) -> bool:
    locale = timezone.localtime(quando)
    if locale.weekday() >= 5:
        return True
    return not (inizio <= locale.time() < fine)
