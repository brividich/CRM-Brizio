# Proposta operativa: ruoli multipli, permessi e automazioni SGI

Data: 2026-09-29. Revisione 2, dopo il consenso al modello multiruolo. Proposta tecnica e organizzativa; nessuna assegnazione reale o automazione attivata.

## Evidenze e limiti

Share X: raggiungibile. Esaminati struttura e titoli del corpus corrente; estrazione locale e riscontro di termini di ruolo in Allegato C Rev.1 (organizzazione e ruoli), Allegato B Rev.2 (matrice responsabilita), MT CN 273 Rev.2 (mansioni sicurezza informazioni), MT CN 06 Rev.21 (risorse umane). Non costituisce lettura integrale o validazione delle responsabilita. Nessun nominativo, rapporto privato o contenuto integrale riprodotto. La presenza di una sigla non dimostra un potere di approvazione: descrizioni e responsabilita devono essere validate sulle sezioni pertinenti e sulle nomine vigenti.

## Modello proposto

Persona -> incarichi multipli, ciascuno con ambito, decorrenza, scadenza, perimetro, riferimento alla nomina e sostituto. Separare ruolo funzionale, permesso applicativo e perimetro dei dati. Ogni incarico deve avere codice stabile e denominazione ufficiale; non dedurre le espansioni di DM/IN1/MSM/MSO/MSA/RDD dalle sole sigle.

Il codice esistente offre AmbitoRuolo, RuoloOperativo, DipendenteRuoloOperativo, gerarchia e date. I ruoli operativi non sono primitive ACL. La ricognizione approfondita conferma anche AccessGroup, AccessGroupMembership e GroupPermissionGrant: il portale supporta gia appartenenze multiple a gruppi di accesso. Occorre collegare questi gruppi agli incarichi SGI senza duplicare il resolver ACL. I gruppi attuali non conservano perimetro, decorrenza, scadenza o provenienza dalla singola nomina.

Il resolver attuale applica: bypass superuser/admin legacy -> override utente -> gruppo con priorita piu alta (a parita vince il diniego) -> grant del ruolo legacy -> fallback legacy dove ammesso -> diniego. Non e una semplice unione indiscriminata. L'assenza di una riga di grant e neutra; enabled=False e un diniego esplicito.

## Matrice candidata da validare

| Profilo funzionale | Azioni candidate | Perimetro |
|---|---|---|
| Collaboratore | Consulta documenti assegnati, presa visione, segnalazioni | Propri documenti e pratiche |
| Responsabile processo/reparto | Assegna attivita, verifica avanzamento, valida evidenze | Processi/reparti assegnati |
| Qualita / coordinamento SGI | Prepara documenti, pianifica audit, gestisce NC/OFI e scadenze | Processi autorizzati; riservatezza separata |
| Direzione / approvatore designato | Approva gli atti di competenza e consulta KPI | Atti previsti dalle responsabilita formalizzate |
| Auditor | Consulta evidenze, esegue audit, registra rilievi | Audit assegnati; controlli di indipendenza |
| HR / formazione | Gestisce incarichi, fabbisogni, corsi e scadenze | Personale autorizzato |
| Sicurezza lavoro | Profili distinti per datore, RSPP, preposto, RLS, addetti | Azioni differenziate per incarico; nessun accesso sanitario generalizzato |
| Sicurezza informazioni / IT | Profili distinti per governance, gestione tecnica e approvazione | Sistemi e informazioni assegnati |
| Acquisti / logistica / produzione / collaudo / manutenzione | Esegue e valida passaggi di competenza | Commesse, reparti, forniture o asset assegnati |
| Parita di genere | Gestisce KPI e attivita; segnalazioni con accesso dedicato | Gruppo autorizzato, riservatezza specifica |
| Amministratore portale | Configura account e piattaforma | Privilegi tecnici; approvazioni di processo separate |

