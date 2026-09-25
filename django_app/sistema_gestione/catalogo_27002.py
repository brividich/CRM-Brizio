"""Catalogo dei 93 controlli dell'Allegato A di ISO/IEC 27001:2022 (ISO/IEC 27002:2022).

Codici ufficiali; titoli brevi in italiano scritti per il portale (non il testo
della norma). Fonte unica per la migrazione di seed e per l'import del MOD.165.
"""
from __future__ import annotations

TEMA_ORGANIZZATIVI = "ORG"
TEMA_PERSONE = "PER"
TEMA_FISICI = "FIS"
TEMA_TECNOLOGICI = "TEC"

TEMI = (
    (TEMA_ORGANIZZATIVI, "Controlli organizzativi"),
    (TEMA_PERSONE, "Controlli sulle persone"),
    (TEMA_FISICI, "Controlli fisici"),
    (TEMA_TECNOLOGICI, "Controlli tecnologici"),
)
_TEMA_DA_CAPITOLO = {"5": TEMA_ORGANIZZATIVI, "6": TEMA_PERSONE, "7": TEMA_FISICI, "8": TEMA_TECNOLOGICI}

CONTROLLI: tuple[tuple[str, str], ...] = (
    ("5.1", "Politiche per la sicurezza delle informazioni"),
    ("5.2", "Ruoli e responsabilità per la sicurezza delle informazioni"),
    ("5.3", "Separazione dei compiti"),
    ("5.4", "Responsabilità della direzione"),
    ("5.5", "Contatti con le autorità"),
    ("5.6", "Contatti con gruppi di interesse specialistici"),
    ("5.7", "Threat intelligence"),
    ("5.8", "Sicurezza delle informazioni nella gestione dei progetti"),
    ("5.9", "Inventario delle informazioni e degli altri asset associati"),
    ("5.10", "Utilizzo accettabile delle informazioni e degli asset"),
    ("5.11", "Restituzione degli asset"),
    ("5.12", "Classificazione delle informazioni"),
    ("5.13", "Etichettatura delle informazioni"),
    ("5.14", "Trasferimento delle informazioni"),
    ("5.15", "Controllo degli accessi"),
    ("5.16", "Gestione delle identità"),
    ("5.17", "Informazioni di autenticazione"),
    ("5.18", "Diritti di accesso"),
    ("5.19", "Sicurezza delle informazioni nei rapporti con i fornitori"),
    ("5.20", "Sicurezza delle informazioni negli accordi con i fornitori"),
    ("5.21", "Sicurezza delle informazioni nella filiera ICT"),
    ("5.22", "Monitoraggio, riesame e cambiamenti dei servizi dei fornitori"),
    ("5.23", "Sicurezza delle informazioni nell'uso dei servizi cloud"),
    ("5.24", "Pianificazione e preparazione della gestione degli incidenti"),
    ("5.25", "Valutazione e decisione sugli eventi di sicurezza"),
    ("5.26", "Risposta agli incidenti di sicurezza"),
    ("5.27", "Apprendimento dagli incidenti di sicurezza"),
    ("5.28", "Raccolta delle evidenze"),
    ("5.29", "Sicurezza delle informazioni durante un'interruzione"),
    ("5.30", "Prontezza ICT per la continuità operativa"),
    ("5.31", "Requisiti legali, statutari, regolamentari e contrattuali"),
    ("5.32", "Diritti di proprietà intellettuale"),
    ("5.33", "Protezione delle registrazioni"),
    ("5.34", "Privacy e protezione dei dati personali"),
    ("5.35", "Riesame indipendente della sicurezza delle informazioni"),
    ("5.36", "Conformità a politiche, regole e standard di sicurezza"),
    ("5.37", "Procedure operative documentate"),
    ("6.1", "Screening del personale"),
    ("6.2", "Termini e condizioni di impiego"),
    ("6.3", "Consapevolezza, istruzione e formazione sulla sicurezza"),
    ("6.4", "Processo disciplinare"),
    ("6.5", "Responsabilità dopo la cessazione o il cambio di impiego"),
    ("6.6", "Accordi di riservatezza"),
    ("6.7", "Lavoro da remoto"),
    ("6.8", "Segnalazione degli eventi di sicurezza"),
    ("7.1", "Perimetri di sicurezza fisica"),
    ("7.2", "Controllo degli accessi fisici"),
    ("7.3", "Sicurezza di uffici, locali e strutture"),
    ("7.4", "Monitoraggio della sicurezza fisica"),
    ("7.5", "Protezione dalle minacce fisiche e ambientali"),
    ("7.6", "Lavoro nelle aree sicure"),
    ("7.7", "Scrivania e schermo puliti"),
    ("7.8", "Collocazione e protezione delle apparecchiature"),
    ("7.9", "Sicurezza degli asset fuori sede"),
    ("7.10", "Supporti di memorizzazione"),
    ("7.11", "Servizi di supporto (utenze)"),
    ("7.12", "Sicurezza dei cablaggi"),
    ("7.13", "Manutenzione delle apparecchiature"),
    ("7.14", "Dismissione o riutilizzo sicuro delle apparecchiature"),
    ("8.1", "Dispositivi endpoint degli utenti"),
    ("8.2", "Diritti di accesso privilegiati"),
    ("8.3", "Limitazione dell'accesso alle informazioni"),
    ("8.4", "Accesso al codice sorgente"),
    ("8.5", "Autenticazione sicura"),
    ("8.6", "Gestione della capacità"),
    ("8.7", "Protezione dal malware"),
    ("8.8", "Gestione delle vulnerabilità tecniche"),
    ("8.9", "Gestione della configurazione"),
    ("8.10", "Cancellazione delle informazioni"),
    ("8.11", "Mascheramento dei dati"),
    ("8.12", "Prevenzione della fuga di dati"),
    ("8.13", "Backup delle informazioni"),
    ("8.14", "Ridondanza delle strutture di elaborazione"),
    ("8.15", "Registrazione degli eventi (logging)"),
    ("8.16", "Attività di monitoraggio"),
    ("8.17", "Sincronizzazione degli orologi"),
    ("8.18", "Uso di programmi di utilità privilegiati"),
    ("8.19", "Installazione di software sui sistemi in esercizio"),
    ("8.20", "Sicurezza delle reti"),
    ("8.21", "Sicurezza dei servizi di rete"),
    ("8.22", "Segregazione delle reti"),
    ("8.23", "Filtraggio web"),
    ("8.24", "Uso della crittografia"),
    ("8.25", "Ciclo di vita dello sviluppo sicuro"),
    ("8.26", "Requisiti di sicurezza delle applicazioni"),
    ("8.27", "Principi di architettura e ingegneria dei sistemi sicuri"),
    ("8.28", "Codifica sicura"),
    ("8.29", "Test di sicurezza nello sviluppo e nell'accettazione"),
    ("8.30", "Sviluppo affidato all'esterno"),
    ("8.31", "Separazione degli ambienti di sviluppo, test e produzione"),
    ("8.32", "Gestione dei cambiamenti"),
    ("8.33", "Informazioni di test"),
    ("8.34", "Protezione dei sistemi informativi durante i test di audit"),
)


def tema_di(codice: str) -> str:
    return _TEMA_DA_CAPITOLO.get(codice.split(".", 1)[0], TEMA_ORGANIZZATIVI)


def ordine_di(codice: str) -> int:
    capitolo, numero = codice.split(".", 1)
    return int(capitolo) * 100 + int(numero)
