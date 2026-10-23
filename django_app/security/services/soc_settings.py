"""Impostazioni operative del SOC (avvisi automatici, report programmato, soglie).

Un solo elenco descrive ogni impostazione: chiave, default, etichetta, spiegazione. La
pagina `/soc/impostazioni/` lo usa per disegnare il modulo e i servizi lo usano per
leggere i valori, così pagina e comportamento non possono divergere. I valori stanno in
``SecurityCenterSetting`` (categoria ``avvisi``): nessuna migrazione, audit già incluso.

Tutti gli avvisi nascono **spenti**: in produzione nessuno riceve mail finché qualcuno non
li accende e sceglie a quali canali mandarli.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from security.models import Severity
from security.services.configuration import get_setting, set_setting

CATEGORY = "avvisi"


@dataclass(frozen=True)
class Option:
    key: str
    default: object
    label: str
    help: str = ""
    kind: str = "bool"  # bool | int | choice | channels | text
    choices: tuple = field(default_factory=tuple)
    min_value: int = 0
    max_value: int = 0
    unit: str = ""


SECTIONS = [
    {
        "code": "incidenti",
        "title": "Scadenze incidenti NIS2 e GDPR",
        "intro": "Un avviso quando una notifica al CSIRT o al Garante sta per scadere e uno quando è scaduta. Ogni avviso parte una volta sola.",
        "options": [
            Option("avvisi.incidenti.attivo", False, "Avvisa sulle scadenze degli incidenti"),
            Option("avvisi.incidenti.anticipo_ore", 6, "Anticipo", "Ore prima della scadenza in cui parte il primo avviso.", "int", min_value=1, max_value=48),
            Option("avvisi.incidenti.canali", [], "Canali", "Dove mandare gli avvisi.", "channels"),
        ],
    },
    {
        "code": "backup",
        "title": "Backup dei PC e dei server",
        "intro": "Un avviso per ogni PC che resta senza backup riuscito oltre la soglia o il cui ultimo backup è fallito. Riparte solo dopo un nuovo backup riuscito.",
        "options": [
            Option("avvisi.backup.attivo", False, "Avvisa sui backup dei PC"),
            Option("avvisi.backup.giorni", 3, "Soglia", "Giorni senza backup riuscito dopo cui un PC va guardato (vale anche per la pagina Backup).", "int", min_value=1, max_value=30),
            Option("avvisi.backup.fallito", True, "Avvisa anche quando l'ultimo backup è fallito", "Senza aspettare la soglia."),
            Option("avvisi.backup.canali", [], "Canali", "Dove mandare gli avvisi.", "channels"),
        ],
    },
    {
        "code": "report",
        "title": "Report periodico automatico",
        "intro": "Il report del SOC inviato da solo ai canali scelti: via mail con il PDF allegato, su Teams con il riassunto e il link.",
        "options": [
            Option("report.auto.attivo", False, "Invia il report da solo"),
            Option("report.auto.frequenza", "weekly", "Frequenza", "Settimanale: il lunedì, sulla settimana prima. Mensile: il giorno 1, sul mese prima.", "choice",
                   choices=(("weekly", "Settimanale (lunedì)"), ("monthly", "Mensile (giorno 1)"))),
            Option("report.auto.canali", [], "Canali", "Dove mandare il report.", "channels"),
        ],
    },
    {
        "code": "soppressione_appresa",
        "title": "Soppressione appresa",
        "intro": "Quando lo stesso alert viene disattivato più volte a mano (falso positivo, non rilevante, rischio accettato, silenziato) "
                 "il sistema crea una regola di soppressione su quell'impronta esatta: le occorrenze successive restano negli Eventi soppressi, "
                 "senza alert. Ogni regola appresa scade, si revoca con un clic e si spegne da sola se qualcuno riapre l'alert.",
        "channels_optional": True,
        "options": [
            Option("soppressione.appresa.attivo", True, "Impara dalle disattivazioni ripetute"),
            Option("soppressione.appresa.soglia", 3, "Soglia", "Disattivazioni della stessa impronta che creano la regola.", "int", min_value=2, max_value=10, unit="disattivazioni"),
            Option("soppressione.appresa.finestra_giorni", 90, "Finestra", "Giorni in cui contare le disattivazioni.", "int", min_value=7, max_value=365),
            Option("soppressione.appresa.durata_giorni", 180, "Durata", "Giorni di validità della regola appresa.", "int", min_value=7, max_value=365),
            Option("soppressione.appresa.escludi_critici", True, "Mai per severità critica", "Gli eventi critici fanno sempre nascere l'alert."),
            Option("soppressione.appresa.escludi_kev", True, "Mai per CVE sfruttate (CISA KEV)"),
            Option("soppressione.appresa.escludi_minacce", True, "Mai per minacce, malware, ransomware, botnet"),
            Option("soppressione.appresa.blocca_aggravamento", True, "Alert comunque se la severità sale",
                   "Se l'evento è più grave delle disattivazioni che hanno creato la regola, l'alert nasce."),
            Option("soppressione.appresa.tipi_esclusi", "", "Tipi di evento esclusi", "Elenco separato da virgole (es. source_silent, possible_sender_spoofing).", "text"),
            Option("soppressione.appresa.canali", [], "Canali", "Dove avvisare quando nasce una regola appresa (facoltativo).", "channels"),
        ],
    },
    {
        "code": "impatto_cve",
        "title": "Impatto CVE sugli asset",
        "intro": "Il job orario legge da NVD i range di versione vulnerabili, da CISA KEV le CVE sfruttate e (facoltativo) "
                 "il punteggio EPSS, poi incrocia le CVE con l'inventario software importato. Serve accesso Internet dal server.",
        "channels_optional": True,
        "options": [
            Option("cve.arricchimento.attivo", False, "Arricchisci le CVE da NVD e CISA KEV"),
            Option("cve.epss.attivo", True, "Leggi anche il punteggio EPSS (FIRST.org)"),
            Option("cve.inventario.freschezza_giorni", 30, "Inventario recente",
                   "Oltre questi giorni l'inventario è «vecchio»: gli esiti diventano da verificare.", "int", min_value=1, max_value=180),
            Option("cve.impatto.alert", True, "Apri un alert quando un PC risulta impattato",
                   "Solo per CVE critiche (CVSS 9 o più) o sfruttate attivamente (CISA KEV). Un alert per CVE, che si aggiorna se altri PC si aggiungono."),
            Option("cve.impatto.ticket", True, "Apri anche il ticket di rimedio",
                   "Se la CVE ha già un ticket aperto (per esempio da Defender), l'alert si collega a quello."),
        ],
    },
    {
        "code": "software_conformita",
        "title": "Software non conforme",
        "intro": "Confronta l'inventario software con le decisioni del Catalogo software (modulo Asset): un alert per prodotto quando "
                 "nuovi PC hanno un software non autorizzato, da rimuovere o in una versione sotto la minima. Si controlla dopo ogni "
                 "import dell'inventario e ogni modifica al catalogo.",
        "channels_optional": True,
        "options": [
            Option("software.non_autorizzato.alert", True, "Alert per software non autorizzato", "Severità alta."),
            Option("software.da_rimuovere.alert", True, "Alert per software da rimuovere"),
            Option("software.versione_minima.alert", True, "Alert per versioni sotto la minima",
                   "Solo per i software «Consentiti» con una versione minima; le versioni non confrontabili non vengono mai segnalate."),
        ],
    },
    {
        "code": "defender",
        "title": "Alert di Microsoft Defender",
        "intro": "Ogni 15 minuti il SOC legge da Microsoft Graph gli alert di Defender aggiornati e ne fa un alert del SOC "
                 "(uno per alert di Defender, aggiornato se cambia, chiuso quando Defender lo dà risolto). Dei dati si tengono "
                 "titolo, severità, stato, dispositivi e il link a Defender; degli utenti coinvolti solo il numero. "
                 "Serve il permesso «SecurityAlert.Read.All» con consenso amministratore sull'app Graph del portale.",
        "channels_optional": True,
        "options": [
            Option("defender.alert.attivo", False, "Leggi gli alert di Defender"),
            Option("defender.severita_minima", Severity.MEDIUM, "Severità minima per l'alert",
                   "Sotto questa soglia l'alert di Defender resta un evento (conta nei KPI, non apre alert).", "choice",
                   choices=((Severity.LOW, "Bassa"), (Severity.MEDIUM, "Media"), (Severity.HIGH, "Alta"))),
            Option("defender.primo_giro_giorni", 7, "Primo giro", "Giorni di storico letti la prima volta.", "int", min_value=1, max_value=30),
            Option("defender.incidenti.attivo", False, "Raggruppa per incidente",
                   "Un solo alert del SOC per incidente di Defender (alert correlati da Defender), chiuso quando Defender "
                   "risolve l'incidente; gli alert singoli dello stesso incidente restano eventi. Serve SecurityIncident.Read.All."),
            Option("defender.software.attivo", False, "Leggi il software dei PC",
                   "Ogni mattina alle 06:20 il software installato sui PC collegati a Defender entra nell'inventario del SOC "
                   "(fonte «Microsoft Defender for Endpoint»): CVE e impatti si aggiornano da soli. Serve Software.Read.All "
                   "dell'API WindowsDefenderATP."),
            Option("defender.vulnerabilita.attivo", False, "Confronta le CVE con Defender",
                   "Ogni mattina alle 06:25 legge le vulnerabilità che Defender vede sui PC e le mette accanto al calcolo del SOC "
                   "nel pannello CVE («Defender conferma» / «Defender non la vede»). Non apre alert. Servono Vulnerability.Read.All "
                   "e Machine.Read.All dell'API WindowsDefenderATP."),
            Option("defender.secure_score.attivo", False, "Mostra il Secure Score",
                   "Punteggio di Microsoft Secure Score, andamento e le 5 azioni che valgono di più, nella Panoramica. "
                   "Letto ogni 12 ore. Serve SecurityEvents.Read.All."),
        ],
    },
    {
        "code": "veeam",
        "title": "Backup letti direttamente da Veeam",
        "intro": "Ogni 15 minuti il SOC legge dall'API REST di Veeam Backup & Replication le sessioni di backup concluse, con "
                 "l'esito di ogni macchina, e lo spazio dei repository: la pagina Backup non dipende più dalle mail di esito. "
                 "Se arrivano anche le mail, la stessa esecuzione conta una volta sola. Indirizzo, utente (di sola lettura) e "
                 "password stanno nel file .env del server (VEEAM_API_URL, VEEAM_API_USERNAME, VEEAM_API_PASSWORD).",
        "channels_optional": True,
        "options": [
            Option("veeam.api.attivo", False, "Leggi i backup dall'API di Veeam"),
            Option("veeam.primo_giro_giorni", 7, "Primo giro", "Giorni di storico letti la prima volta.", "int", min_value=1, max_value=30),
            Option("veeam.repository.alert", True, "Avvisa quando un repository si riempie",
                   "Un alert per repository sotto la soglia, chiuso da solo quando lo spazio torna sopra."),
            Option("veeam.repository.soglia_pct", 15, "Spazio libero minimo", "Sotto questa percentuale di spazio libero nasce l'alert.",
                   "int", min_value=1, max_value=50, unit="%"),
        ],
    },
    {
        "code": "entra",
        "title": "Microsoft Entra ID (account, modifiche amministrative, accessi)",
        "intro": "Due controlli su Microsoft 365, ciascuno con il suo interruttore. «Account di ex dipendenti»: ogni 6 ore "
                 "confronta gli account di Entra con l'anagrafica e apre un alert per ogni account ancora abilitato di una "
                 "persona cessata; l'alert si chiude da solo quando l'account viene disattivato. «Modifiche amministrative»: "
                 "ogni 15 minuti legge l'audit di Entra e apre un alert solo per le attività sensibili (ruoli di amministratore, "
                 "consensi e credenziali delle app, accesso condizionale, metodi MFA, federazione dei domini). «Accessi sospetti»: "
                 "ogni 15 minuti tentativi falliti a raffica, accessi da Paesi non ammessi, protocolli vecchi. "
                 "Servono i permessi «User.Read.All» e «AuditLog.Read.All» con consenso amministratore sull'app Graph del portale.",
        "channels_optional": True,
        "options": [
            Option("entra.account_cessati.attivo", False, "Controlla gli account degli ex dipendenti"),
            Option("entra.audit.attivo", False, "Leggi le modifiche amministrative di Entra"),
            Option("entra.primo_giro_giorni", 7, "Primo giro dell'audit", "Giorni di audit letti la prima volta.",
                   "int", min_value=1, max_value=30),
            Option("entra.accessi.attivo", False, "Segnala gli accessi sospetti a Microsoft 365",
                   "Tentativi falliti a raffica, accessi da Paesi non ammessi, accessi con protocolli vecchi (IMAP, POP, SMTP). "
                   "Un alert al giorno per account e motivo; i singoli accessi non vengono salvati."),
            Option("entra.paesi_ammessi", "IT", "Paesi ammessi",
                   "Codici a due lettere separati da virgole (es. IT, CH). Un accesso riuscito da un altro Paese apre un alert alto.",
                   "text"),
            Option("entra.falliti_soglia", 10, "Tentativi falliti",
                   "Quanti tentativi falliti sullo stesso account in un giro (15 minuti) aprono un alert.",
                   "int", min_value=3, max_value=100),
        ],
    },
    {
        "code": "apparati_rete",
        "title": "Apparati di rete (Contatori IT)",
        "intro": "Firewall, switch, server, storage, UPS e videoregistratori monitorati via SNMP in Contatori IT. Quando un "
                 "apparato non risponde per più controlli consecutivi (uno ogni 5 minuti) nasce un evento e un alert, uno per "
                 "apparato; l'alert si chiude da solo quando l'apparato risponde di nuovo. Stampanti, telecamere e sensori "
                 "restano nel solo monitor di Contatori IT.",
        "channels_optional": True,
        "options": [
            Option("apparati.irraggiungibile.attivo", True, "Manda al SOC le cadute degli apparati di rete"),
            Option("apparati.irraggiungibile.alert", True, "Apri un alert per ogni caduta",
                   "Spento: le cadute restano eventi (KPI) senza alert. Severità alta per i firewall, attenzione per gli altri."),
            Option("apparati.irraggiungibile.controlli", 2, "Controlli senza risposta",
                   "Quante interrogazioni consecutive fallite fanno una caduta.", "int", min_value=1, max_value=12, unit="controlli"),
            Option("apparati.tabella_mac.attivo", True, "Leggi la tabella MAC degli switch",
                   "Ogni notte alle 05:30 legge (solo lettura) su quale porta di ogni switch «Rete» sta ogni MAC: la scheda del PC "
                   "dice a quale switch e porta è collegato, la scheda dello switch quali PC ha sulle porte."),
        ],
    },
    {
        "code": "watchguard",
        "title": "WatchGuard Endpoint Security (API)",
        "intro": "Letture dall'API di WatchGuard Cloud, al posto degli export a mano. Servono le credenziali API (riquadro sotto). "
                 "Girano alle 06:10 e alle 13:10. Sola lettura: le patch si installano dalla console WatchGuard.",
        "channels_optional": True,
        "active_any": True,
        "options": [
            Option("watchguard.api.dispositivi", False, "Leggi i PC e lo stato della protezione",
                   "Agente, protezione, ultima connessione e MAC di ogni PC; anche i dispositivi trovati in rete senza agente."),
            Option("watchguard.api.software", False, "Leggi il software dei PC",
                   "L'inventario software WatchGuard arriva da solo, come se fosse l'export caricato a mano: CVE e impatti si aggiornano."),
            Option("watchguard.api.patch", False, "Leggi le patch mancanti",
                   "Patch pubblicate e non installate per PC, con le CVE che correggono, e l'esito dei task di installazione: "
                   "il pannello CVE dice dove la patch è pronta."),
        ],
    },
    {
        "code": "ai_sintesi",
        "title": "Sintesi del giorno già pronta",
        "intro": "L'AI locale prepara la «Sintesi del giorno» della Panoramica ogni 30 minuti nelle ore di lavoro, solo quando "
                 "i punti da guardare cambiano: chi apre la Panoramica la trova già scritta invece di aspettare. "
                 "Gira dal flusso «security_ai_sintesi» (Automazioni › designer).",
        "channels_optional": True,
        "options": [
            Option("ai.sintesi.attivo", True, "Prepara la sintesi in anticipo"),
        ],
    },
    {
        "code": "ai_lettura",
        "title": "Lettura assistita dall'AI",
        "intro": "Le mail e i file che un parser legge solo in parte («Da verificare») o che nessun parser riconosce vengono fatti "
                 "leggere all'AI locale, che propone i campi mancanti o dice che tipo di mail è. È solo una proposta: non crea "
                 "né chiude alert. Gira dal flusso «security_ai_lettura» (Automazioni › designer), dove si cambia la cadenza "
                 "e si aggiungono altre azioni.",
        "channels_optional": True,
        "options": [
            Option("ai.lettura.attivo", False, "Fai leggere all'AI le letture da verificare"),
            Option("ai.lettura.max_per_giro", 3, "Massimo per giro", "Elementi letti a ogni esecuzione: in produzione ogni lettura impegna l'AI per 15-40 secondi.",
                   "int", min_value=1, max_value=20, unit="elementi"),
            Option("ai.lettura.canali", [], "Canali", "Dove avvisare quando ci sono nuove proposte da controllare (facoltativo).", "channels"),
        ],
    },
]

OPTIONS = {option.key: option for section in SECTIONS for option in section["options"]}


def value(key):
    option = OPTIONS[key]
    raw = get_setting(key, option.default)
    if option.kind == "bool":
        return bool(raw)
    if option.kind == "int":
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return option.default
        return max(option.min_value, min(option.max_value, number)) if option.max_value else number
    if option.kind == "channels":
        return [int(x) for x in raw if str(x).isdigit()] if isinstance(raw, list) else []
    if option.kind == "choice":
        return raw if raw in dict(option.choices) else option.default
    if option.kind == "text":
        return str(raw or "").strip()
    return raw


def text_list(key):
    """Valore «text» letto come elenco separato da virgole (minuscolo, senza vuoti)."""
    return [part.strip().lower() for part in value(key).split(",") if part.strip()]


def backup_stale_days():
    return value("avvisi.backup.giorni")


def parse_post(data):
    """Valori puliti dal POST del modulo, con l'elenco degli errori (``(valori, errori)``)."""
    from security.models import SecurityNotificationChannel

    valid_channels = set(SecurityNotificationChannel.objects.values_list("pk", flat=True))
    values, errors = {}, []
    for key, option in OPTIONS.items():
        field_name = key.replace(".", "__")
        if option.kind == "bool":
            values[key] = data.get(field_name) == "on"
        elif option.kind == "int":
            if field_name not in data:
                continue  # campo non inviato (form parziale): resta il valore attuale
            raw = str(data.get(field_name, "")).strip()
            if not raw.isdigit() or not option.min_value <= int(raw) <= option.max_value:
                errors.append(f"{option.label}: un numero da {option.min_value} a {option.max_value}.")
                continue
            values[key] = int(raw)
        elif option.kind == "choice":
            if field_name not in data:
                continue  # campo non inviato (form parziale): resta il valore attuale
            raw = data.get(field_name, "")
            if raw not in dict(option.choices):
                errors.append(f"{option.label}: scelta non valida.")
                continue
            values[key] = raw
        elif option.kind == "channels":
            values[key] = sorted({int(x) for x in data.getlist(field_name) if str(x).isdigit() and int(x) in valid_channels})
        elif option.kind == "text":
            values[key] = str(data.get(field_name, "")).strip()[:500]
    for section in SECTIONS:
        if section.get("channels_optional"):
            continue
        active = next((o.key for o in section["options"] if o.kind == "bool"), None)
        channels = next((o.key for o in section["options"] if o.kind == "channels"), None)
        if active and channels and values.get(active) and not values.get(channels):
            errors.append(f"{section['title']}: per accenderli scegli almeno un canale.")
    return values, errors


def save(values, actor):
    """Salva solo ciò che è cambiato (ogni modifica finisce nell'audit della configurazione)."""
    changed = 0
    for key, new in values.items():
        if value(key) != new:
            set_setting(key, new, actor=actor, category=CATEGORY, description=OPTIONS[key].label)
            changed += 1
    return changed


def form_sections():
    """Sezioni con i valori correnti, pronte per il template."""
    out = []
    for section in SECTIONS:
        out.append({
            **section,
            "fields": [
                {"option": option, "name": option.key.replace(".", "__"), "value": value(option.key)}
                for option in section["options"]
            ],
            "active": (any(value(o.key) for o in section["options"] if o.kind == "bool") if section.get("active_any")
                       else value(next(o.key for o in section["options"] if o.kind == "bool"))),
        })
    return out