Sono profili proposti, non l'organigramma aziendale accertato. Qualifiche specialistiche e incarichi PART 145 vanno modellati separatamente dove necessari.

## Automazioni candidate, in ordine iniziale

1. Revisione documento: bozza -> approvazione del responsabile designato -> pubblicazione -> prese visione per ruolo e reparto -> solleciti -> escalation. Conservare revisione e destinatari storici.
2. NC/OFI: apertura -> responsabile del processo -> azione con scadenza -> sollecito -> verifica di efficacia indipendente -> chiusura autorizzata.
3. Ingresso o cambio incarico: proposta accessi, piano formazione, documenti e DPI pertinenti; attivazione dopo le verifiche richieste. Fine incarico: riesame/revoca degli accessi collegati e riassegnazione delle attivita aperte.
4. Qualifica in scadenza: avvisi configurabili, pianificazione rinnovo e controllo dell'idoneita all'assegnazione di attivita specialistiche.
5. Audit: proposta programma e auditor idonei, controllo conflitti, raccolta evidenze, approvazione umana e follow-up.
6. Specifica cliente: destinatari per ruolo/processo, compilazione e approvazione dei passaggi pertinenti, solleciti. Validare prima la corrispondenza delle sigle aziendali.

Ogni flusso richiede evento, responsabile, approvatore, scadenza, sostituto, escalation e traccia delle decisioni. Nessun destinatario valido: coda eccezioni al coordinatore autorizzato, senza invio generalizzato. Ripetere un evento non deve duplicare attivita o notifiche. Prima dell'esecuzione verificare account attivo, incarico valido, permessi e perimetro.

## Punto tecnico da correggere prima dell'attivazione

core/operational_roles.py filtra i ruoli attivi, ma get_roles_for_user e get_anagrafica_ids_for_role non filtrano data_inizio/data_fine delle assegnazioni; get_users_for_role non filtra is_active degli account. Questo servizio, da solo, non garantisce destinatari attualmente abilitati. Verificare anche i controlli dei singoli chiamanti. Nessuna correzione applicata in questa analisi.

## Passo successivo

Compilare la matrice ufficiale ruolo -> fonte/revisione/sezione -> azione -> perimetro -> approvatore -> sostituto, validarla con i responsabili e confrontarla con la configurazione effettiva del portale. Partire da revisione documenti, NC/OFI e cambio incarico con simulazione su dati sintetici. Stato e assegnazioni reali del database non verificati.

## Regole multiruolo concordate

1. Ogni persona puo ricoprire piu incarichi contemporaneamente, anche nello stesso ambito. Il ruolo principale e un dato organizzativo, non un limite alle autorizzazioni.
2. Il risultato e l'unione delle coppie **azione + perimetro** consentite dagli incarichi validi, soggetta ai dinieghi ACL e ai vincoli del processo. Non unire prima i permessi e poi tutti i reparti: si creerebbero autorizzazioni mai assegnate.
3. Il nuovo collegamento usa gruppi funzionali con soli grant positivi. Per permessi estranei al ruolo si lascia assenza di riga, senza generare dinieghi su tutto il catalogo: un diniego potrebbe cancellare un permesso legittimo di un altro incarico.
4. I dinieghi espliciti e gli override esistenti non vengono rimossi o reinterpretati. Prima di proporre un accesso, mostrare il risultato effettivo del resolver, compresa la regola vincente e gli eventuali conflitti. Priorita/override restano una scelta amministrativa tracciata.
5. Ogni azione deve superare anche i controlli su oggetto, stato, competenza e indipendenza. Avere sia compila sia approva non elimina il divieto di autoapprovazione dove previsto. Non affidare questi vincoli al solo menu o a un generico diniego di gruppo.
6. Perdere un incarico rimuove solo il suo contributo. Conservare accessi ottenuti da un altro incarico valido o da una concessione manuale distinta, e mantenere lo storico delle azioni svolte.
7. Notifiche e attivita equivalenti si deduplicano per persona e adempimento; due responsabilita con evidenze o firme diverse restano due adempimenti. Il registro conserva tutti i ruoli che hanno individuato il destinatario.
8. Nessuna scelta manuale del ruolo puo aumentare i diritti: l'eventuale selezione «agisco come...» sceglie solo fra incarichi validi e pertinenti, con verifica server al momento dell'azione.

