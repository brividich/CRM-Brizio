"""Gli eventi del registro spiegati a chi non è un tecnico.

Per ogni tipo di evento: cosa vuol dire, quando è normale e cosa fare; una frase che racconta il
singolo evento (chi, cosa, da dove, su quale sistema) e le etichette in italiano dei campi
originali di Windows. Testi brevi, senza sigle: li leggono anche il titolare e l'auditor.
"""
from __future__ import annotations

from . import regole

# categoria → (cosa vuol dire, quando è normale, cosa fare)
SPIEGAZIONI: dict[str, tuple[str, str, str]] = {
    "accesso": (
        "Una persona è entrata: in un PC del dominio, in un server o in desktop remoto. «Accesso al dominio» è il "
        "controller di dominio che riconosce la persona quando accende o sblocca il PC.",
        "Normale durante l'orario di lavoro e dai PC che la persona usa di solito.",
        "Guardare gli accessi fuori orario, da PC o indirizzi insoliti, o di account di persone assenti o cessate. "
        "La scheda in «Persona o PC» mostra la giornata della persona.",
    ),
    "accesso_privilegiato": (
        "Un account con poteri di amministratore ha iniziato una sessione: può cambiare configurazioni, account e dati.",
        "Normale per gli amministratori di sistema nominati, quando lavorano.",
        "Se l'account non è tra gli amministratori nominati, o l'orario è insolito, chiedere all'amministratore cosa "
        "stava facendo. Gli account con privilegi senza nomina compaiono in «Elenchi › Account AD».",
    ),
    "uscita": (
        "Una persona è uscita dalla sessione (disconnessione o chiusura del desktop remoto).",
        "Sempre normale: serve a sapere quanto è durata una sessione.",
        "Nulla, salvo ricostruire una sessione durante un controllo.",
    ),
    "accesso_fallito": (
        "Qualcuno ha provato a entrare e non ci è riuscito; il motivo è scritto accanto (password sbagliata, "
        "utente inesistente, account disabilitato…).",
        "Qualche tentativo isolato è normale: una password digitata male, una password scaduta, un PC con "
        "credenziali vecchie salvate.",
        "Preoccuparsi per molti tentativi in pochi minuti, per account che non esistono o sono disabilitati, o per "
        "tentativi da internet: possono essere qualcuno che prova a indovinare la password. Se è sempre lo stesso "
        "PC, di solito ha una password vecchia salvata (unità di rete, Outlook, telefono).",
    ),
    "account_bloccato": (
        "Dopo troppi tentativi sbagliati Windows ha bloccato l'account: la persona non può entrare finché non "
        "si sblocca o passa il tempo di blocco.",
        "Capita quando qualcuno dimentica la password o ha una password vecchia salvata su un dispositivo.",
        "Chiedere alla persona; se non ne sa nulla, guardare da quale PC arrivavano i tentativi (indicato "
        "nell'evento) e controllarlo.",
    ),
    "account_creato": (
        "È stato creato un nuovo account in Active Directory.",
        "Normale per un nuovo assunto, un consulente o un nuovo servizio.",
        "Verificare che ci sia una richiesta (assunzione, ticket). Un account creato senza motivo è un segnale "
        "di allarme.",
    ),
    "account_eliminato": (
        "Un account è stato eliminato da Active Directory.",
        "Normale quando una persona lascia l'azienda.",
        "Verificare che corrisponda a una cessazione o a una richiesta.",
    ),
    "account_modificato": (
        "Un account è stato cambiato: abilitato, disabilitato, sbloccato, password cambiata o reimpostata.",
        "Normale quando l'IT sblocca o reimposta una password su richiesta.",
        "Una password reimpostata senza richiesta della persona merita una domanda all'IT.",
    ),
    "gruppo_privilegiato": (
        "Un account è stato aggiunto a un gruppo di amministratori (es. Domain Admins): da quel momento ha il "
        "controllo del dominio o del server.",
        "Raro. Va fatto solo per un nuovo amministratore di sistema, con lettera di nomina.",
        "Verificare subito chi l'ha fatto e perché. Senza una nomina va tolto e trattato come incidente.",
    ),
    "gruppo_modificato": (
        "Un account è stato aggiunto o tolto da un gruppo (permessi su cartelle, programmi, posta).",
        "Normale quando una persona cambia ruolo o ufficio.",
        "Controllare solo se il gruppo dà accesso a dati riservati o se nessuno ha chiesto la modifica.",
    ),
    "registro_cancellato": (
        "Il registro degli eventi di un server è stato svuotato a mano: le tracce precedenti su quel server sono "
        "sparite (qui restano nell'archivio sigillato fino all'ultima lettura).",
        "Quasi mai normale.",
        "Trattarlo come possibile tentativo di nascondere qualcosa: chiedere all'account indicato e aprire un "
        "incidente se non c'è una spiegazione.",
    ),
    "registro_svuotato": (
        "Il registro è stato svuotato da un programma di raccolta autorizzato (per esempio BusinessLog con "
        "«Cancella Registro»).",
        "Normale finché quel programma resta acceso con quell'opzione.",
        "Nulla; se compare spesso, spegnere «Cancella Registro» nel programma.",
    ),
    "audit_modificato": (
        "Qualcuno ha cambiato cosa Windows registra: si può spegnere la registrazione di accessi o modifiche.",
        "Raro, solo durante interventi pianificati sui criteri di gruppo.",
        "Chiedere all'account indicato: spegnere i registri è un modo per non lasciare tracce.",
    ),
    "servizio_installato": (
        "Su un server è stato installato un nuovo servizio (un programma che parte da solo con Windows).",
        "Normale durante installazioni e aggiornamenti di programmi.",
        "Se nessuno stava installando nulla, controllare il nome e il percorso del programma: è un metodo "
        "usato anche dai virus.",
    ),
    "attivita_pianificata": (
        "Una persona ha creato un'attività pianificata (un comando che parte da solo a orari stabiliti).",
        "Normale quando l'IT automatizza un lavoro.",
        "Se nessuno l'ha creata apposta, controllare cosa esegue.",
    ),
    "ora_modificata": (
        "Qualcuno ha cambiato l'orologio del sistema.",
        "Raro: di solito l'ora si regola da sola.",
        "Un orologio sbagliato rende meno affidabili tutti i registri: verificare chi e perché.",
    ),
    "avvio_arresto": (
        "Il sistema è stato acceso o spento; «arresto imprevisto» vuol dire che si è spento senza chiudere "
        "(mancanza di corrente, blocco, spegnimento forzato).",
        "Normale durante aggiornamenti e manutenzioni programmate.",
        "Un arresto imprevisto o un riavvio fuori dalle manutenzioni va capito.",
    ),
    "configurazione": (
        "La configurazione di un apparato (firewall, switch, ESXi, NAS) è stata cambiata.",
        "Normale durante interventi dell'IT o del fornitore.",
        "Se nessuno stava intervenendo, chiedere all'account indicato.",
    ),
    "comando_privilegiato": (
        "Su un server Linux o un apparato è stato eseguito un comando come amministratore.",
        "Normale durante la manutenzione.",
        "Controllare i comandi fuori orario o di account sconosciuti.",
    ),
    "file_letto": ("Un file è stato aperto.", "Normale nel lavoro di tutti i giorni.", "Si guarda solo dentro un'indagine."),
    "file_modificato": ("Un file è stato salvato o modificato.", "Normale nel lavoro di tutti i giorni.",
                        "Si guarda dentro un'indagine; molte modifiche in pochi minuti possono essere un ransomware."),
    "file_eliminato": ("Un file è stato cancellato.", "Normale ogni tanto.",
                       "Molte cancellazioni in pochi minuti dallo stesso account vanno capite subito."),
    "file_permessi": ("Sono stati cambiati i permessi di un file o di una cartella.", "Normale quando l'IT sistema gli accessi.",
                      "Verificare se riguarda cartelle riservate."),
    "stampa": ("È stato stampato un documento.", "Normale.", "Si guarda solo dentro un'indagine."),
    "usb_collegato": ("È stata collegata una chiavetta o un disco esterno.", "Normale sui PC, raro sui server.",
                      "Su un server chiedere chi l'ha collegata e perché."),
    "usb_file_scritto": ("Un file è stato copiato su una chiavetta o un disco esterno.", "Capita.",
                         "Molti file copiati su chiavetta in pochi minuti possono essere una fuga di dati."),
    "usb_file_letto": ("Un file è stato aperto da una chiavetta.", "Capita.", "Si guarda dentro un'indagine."),
    "usb_file_eliminato": ("Un file è stato cancellato da una chiavetta.", "Capita.", "Si guarda dentro un'indagine."),
}

