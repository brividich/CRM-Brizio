# Registro delle attività di trattamento — NOVICROM HUB (bozza)

Bozza del registro del titolare (art. 30.1 GDPR) per i trattamenti svolti **con il portale NOVICROM HUB**. È ricavata dal codice e dalle integrazioni reali del portale al 21/10/2026 (checklist GDPR, punto F1). Non copre i trattamenti fuori dal portale (gestionale paghe, posta, cartelle di rete, videosorveglianza, sito web).

**Stato: bozza da validare.** Le basi giuridiche, i destinatari e i termini sono proposte: vanno confermati dal titolare con il DPO o il consulente privacy. Le voci «da confermare» sono informazioni che il codice non può sapere.

| Campo | Valore |
| --- | --- |
| Titolare | Costruzioni Novicrom S.r.l. — sede, P.IVA e contatti: *da compilare* |
| Rappresentante legale | *da compilare* |
| DPO / referente privacy | *da compilare* (nome e contatto) |
| Data della bozza | 21/10/2026 |
| Documenti collegati | [Retention dei dati personali](../audit/RETENTION_DATI_PERSONALI.md) · [Valutazione d'impatto preliminare](DPIA_PRELIMINARE.md) · [Responsabili esterni](RESPONSABILI_ART28.md) · [Politica audit](../dr/AUDIT_POLICY.md) |

## Misure di sicurezza comuni (art. 32)

Valgono per tutti i trattamenti sotto; ogni scheda riporta solo le misure in più.

- **Accesso**: login con account aziendale (Active Directory) o account del portale; permessi per pagina e per azione (ACL v2) secondo il ruolo; verifica in due passaggi per i ruoli scelti, sempre da Internet e dalla rete interna sui dispositivi nuovi; blocco dopo tentativi falliti; sessione che scade per inattività.
- **Tracciabilità**: registro attività (audit) di modifiche, esportazioni e consultazione delle schede più delicate, sigillato ogni mese; per i dati sensibili il registro tiene solo i nomi dei campi cambiati, non i valori.
- **Riservatezza dei file**: allegati personali fuori dalla cartella web, cifrati (Fernet), scaricabili solo dopo il login e il controllo dei permessi.
- **Cifratura nel database** di IBAN, prescrizioni e note delle visite, giudizio letto dai referti e firma delle consegne DPI.
- **Log**: codici fiscali e IBAN mascherati in tutti i log applicativi.
- **Rete**: portale solo in rete interna; da Internet è pubblicato solo il collegamento di approvazione (Entra Application Proxy).
- **Continuità**: backup verificati con prove di ripristino. I backup del database **non sono ancora cifrati** (SQL Server Express): decisione aperta, vedi Retention.
- **Conservazione**: pulizia automatica notturna per gli archivi tecnici; per i dati di dipendenti e candidati conteggio settimanale e conferma di un amministratore.

## Trattamenti

### T01 — Gestione del rapporto di lavoro

| Campo | Contenuto |
| --- | --- |
| Finalità | Anagrafica del personale, organigramma, ruoli e mansioni, reparto, contratto e storico organizzativo, documenti del dipendente |
| Base giuridica | Art. 6.1.b (contratto di lavoro), 6.1.c (obblighi di legge: lavoro, fisco, previdenza). Dati dei familiari a carico: 6.1.c |
| Interessati | Dipendenti, ex dipendenti, familiari a carico, collaboratori con account |
| Categorie di dati | Identificativi, codice fiscale, dati di nascita e residenza, recapiti, IBAN, foto, figli a carico, taglie, telefono aziendale, contratto, ruolo e mansione, documenti (contratti, attestati, referti — questi ultimi vedi T04) |
| Destinatari | HR e amministrazione; responsabili per il proprio personale (permessi del portale); consulente del lavoro / studio paghe *da confermare* |
| Trasferimenti extra UE | Nessuno dal portale |
| Termine | 10 anni dalla cessazione, poi minimizzazione (restano nome, rapporto, formazione, DPI, storia delle visite) — *proposta* |
| Moduli | `anagrafica` (tabella legacy `anagrafica_dipendenti`, `DipendenteAnagraficaCivile`, `FiglioACarico`, documenti) |
| Diritti | «La mia scheda»: «Scarica i miei dati» (art. 15/20) e «Segnala un dato da correggere» (art. 16), risposta HR entro 30 giorni |

### T02 — Retribuzioni, cedolini e saldi

| Campo | Contenuto |
| --- | --- |
| Finalità | Consultazione delle voci retributive, dei ratei e dei saldi ferie/permessi importati dai cedolini |
| Base giuridica | Art. 6.1.b, 6.1.c |
| Interessati | Dipendenti |
| Categorie di dati | Voci del cedolino, importi, saldi, mese di competenza |
| Destinatari | HR e amministrazione; il dipendente per i propri dati |
| Trasferimenti extra UE | Cedolini letti da una cartella SharePoint (Microsoft 365, vedi Responsabili) |
| Termine | 10 anni dalla cessazione, poi cancellazione di voci e saldi — *proposta* |
| Moduli | `anagrafica` (`ImportazioneRetributiva`, `VoceRetributiva`, `ImportazioneCedolini`, `SaldoCedolino`) |
| Misure in più | Consultazione di ratei e retribuzioni registrata nell'audit |

### T03 — Presenze e assenze

| Campo | Contenuto |
| --- | --- |
| Finalità | Richiesta e approvazione di ferie, permessi e altre assenze; calendario; certificazioni di presenza |
| Base giuridica | Art. 6.1.b, 6.1.c. Assenze per malattia o infortunio: art. 9.2.b (dati relativi alla salute, solo il tipo di assenza e i riferimenti del certificato) |
| Interessati | Dipendenti |
| Categorie di dati | Date, tipo e motivazione dell'assenza, approvatore, certificazioni |
| Destinatari | Responsabile diretto, HR, amministrazione. Approvazioni anche via mail, Teams e Power Automate |
| Trasferimenti extra UE | Lista SharePoint delle assenze e flussi Teams/Power Automate (Microsoft 365) |
| Termine | 5 anni — *proposta, non ancora applicata* (tabelle legacy) |
| Moduli | `assenze`, `automazioni` |
| Note | La mail di cancellazione di un'assenza riporta la motivazione e può arrivare all'indirizzo personale del dipendente (checklist G9: lasciata così per scelta) |

### T04 — Sorveglianza sanitaria

| Campo | Contenuto |
| --- | --- |
| Finalità | Programmazione delle visite, scadenze, giudizio di idoneità alla mansione, prescrizioni e limitazioni, acquisizione dei referti dal medico competente |
| Base giuridica | Art. 6.1.c e 9.2.b (D.Lgs. 81/08 art. 18, 41), 9.2.h per quanto trattato dal medico competente |
| Interessati | Dipendenti |
| Categorie di dati | **Dati relativi alla salute**: giudizio di idoneità, prescrizioni e limitazioni, note, referti; date e tipo di visita |
| Destinatari | HR / addetto alla sorveglianza sanitaria; medico competente; il dipendente |
| Trasferimenti extra UE | Nessuno dal portale. La lettura dei referti (OCR Tesseract) avviene sul server |
| Termine | *da definire con il medico competente*. La cartella sanitaria resta al medico competente |
| Moduli | `anagrafica` (`VisitaMedica`, `RequisitoVisitaDipendente`, `RefertoIntakeRiga`, `DerogaOperativaVisita`) |
| Misure in più | Prescrizioni, note e giudizio letto dal referto cifrati nel database; nell'export «I miei dati» le prescrizioni e le note non escono; DPIA richiesta (vedi DPIA preliminare) |
| Note | Al datore di lavoro serve il **giudizio**, non la diagnosi: verificare che i referti caricati contengano solo il giudizio di idoneità |

### T05 — Formazione e addestramento

| Campo | Contenuto |
| --- | --- |
| Finalità | Corsi obbligatori e professionali, attestati, e-learning, skill matrix, abilitazioni (EN 9100, PART 145) |
| Base giuridica | Art. 6.1.c (D.Lgs. 81/08 art. 37), 6.1.b |
| Interessati | Dipendenti |
| Categorie di dati | Corsi, date, esiti, attestati, competenze |
| Destinatari | HR, responsabili, enti di formazione *da confermare*, organismi di certificazione in audit |
| Trasferimenti extra UE | Nessuno |
| Termine | Durata del rapporto più 10 anni (resta anche dopo la minimizzazione dei cessati) — *proposta* |
| Moduli | `anagrafica` (formazione, skill matrix), `procedure_refresh` |

### T06 — Dispositivi di protezione individuale

| Campo | Contenuto |
| --- | --- |
| Finalità | Richiesta, consegna e firma per ricevuta dei DPI, magazzino, scadenze |
| Base giuridica | Art. 6.1.c (D.Lgs. 81/08 art. 77) |
| Interessati | Dipendenti |
| Categorie di dati | DPI consegnati, taglie, date, immagine della firma |
| Destinatari | Ufficio sicurezza, magazzino; Power BI (vista `bi_dpi_consegne`) |
| Trasferimenti extra UE | Power BI (Microsoft) se il report è pubblicato nel servizio cloud |
| Termine | Durata del rapporto più 10 anni — *proposta* |
| Moduli | `dpi`, `dati_bi` |
| Misure in più | Firma cifrata nel database |

### T07 — Sicurezza sul lavoro: incidenti, near miss, ispezioni

| Campo | Contenuto |
| --- | --- |
| Finalità | Registrazione di incidenti, infortuni, near miss e situazioni pericolose; diario del preposto; azioni correttive |
| Base giuridica | Art. 6.1.c (D.Lgs. 81/08); dati sanitari di un infortunio: 9.2.b |
| Interessati | Dipendenti, eventuali terzi presenti |
| Categorie di dati | Persone coinvolte, descrizione dell'evento, eventuali lesioni |
| Destinatari | RSPP, preposti, direzione |
| Trasferimenti extra UE | Lista SharePoint delle rilevazioni (Microsoft 365) |
| Termine | *da definire* (allegati compresi) |
| Moduli | `rilevazione_incidenti`, `diario_preposto`, `anomalie` |

### T08 — Selezione del personale

| Campo | Contenuto |
| --- | --- |
| Finalità | Gestione delle candidature: CV, colloqui, punteggi, esito |
| Base giuridica | Art. 6.1.b (misure precontrattuali su richiesta del candidato) |
| Interessati | Candidati |
| Categorie di dati | Anagrafica e recapiti, CV, competenze, valutazioni dei colloqui |
| Destinatari | HR, responsabili che partecipano ai colloqui |
| Trasferimenti extra UE | Nessuno dal portale |
| Termine | 24 mesi dall'ultima modifica per i candidati chiusi o «in database», poi anonimizzazione — *proposta*. Gli assunti passano a T01 |
| Moduli | `anagrafica` (recruiting: `Candidato`, `CandidatoPunteggio`, `CandidatoLog`) |
| Note | Serve un'informativa per i candidati al momento della raccolta del CV *da verificare* |

### T09 — Registro timbri, firme e sigle

| Campo | Contenuto |
| --- | --- |
| Finalità | Tracciabilità delle lavorazioni e dei rilasci (qualità EN 9100, PART 145): chi può firmare o timbrare cosa |
| Base giuridica | Art. 6.1.c (requisiti aeronautici), 6.1.f (tracciabilità della qualità) |
| Interessati | Dipendenti abilitati |
| Categorie di dati | Nome, sigla, immagine di firma e timbro, abilitazioni |
| Destinatari | Qualità, produzione, organismi di certificazione e clienti in audit |
| Trasferimenti extra UE | Nessuno |
| Termine | *da decidere* (legato alla conservazione della documentazione di prodotto) |
| Moduli | `timbri` |
| Misure in più | Immagini nell'archivio privato, nomi dei file senza dati personali |

### T10 — Account, accessi e sicurezza informatica del portale

| Campo | Contenuto |
| --- | --- |
| Finalità | Autenticazione, permessi, verifica in due passaggi, riconoscimento dei dispositivi, prevenzione degli accessi abusivi, audit delle operazioni, diagnosi degli errori |
| Base giuridica | Art. 6.1.c (art. 32 GDPR) e 6.1.f (sicurezza dei sistemi) |
| Interessati | Utenti del portale |
| Categorie di dati | Username, email, IP, browser e dispositivo, orari di accesso, tentativi falliti, operazioni svolte, segnalazioni e occorrenze di errore |
| Destinatari | Amministratori del portale |
| Trasferimenti extra UE | Nessuno dal portale; audit sigillato esportato ogni mese su SharePoint |
| Termine | Tentativi di accesso 90 giorni, occorrenze errori 90 giorni, sessioni alla scadenza, audit 60 mesi online + 120 mesi in archivio (vedi Retention) |
| Moduli | `core`, `twofa`, `monitoring`, `admin_portale` |
| Note | Strumenti di lavoro ai sensi dell'art. 4 c. 2 L. 300/1970; i dati raccolti sono utilizzabili solo se i lavoratori ne hanno adeguata informazione (art. 4 c. 3): serve l'informativa ai dipendenti |

### T11 — Security Center (SOC)

| Campo | Contenuto |
| --- | --- |
| Finalità | Rilevazione e gestione di eventi e incidenti di sicurezza informatica (NIS2, D.Lgs. 138/2024), vulnerabilità, inventario dei PC e del software, stato dei backup |
| Base giuridica | Art. 6.1.c (obblighi di sicurezza e notifica), 6.1.f |
| Interessati | Dipendenti e utenti dei PC aziendali, mittenti di mail di report |
| Categorie di dati | Account Microsoft 365 ed Entra (anche ex dipendenti), dispositivi Intune, alert di Defender con utente e PC, mail dei report di sicurezza, software installato |
| Destinatari | Personale IT / SOC |
| Trasferimenti extra UE | Dati letti da Microsoft Graph, Defender, Intune ed Entra (Microsoft) |
| Termine | Mail del SOC: dopo 12 mesi mittente e contenuto svuotati; chat e log AI del SOC 12 mesi |
| Moduli | `security` |
| Note | Come T10 per l'art. 4 L. 300/1970. Controllo sistematico dei dispositivi dei lavoratori: DPIA consigliata |

### T12 — Assistente AI

| Campo | Contenuto |
| --- | --- |
| Finalità | Risposte alle domande degli utenti su procedure, guide e dati del portale a cui l'utente ha già accesso |
| Base giuridica | Art. 6.1.f (supporto operativo) |
| Interessati | Utenti che lo usano; persone citate nelle domande o nei documenti |
| Categorie di dati | Domande e risposte, feedback, chiamate agli strumenti con i loro parametri |
| Destinatari | Nessuno fuori dal portale: il modello gira su un server interno (Ollama) |
| Trasferimenti extra UE | Nessuno |
| Termine | Conversazioni e feedback 90 giorni; registro degli strumenti secondo la revisione privacy di ogni strumento *da verificare* |
| Moduli | `ai_assistant`, `security` (copilota SOC) |
| Note | DPIA consigliata (uso innovativo di tecnologia); gli strumenti dell'assistente rispettano i permessi dell'utente |

### T13 — Automazioni e approvazioni

| Campo | Contenuto |
| --- | --- |
| Finalità | Notifiche e approvazioni automatiche dei flussi (assenze, ticket, anomalie, DPI) via mail, Teams e link di approvazione |
| Base giuridica | Come il trattamento di origine (T03, T06…) |
| Interessati | Dipendenti richiedenti e approvatori |
| Categorie di dati | Dati del record che fa partire la regola, email del destinatario, esito |
| Destinatari | Approvatori; servizi Microsoft (Power Automate, Teams, Outlook) |
| Trasferimenti extra UE | Microsoft 365. Le chiamate HTTP delle regole vanno solo a servizi Microsoft o a host approvati in configurazione |
| Termine | Run log ed eventi 90 giorni; link e mail di approvazione 6 mesi dopo la decisione |
| Moduli | `automazioni` |

### T14 — Comunicazioni interne, prese visione, notifiche

| Campo | Contenuto |
| --- | --- |
| Finalità | Notizie aziendali, presa visione di procedure e schede di sicurezza, notifiche in-app, mail e push |
| Base giuridica | Art. 6.1.c (informazione dei lavoratori, D.Lgs. 81/08 art. 36), 6.1.b |
| Interessati | Dipendenti |
| Categorie di dati | Letture e prese visione con data, preferenze di notifica, iscrizioni push del browser |
| Destinatari | HR, qualità, sicurezza; servizi push del produttore del browser (solo il segnale, contenuto cifrato) |
| Trasferimenti extra UE | Servizi push dei browser (Google, Mozilla, Apple, Microsoft) — *da valutare* |
| Termine | Prese visione: come la documentazione del sistema di gestione; notifiche: archiviazione automatica |
| Moduli | `notizie`, `procedure_refresh`, `schede_sicurezza`, `core` (notifiche) |

### T15 — Clienti, fornitori e commesse

| Campo | Contenuto |
| --- | --- |
| Finalità | Commesse KICK-OFF, incontri con i clienti, specifiche cliente, fornitori, ticket |
| Base giuridica | Art. 6.1.b, 6.1.f (contatti professionali) |
| Interessati | Referenti di clienti e fornitori |
| Categorie di dati | Nome, ruolo, email e telefono professionali, partecipazione agli incontri |
| Destinatari | Personale coinvolto nella commessa; calendario Outlook |
| Trasferimenti extra UE | Inviti e calendario Outlook (Microsoft 365) |
| Termine | *da definire* (durata del rapporto commerciale + termini civilistici) |
| Moduli | `tasks`, `gestione_specifiche`, `anagrafica` (fornitori), `tickets` |

## Cosa manca per chiudere il registro

1. Dati del titolare e del DPO o referente.
2. Conferma delle basi giuridiche e dei termini *proposta* (sezione D della checklist).
3. Termini ancora aperti: T03 assenze, T04 visite, T07 incidenti, T09 timbri, T15 clienti, allegati di ticket e task.
4. Destinatari esterni da confermare: consulente del lavoro, enti di formazione, medico competente (vedi Responsabili).
5. Informative: dipendenti (anche per l'art. 4 L. 300/1970), candidati.
6. Aggiornare il registro quando un modulo nuovo tratta dati personali: stessa regola di [Retention](../audit/RETENTION_DATI_PERSONALI.md).
