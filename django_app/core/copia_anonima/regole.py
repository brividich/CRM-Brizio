"""Quali tabelle svuotare e cosa fare di ogni colonna di testo. Nessun accesso al database.

Regola di fondo: **una colonna non riconosciuta viene sostituita**. Una colonna nuova che nessuno
ha classificato perde il contenuto, non lo conserva.
"""
from __future__ import annotations

import re

SVUOTA = "svuota"
SEGRETO = "segreto"
EMAIL = "email"
UTENTE = "utente"
NOME = "nome"
COGNOME = "cognome"
PERSONA = "persona"
CONTATTO = "contatto"
BINARIO = "binario"
TIENI = "tieni"
TESTO = "testo"
UUID = "uuid"


def _rx(*parti: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in parti), re.IGNORECASE)


# Registri, code, sessioni, conversazioni: nessun collaudo funzionale ne ha bisogno.
TABELLE_DA_SVUOTARE = _rx(
    r"^django_(session|cache|admin_log|q_\w+)$", r"^axes_", r"^core_(auditlog|auditsigillo|pushiscrizione)$",
    r"^core_(dispositivoaccesso|pinpostazione|navigationsnapshot)$", r"^automation_event_queue$", r"^sync_audit$",
    r"^ai_assistant_(aichatfeedback|aiconversation|aiconversationmessage|aiproposta)$",
    r"^security_ai(conversation|conversationmessage|knowledgechunk|knowledgedocument|knowledgeembedding|memoryfact)$",
    r"^security_security(aiinteractionlog|letturalog|mailboxmessage|mailboxingestionrun|notificationlog)$",
    r"^security_security(externalfeedcache|sourcefile|eventrecord|configurationauditlog)$",
    r"^registro_log_(eventoregistro|sigillogiorno|indagine|statoraccoglitore)$",
    r"^anomalie_(anomalieemaillog|anomaliamailactiontoken|anomaliapendingnotification|anomaliaactionlog)$",
    r"^automazioni_(emailinviata|approvalmailboxmessage|automationapprovallink|automationactionlog)$",
    r"^automazioni_(automationrunlog|brokerrecoveryentry|clusterheartbeat|clusterwatchdogstate)$",
    r"^(monitoring_automationexecution|monitoring_issueoccurrence|monitoring_userproblemreport)$",
    r"^twofa_(twofactorchallenge|usertwofactor)$", r"^dati_bi_apiclient$", r"^assets_meteringestclient$",
    r"sharepointoutbox$", r"^dpi_linkconfermadpi$", r"^anagrafica_dipendenti_recovery_",
    r"^anagrafica_trainingexportlog$", r"^anagrafica_(candidatolog|trainingscanlog)$",
    r"^automazioni_automationapproval$",
)

# Cataloghi e configurazione: restano, salvo segreti e indirizzi mail.
TABELLE_DA_TENERE = _rx(
    r"^(auth_group|auth_permission|django_content_type|django_migrations|_portale_init)$",
    r"^(pulsanti|ruoli|permessi|ui_\w+)$",
    r"^core_(navigationitem|permissiondefinition|routepermissionbinding|rolepermissiongrant|grouppermissiongrant)$",
    r"^core_(modulecategory|hublink|hublinkcategory|legacyredirect|optioneconfig|ruolopermessomodulo)$",
    r"^core_(presetpermessimodulo|catalogo|catalogovoce|accessgroup|anagraficavoce|checklistvoce|employeeboardtemplate)$",
    r"^anagrafica_(area_aziendale|areaaziendale|centrodicosto|fattorerischio|tipovisitamedica|tipologiacontratto)$",
    r"^anagrafica_(livellocontrattuale|mansione|ruoloaziendale|ruolooperativo|tipoqualifica|categoriacorso)$",
    r"^anagrafica_(ambitoruolo|competenzacatalogo|voceretributiva|vocemacchinacatalogo|subnav\w+)$",
    r"^rentri_catalogoeer$", r"^glossario_tecnico_", r"^dpi_(tipodpi|categoriadpi|modellodpi|tagliadpi)$",
    r"^security_(securitycverecord|securitycverisoluzione|microsoft\w+|softwarealias|softwarecpemapping|softwarenarule)$",
    r"^assets_(assetcategory\w*|assetlist\w+|asset\w*layout|assetdetail\w+|assetheadertool|assetsidebarbutton)$",
    r"^assets_(assetactionbutton|assetdashboardconfig|failurecode|periodiccheck(category|type|system|layout|measurefield))$",
    r"^anomalie_(anomaliatipodifetto|anomalieroledefinition)$", r"^tasks_(taskcategory\w*|taskroledefinition)$",
    r"^tickets_categoriaticket$", r"^scadenzario_(categoriascadenza|voceconfig)$",
    r"^checklist_operativa_checklisttasktemplate$",
    r"^sistema_gestione_(controlloiso27002|checklist\w+|processo|processorevisione)$",
    r"(impostazioni|config|settings?)$",
)