### Esempio sintetico di cumulo corretto

| Incarico | Azione | Perimetro | Risultato |
|---|---|---|---|
| Responsabile reparto A | Consulta assenze | A | Vede richieste, storico e futuro di A |
| Preposto reparto B | Compila diario preposto | B | Compila per B, senza acquisire gestione assenze B |
| Auditor | Esegue audit | Audit assegnati | Accede alle evidenze pertinenti, con controllo indipendenza |
| Compilatore MOD.133 | Compila | Specifiche assegnate | Compila nel proprio perimetro |
| Approvatore MOD.133 | Approva | Specifiche assegnate | Approva soltanto se i vincoli del flusso lo consentono |

Se termina l'incarico da preposto B, restano quelli su A, sugli audit e sulle specifiche. Il titolo di responsabile A non si estende a B.

## Catalogo e fonti da associare

Questa tabella indica dove verificare la responsabilita, non dichiara che le nomine siano state validate. Conservare codice, revisione, sezione e data di verifica per ogni corrispondenza; usare le sigle ufficiali solo dopo averne verificato la definizione.

| Famiglia | Fonte SGI individuata | Verifica da completare |
|---|---|---|
| Ruoli trasversali / direzione / responsabili | IDOR 01 Allegato C Rev.1; IDOR CN 01 Allegato B Rev.2 | Denominazioni e poteri specifici di RDD, DM, IN1, MSM, MSO, MSA e altre sigle |
| HR, competenze, incarichi | MT CN 06 Rev.21; MOD.188 NIR Rev.0 | Nomina, validita, sostituzioni e requisiti di competenza |
| Qualifiche di processo | MOD.128 MPQ Rev.16 | Distinguere ruolo, qualifica e abilitazione a una macchina/processo |
| Sicurezza informazioni | MT CN 273 Rev.2; IDOR CN 02 ISMS Rev.2 | Governance, responsabili delle informazioni, gestione tecnica e approvazioni |
| Sicurezza lavoro | Cartella 45001; MOD.188; MT CN 451 Rev.2 | Perimetro di datore, RSPP, RLS, preposti e addetti; nessun profilo unico con tutti i poteri |
| Qualita / audit / azioni correttive | MT CN 12 Rev.1; MT CN 11 Rev.0; MT CN 08 Rev.3 | Chi pianifica, esegue, approva, verifica efficacia e pubblica |
| Parita di genere | Cartella 125; MT CN 125_10, 125_11, 125_13 | Destinatari autorizzati delle segnalazioni, comunicazioni e KPI |
| Incarichi specialistici | Cartella PART 145; MT CN 70 Rev.1 | Qualifiche, validita e responsabilita specifiche prima di attribuire poteri |

## Prima matrice applicativa da configurare in anteprima

I codici seguenti sono riscontrati nel codice della release; non attestano grant presenti nel database. I profili sono proposti e non vanno assegnati in massa dalla sola sigla aziendale.