# Una riga per sezione del catalogo, mostrata sopra l'elenco.
SEZIONI_TESTO = {
    "": "Tutto quello che il registro ha catalogato: accessi, accessi non riusciti, modifiche agli account, eventi dei "
        "server e degli apparati.",
    "accessi": "Chi è entrato, dove e da dove: accessi al dominio dai PC, accessi ai server e in desktop remoto, sblocchi.",
    "falliti": "Tentativi di entrare non riusciti e account bloccati, con il motivo. Molti tentativi ravvicinati vanno guardati.",
    "account": "Account creati, eliminati, bloccati o modificati e cambi ai gruppi. Le aggiunte ai gruppi di "
               "amministratori sono segnate come critiche.",
    "sistema": "Cosa è successo ai server e agli apparati: registri cancellati, criteri di registrazione cambiati, "
               "servizi installati, accensioni e spegnimenti, configurazioni modificate.",
    "syslog": "Gli eventi riconosciuti dagli apparati di rete e dai server non Windows (ESXi, firewall, switch, NAS, Linux).",
}

# Campi originali di Windows → etichetta in italiano (gli altri restano solo tra i dati tecnici).
CAMPI = {
    "TargetUserName": "Account", "TargetDomainName": "Dominio dell'account", "SubjectUserName": "Fatto da",
    "SubjectDomainName": "Dominio di chi l'ha fatto", "LogonType": "Tipo di accesso", "IpAddress": "Indirizzo di provenienza",
    "IpPort": "Porta di provenienza", "WorkstationName": "PC di provenienza", "Workstation": "PC di provenienza",
    "Status": "Esito", "SubStatus": "Motivo", "FailureReason": "Motivo (Windows)", "ProcessName": "Programma",
    "AuthenticationPackageName": "Metodo di verifica", "LogonProcessName": "Componente che ha gestito l'accesso",
    "ElevatedToken": "Con privilegi di amministratore", "MemberName": "Membro", "ServiceName": "Servizio",
    "ServiceFileName": "Programma del servizio", "TaskName": "Attività", "ObjectName": "File o oggetto",
    "AccessMask": "Operazione (codice)", "PrivilegeList": "Privilegi", "TicketEncryptionType": "Cifratura del biglietto",
    "TargetLogonId": "Numero della sessione", "SubjectLogonId": "Numero della sessione di chi l'ha fatto",
}
VALORI_SI_NO = {"%%1842": "Sì", "%%1843": "No"}
CODICI_KERBEROS = {"0x0": "riuscito", **regole.MOTIVI_KERBEROS}