# Oggetti senza persone: nomi e descrizioni restano utili alle prove.
TABELLE_OGGETTI = _rx(
    r"^assets_", r"^contatori_", r"^attrezzature_", r"^gestione_carichi_macchina_",
    r"^security_(softwareinstallation|watchguard\w+|defendervulnerabilita|securityvulnerabilityfinding|securitycveimpact)$",
)
COLONNE_OGGETTI = _rx(r"^(nome|name|descrizione|description|titolo|title|modello|model|hostname|host|ubicazione)$")

SEGRETI = _rx(
    r"pass(word|wd)", r"token", r"secret", r"segreto", r"_enc$", r"cifrat", r"session_data",
    r"api_?key", r"community", r"webhook", r"vault_ref", r"pin_hash", r"code_hash", r"ua_hash", r"session_hash",
    r"opcua_utente",
)
EMAILS = _rx(r"e?mail", r"^pec$", r"(^|_)upn$", r"^sender", r"^(to|cc|bcc)_", r"_emails?$")
UTENTI = _rx(r"^username", r"aliasusername", r"^sam$", r"^dn$", r"^account")
NOMI = _rx(r"^first_name$")
COGNOMI = _rx(r"^last_name$", r"^cognome$")
# Tabelle in cui `nome` e `matricola` indicano una persona.
TABELLE_PERSONE = _rx(
    r"^(utenti|dipendenti|capi_reparto|info_personali|auth_user)$", r"^anagrafica_dipendent", r"^anagrafica_candidato$",
    r"^anagrafica_figlioacarico$", r"^anagrafica_traininginstructor$", r"^fornitori_tecnicofornitore$",
    r"^timbri_operatoretimbri$", r"^sistema_gestione_(auditor|auditpersona)$",
)
PERSONE = _rx(
    r"nome_?(dipendente|esterno)$", r"nominativo", r"(^|_)display(_name)?$", r"_display", r"responsabil", r"capo",
    r"preposto", r"auditor", r"docente", r"teacher", r"tecnico", r"technician", r"richiedente", r"segnalante",
    r"destinatar", r"recipient", r"assegnat", r"assigned", r"assignment_to", r"assignee", r"incaricato", r"persona",
    r"persone", r"partecipanti", r"medico", r"owner", r"operator", r"proprietario", r"^chi(_|$)", r"autore", r"author",
    r"actor", r"(^|_)by(_|$)", r"_da(_nome)?$", r"(^|_)utente", r"^user_", r"_nome$", r"^inserito", r"^aggiornato",
    r"redatto", r"approvato", r"ragione_sociale", r"^cliente", r"^fornitore$", r"valutatore", r"valutato",
    r"presenti", r"^rubrica$", r"intestatario", r"patrono",
)
CONTATTI = _rx(
    r"telefono", r"cellulare", r"phone", r"^fax$", r"indirizzo(?!_ip|_mac)", r"residenza", r"domicilio", r"^cap(_|$)",
    r"^citta", r"luogo_nascita", r"provincia", r"nazionalita", r"cittadinanza", r"nazione", r"codice_fiscale", r"tax_code",
    r"partita_iva", r"^piva$", r"iban", r"nome_banca", r"badge", r"codice_timbro", r"codice_dip", r"genere",
    r"data_nascita", r"taglia", r"titolo_studio", r"certificato_medico", r"(^|_)ip(_|$)", r"remote_addr", r"user_agent",
    r"browser_info", r"^mac(_|$)", r"impronta", r"fingerprint",
)
TIPI_BINARI = ("varbinary", "binary", "image")