| Profilo candidato | Permessi esistenti da associare | Ulteriore controllo necessario |
|---|---|---|
| Lettore audit | sistema_gestione.modulo.view; sistema_gestione.audit.view | Audit/documenti visibili nel perimetro |
| Pianificatore audit | Precedenti + sistema_gestione.audit.edit | Programmi e processi affidati |
| Auditor esecutore | Lettura + sistema_gestione.audit.esegui | Assegnazione al team, competenza, indipendenza e stato |
| Approvatore audit | Lettura + sistema_gestione.audit.approva | Autorita di approvazione e separazione delle responsabilita |
| Preparatore SoA | sistema_gestione.modulo.view; sistema_gestione.soa.view; sistema_gestione.soa.edit | Ambito SGSI e documenti riservati |
| Approvatore SoA | Accesso/lettura + sistema_gestione.soa.approva | Nomina e revisione sottoposta ad approvazione |
| Compilatore specifiche | gestione_specifiche.specifica.view; gestione_specifiche.specifica.claim; gestione_specifiche.mod133.compila | Task e specifiche assegnati |
| Approvatore specifiche | Lettura/presa in carico + gestione_specifiche.mod133.approva | Responsabilita della fase e regole MOD.133 |
| Gestore registro OFI | gestione_specifiche.specifica.view; gestione_specifiche.registroofi.add | Responsabilita e stato CAR; permesso add non equivale a chiusura libera |
| Lettore assenze reparto | legacy.assenze.view_reparto_assenze, insieme agli accessi pagina necessari | Relazione responsabile-dipendente; nessuna approvazione implicita |
| Lettore assenze aziendali | legacy.assenze.view_all_assenze, insieme agli accessi pagina necessari | Incarico HR/Direzione autorizzato, senza ampliamento dei dettagli riservati |

Questa matrice non e un seed pronto da applicare: prima occorre censire tutti i binding di pagina/API coinvolti e le eventuali verifiche legacy dentro le view. Per HR, DPI, sicurezza e documenti completare la mappatura con i cataloghi dei rispettivi moduli, senza inventare nuovi codici sinonimi.

## Dati aggiuntivi necessari

| Oggetto | Dati richiesti | Nota sull'esistente |
|---|---|---|
| Ruolo SGI | Codice stabile, nome ufficiale, ambito, fonte/revisione/sezione, responsabile della validazione | Il catalogo operativo esiste; nome oggi univoco, ambito e gerarchia gia presenti |
| Incarico | Persona, ruolo, perimetri tipizzati, dal/al, nomina, stato, sostituto/delega, origine | Date gia presenti; vincolo persona/ruolo attuale non consente piu periodi storici distinti per la stessa coppia |
| Collegamento autorizzativo | Incarico -> gruppo -> grant e perimetro, con proprieta del contributo | Membership attuale persona/gruppo non distingue contributi manuali e automatici |
| Decisione | Utente, azione/oggetto, incarico che giustifica l'azione, regola effettiva, data e motivazione | Riutilizzare audit esistente; registrare riferimenti, senza duplicare contenuti riservati |
| Delega | Delegante, delegato, azioni/perimetro, intervallo, motivo e revoca | Mai piu ampia della delega concessa, niente deleghe circolari |

Il collegamento automatico non deve cancellare una membership creata a mano o richiesta da un altro incarico. Serve una provenienza per ogni contributo e un calcolo dell'accesso residuo prima della revoca. La gerarchia «riporta a» non concede ereditarieta dei dati o dei poteri.

## Automazioni prioritarie: specifica operativa

| Flusso | Evento | Assegnazione e decisione umana | Termine/escalation | Evidenze e protezioni |
|---|---|---|---|---|
| Revisione documento | Revisione approvata e pubblicata | Destinatari per ruolo/perimetro; presa visione personale | Termine definito in campagna, sollecito al responsabile, poi coordinamento SGI | Congelare revisione e platea; nuova nomina valuta la revisione vigente; non segnare letture automaticamente |
| NC/OFI/CAR | Rilievo emesso | Responsabile processo propone azione; verificatore competente distinto valuta efficacia | Usare scadenze e proroghe del modulo CAR gia presente | Niente secondo registro o chiusura automatica; traccia delle transizioni |
| Cambio incarico | Nomina approvata con decorrenza | HR valida persona; responsabile valida perimetro; gestore accessi approva differenza dei permessi | Decorrenza effettiva e revoca alla fine; coda eccezioni se mancano dati | Simulazione prima/dopo, formazione/documenti/DPI pertinenti; non attivare accessi dalla sola importazione |
| Qualifica in scadenza | Soglia temporale configurata | HR/formazione e responsabile operativo pianificano rinnovo | Soglie concordate; escalation se non rinnovata | Distinguere qualifica scaduta da account disabilitato; bloccare solo attivita che richiedono quella qualifica |
| Audit | Programma/piano approvato | Team competente, assegnato e indipendente | Calendario e preavvisi del modulo audit | Usare i gate gia implementati, evidenze e firme umane |
| Specifica cliente | Nuova specifica/revisione | Compilatori e approvatori MOD.133 individuati per processo | Timer gia previsti nel workflow specifiche | Validare sigle aziendali; conservare fonte e assegnazione della fase |