def spiegazione(categoria: str) -> dict:
    cosa, normale, fare = SPIEGAZIONI.get(categoria, ("", "", ""))
    return {"cosa": cosa, "normale": normale, "fare": fare, "c_e": bool(cosa)}


def _valore(campo: str, valore: str, evento_id) -> str:
    v = (valore or "").strip()
    if campo == "LogonType":
        return regole.TIPI_ACCESSO.get(v, v)
    if campo in ("Status", "SubStatus"):
        basso = v.lower()
        if evento_id in (4768, 4771):
            return CODICI_KERBEROS.get(basso, v)
        if basso in ("0x0", "0"):
            return "riuscito"
        return regole.MOTIVI_FALLIMENTO.get(basso, v)
    if campo == "IpAddress":
        return regole._ip(v) or "—"
    if campo == "ElevatedToken":
        return VALORI_SI_NO.get(v, v)
    if campo == "ProcessName":
        return v.replace("/", "\\").split("\\")[-1] or v
    return v


def campi_leggibili(dati: dict) -> list[dict]:
    """I campi originali che hanno un'etichetta, tradotti, nell'ordine di :data:`CAMPI`."""
    interni = (dati or {}).get("dati") or {}
    eid = (dati or {}).get("id")
    out = []
    for campo, etichetta in CAMPI.items():
        v = interni.get(campo)
        if v in (None, "", "-"):
            continue
        out.append({"etichetta": etichetta, "valore": _valore(campo, str(v), eid), "tecnico": campo})
    return out


def frase(ev) -> str:
    """Il singolo evento in una frase: chi ha fatto cosa, da dove, su quale sistema."""
    chi = ev.account or "un account non indicato"
    sistema = (ev.host or ev.fonte_nome or "").split(".")[0]
    da = f" da {ev.ip_origine}" if ev.ip_origine else ""
    su = f" (registrato da {sistema})" if sistema else ""
    c = ev.categoria
    if c == "accesso":
        if (ev.tipo_accesso or "").startswith("Accesso al dominio"):
            return f"Accesso al dominio di {chi}{' dal PC ' + ev.ip_origine if ev.ip_origine else ''}{su}."
        return f"Accesso di {chi} a {sistema or 'un sistema'}{da}" + (f" ({ev.tipo_accesso.lower()})" if ev.tipo_accesso else "") + "."
    if c == "accesso_privilegiato":
        return f"Sessione con privilegi di amministratore aperta da {chi} su {sistema or 'un sistema'}."
    if c == "uscita":
        return f"Fine della sessione di {chi} su {sistema or 'un sistema'}."
    if c == "accesso_fallito":
        motivo = ev.descrizione.split(":", 1)[1].strip() if ":" in (ev.descrizione or "") else ""
        return f"Tentativo di accesso non riuscito per {chi}{da}{su}" + (f": {motivo}." if motivo else ".")
    if c == "account_bloccato":
        return f"L'account {chi} è stato bloccato dopo troppi tentativi sbagliati" + (f", arrivati da {ev.ip_origine}" if ev.ip_origine else "") + "."
    if c in ("account_creato", "account_eliminato", "account_modificato", "gruppo_privilegiato", "gruppo_modificato",
             "audit_modificato", "attivita_pianificata", "ora_modificata", "servizio_installato", "registro_cancellato",
             "registro_svuotato"):
        return f"{ev.descrizione} (su {sistema})." if sistema else f"{ev.descrizione}."
    if c == "avvio_arresto":
        return f"{sistema or 'Il sistema'}: {(ev.descrizione or '').lower()}."
    return ev.descrizione or ""
