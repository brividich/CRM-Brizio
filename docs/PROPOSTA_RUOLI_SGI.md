# Proposta preliminare ruoli, permessi e automazioni SGI

Data: 2026-09-29. Analisi, non configurazione applicata.

## Evidenze e limiti

Share X: raggiungibile. Esaminati struttura e titoli del corpus corrente; estrazione locale e riscontro di termini di ruolo in Allegato C Rev.1 (organizzazione e ruoli), Allegato B Rev.2 (matrice responsabilita), MT CN 273 Rev.2 (mansioni sicurezza informazioni), MT CN 06 Rev.21 (risorse umane). Non costituisce lettura integrale o validazione delle responsabilita. Nessun nominativo, rapporto privato o contenuto integrale riprodotto. La presenza di una sigla non dimostra un potere di approvazione: descrizioni e responsabilita devono essere validate sulle sezioni pertinenti e sulle nomine vigenti.

## Modello proposto

Persona -> incarichi multipli, ciascuno con ambito, decorrenza, scadenza, perimetro, riferimento alla nomina e sostituto. Separare ruolo funzionale, permesso applicativo e perimetro dei dati. Ogni incarico deve avere codice stabile e denominazione ufficiale; non dedurre le espansioni di DM/IN1/MSM/MSO/MSA/RDD dalle sole sigle.

Il codice esistente offre AmbitoRuolo, RuoloOperativo, DipendenteRuoloOperativo, gerarchia e date. I ruoli operativi non sono primitive ACL; i grant canonici dipendono dai ruoli legacy. Non presumere che piu incarichi producano gia un'unione dei permessi. Occorre progettare una mappatura esplicita preservando ACL v2, controlli server e restrizioni sui singoli oggetti.

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