Condizioni comuni: account attivo, incarico decorso e non scaduto, perimetro pertinente, permesso effettivo, competenza richiesta e assenza di conflitti. Ricontrollare le condizioni quando si esegue il job, non solo quando si crea la coda. Una persona senza account valido non viene sostituita da un indirizzo indovinato. Nessun candidato o piu responsabili dove ne serve uno: eccezione assegnata al coordinatore autorizzato, senza scegliere il primo della lista.

Una stessa combinazione evento/revisione/adempimento/persona produce un solo task; tentativi successivi sono idempotenti e tracciati. Una richiesta personale del caporeparto senza superiore configurato va in eccezione verso un responsabile nominato: non si autoapprova. Questo comportamento e proposto, non incluso nel fix Assenze.

## Sequenza di attuazione

1. **Inventario e matrice verificata**: fonti SGI, catalogo ruoli e gruppi esistenti, nomine e perimetri. Individuare duplicati, incarichi orfani, override e conflitti. Nessuna modifica dei grant.
2. **Validita e tracciabilita**: correggere filtro date/account nel servizio ruoli; aggiungere perimetri, riferimenti nomina e provenienza dei contributi con migrazioni conservative. Conservare assegnazioni storiche, non sovrascriverle.
3. **Simulatore multiruolo**: per persona, mostrare incarichi, permessi prima/dopo, fonte, perimetro, dinieghi e accessi che rimangono dopo una revoca. Esportare una proposta da verificare senza applicarla.
4. **Pilota controllato**: gruppi funzionali selezionati, nessun cambio di priorita automatico, verifiche server per oggetto. Disattivazione del solo collegamento automatico e ripristino dei contributi precedenti come ritorno alla situazione iniziale.
5. **Tre flussi iniziali**: documenti, NC/OFI e cambio incarico, riusando code/scheduler e moduli gia presenti. Prima simulazione, poi attivazione concordata e monitoraggio delle eccezioni.

### Criteri di accettazione

- Un incarico su A non estende a B il permesso ottenuto con un altro ruolo.
- Incarichi futuri/scaduti, ruoli disattivi e account disabilitati non generano accessi o destinatari automatici.
- La revoca di uno di due contributi identici conserva l'accesso residuo; una concessione manuale resta distinguibile.
- Il simulatore coincide con la decisione reale ACL, inclusi priorita, dinieghi e override; coprire anche menu, route/API ed export.
- Compilatore e approvatore sulla stessa persona non aggirano i vincoli di indipendenza.
- Due incarichi che individuano lo stesso adempimento non generano doppie notifiche; gli adempimenti distinti restano separati.
- Nessun responsabile, conflitto di responsabilita o delega scaduta produce un'eccezione esplicita e tracciata.
- Cambio incarico, revoca e job contemporanei non permettono l'esecuzione con autorizzazioni obsolete.

## Stato di questa sessione

Fix Assenze completato e pubblicato in release/prod con merge 5871b10a; 230 test verdi, deploy separato. Questa proposta definisce il passo successivo e non modifica ACL, gruppi, incarichi o automazioni reali. Restano da validare le corrispondenze puntuali delle fonti SGI e le nomine aziendali.