# Valori tecnici: enumerazioni, codici di sistema, impronte di file.
TECNICHE = _rx(
    r"^(stato|status|tipo|type|kind|categoria|category|severity|severita|gravita|esito|livello|level)($|_)",
    r"(_stato|_status|_type|_tipo|_kind|_mode|_format|_key|_code|_slug)$",
    r"^(priorita|priority|modalita|modo|mode|formato|format|fase|phase|colore|color|icona|icon|slug|sigla)($|_)",
    r"(_color|_colour)$", r"^(app_label|model_name|codename|permission_code|route_name|view_name|url_path|path_pattern)$",
    r"^(module|modulo|module_name|sezione|section|ui_slot|ui_section|action_type|event_type|source_kind|source_type)$",
    r"^(unit|unita|unit_label|unita_misura|mime|tipo_mime|content_type|lingua|periodo|mese|trimestre|frequenza)($|_)",
    r"^(periodicita|frequency|schedule_type|cron|func|hook|key|chiave|label|etichetta|environment|env)$",
    r"^(version|versione|revisione|revision|numero|ambito|scope|origine|fonte|source|canale|channel)($|_)",
    r"^(reparto|area|mansione|qualifica|ruolo|role|azienda|sede|gruppo|group)($|_(code|id|ids|type|nome|name|label)$)",
    r"^(codice|code|part_number|pn_|rev_|cve|kb|vendor|produttore|manufacturer|product|serial|seriale|numero_interno)",
    r"sha256", r"(^|_)hash", r"_ids$", r"^(field_type|tipo_campo|input_type|value_type|step_type|trigger_type)$",
)

# Date e importi che identificano una persona anche senza nome.
DATE_PERSONALI = _rx(r"data_nascita", r"^nascita", r"birth")
TABELLE_IMPORTI = _rx(
    r"^anagrafica_(costoorariomensile|importazioneretributiva|saldocedolino|storicocontratto|dipendenteanagraficaaziendale)$"
)


def adatta_al_campo(azione: str, tipo_campo: str | None) -> str:
    """Il valore finto deve restare leggibile dal campo Django, o la pagina va in errore."""
    if azione in (TIENI, BINARIO):
        return azione
    if tipo_campo == "UUIDField":
        return UUID
    if tipo_campo == "JSONField":
        return TESTO
    return azione


def classifica_tabella(tabella: str) -> str | None:
    return SVUOTA if TABELLE_DA_SVUOTARE.search(tabella) else None


def classifica(tabella: str, colonna: str, tipo_sql: str, con_scelte: bool = False) -> str:
    """Azione per una colonna. Prima cio' che non deve mai restare, poi cio' che puo' restare."""
    if tipo_sql.lower() in TIPI_BINARI:
        return BINARIO
    if SEGRETI.search(colonna):
        return SEGRETO
    if EMAILS.search(colonna):
        return EMAIL
    if con_scelte:
        return TIENI
    if TABELLE_DA_TENERE.search(tabella):
        # Anche nei cataloghi, un nome di persona o un dato di contatto non restano.
        return PERSONA if PERSONE.search(colonna) or CONTATTI.search(colonna) else TIENI
    if UTENTI.search(colonna):
        return UTENTE
    in_tabella_persone = bool(TABELLE_PERSONE.search(tabella))
    if NOMI.search(colonna) or (colonna.lower() == "nome" and in_tabella_persone):
        return NOME
    if COGNOMI.search(colonna):
        return COGNOME
    if colonna.lower() == "matricola" and in_tabella_persone:
        return CONTATTO
    if PERSONE.search(colonna):
        return PERSONA
    if CONTATTI.search(colonna):
        return CONTATTO
    if TECNICHE.search(colonna):
        return TIENI
    if TABELLE_OGGETTI.search(tabella) and COLONNE_OGGETTI.search(colonna):
        return TIENI
    return TESTO
