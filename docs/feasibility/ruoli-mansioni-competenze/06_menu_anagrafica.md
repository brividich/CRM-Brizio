# Menu di Anagrafica: studio di riordino

Versione 1.0 · 22/11/2026 · richiesto dal proprietario dopo l'arrivo della bozza della Qualità.

> È uno studio: nessun file del portale è stato modificato. Fonti: il menu reale catturato il 21/11/2026 da un utente
> amministratore (`prototipo/src/guscio/hrnav.html`), il codice del portale, la bozza della Qualità e i documenti in
> vigore. Sostituisce la tabella del menu a sei pilastri di `03_ux.md` (capitolo 10); restano validi i cinque modelli
> di pagina e le regole di interfaccia scritti lì.

## In breve

1. **Oggi:** 9 voci in barra e 53 in tutto; 20 stanno sotto «Competenze». Con le funzioni nuove salirebbero a circa 60.
2. **Proposta:** 6 pilastri e 3 voci di servizio, 34 voci in tutto. Un terzo in meno, con dentro le funzioni nuove.
3. **Tre idee.** Il menu segue la struttura della bozza: reparto, mansione, competenza. Le parole sono quelle del
   sistema di gestione. Si entra da «Oggi», che mostra a ciascuno ciò che lo aspetta.
4. **La forma resta quella di oggi**, a due righe: cambia il contenuto. Il menu laterale è scartato.
5. **Costo:** 5-10 giorni per il menu, 6-12 per gli accorpamenti di pagine. Gli indirizzi non cambiano.

---

## 1. Il menu di oggi

| Pilastro | Gruppi | Voci |
| --- | --- | --- |
| Dashboard | — | 1 |
| Scadenzario | — | 1 |
| Persone | Dipendenti (5), Ingressi (3) | 8 |
| Organizzazione | Struttura (5), Reparti e costi (2) | 7 |
| Competenze | Formazione (8), Qualifiche (6), Abilitazioni (6) | 20 |
| Salute e sicurezza | Panoramica (1), Sorveglianza sanitaria (5), Conformità (2), Rischi e mansioni (1) | 9 |
| Amministrazione | — | 3 |
| Report | — | 3 |
| Impostazioni | — | 1 |
| **Totale** | | **53** |

Il modulo ha 536 indirizzi (`anagrafica/urls.py`): il menu ne mostra uno su dieci, ed è giusto così. Il problema non è
quante pagine esistono, ma quante voci stanno alla pari.

**Che cosa non funziona.**

| Difetto | Misura |
| --- | --- |
| Pagine dello stesso tipo ripetute | 3 scadenzari, 4 cruscotti, 3 matrici, 2 coperture, 3 tipi di «sessione» |
| Un pilastro porta più di un terzo del menu | «Competenze»: 20 voci su 53 |
| La mansione sta in tre pilastri | Mansionario (Organizzazione); Mansioni di rischio, Cambi mansione, Conformità mansione (Sicurezza); Abilitazioni macchina (Competenze) |
| Le parole non sono quelle dei documenti | «Abilitazioni macchina» è la skill matrix; «Qualifiche» e «Processi qualificati» sono le abilitazioni |
| Voci che sono azioni, filtri o strumenti | Nuovo dipendente, Ex dipendenti, Chiedi un report, Validazione abbinamento macchine |
| Nessun ingresso per ruolo | «Il mio team» è la seconda voce di un gruppo; l'operatore non ha la sua scheda nel menu |
| «Macchina» nel nome | Uffici e direzione non hanno macchine: nella bozza sono 115 mansioni |

**Che cosa conservare.**

- Il menu è configurabile dal portale, senza sviluppo (`anagrafica/models.py:2676`, `:2713`).
- Le voci che l'utente non può aprire spariscono da sole (`anagrafica/subnav_gates.py`).
- La forma a due righe, con i numeri sui pilastri, è già provata anche sul telefono
  (`anagrafica/tests_subnav_due_livelli.py:94`).

## 2. Che cosa è cambiato dalla prima proposta

La prima proposta (sei pilastri, 42 voci) è del 21/11/2026. Da allora:

| Fatto nuovo | Effetto sul menu |
| --- | --- |
| La bozza della Qualità ordina tutto per reparto, mansione, competenza | Il pilastro «Organizzazione» diventa quel catalogo, a tre livelli |
| La bozza chiama «abilitazione» la competenza con scadenza | «Qualifiche» non è più un mondo a parte: è un filtro |
| «Responsabilità del reparto» è una mansione, una per reparto | Il capo reparto ha un ingresso suo: «Il mio reparto» |
| Anche il personale non operativo | Via «macchina» dai nomi |
| La skill matrix si firma ogni sei mesi | «Refresh semestrale» diventa «Emissione semestrale» |
| Nove indicatori per il riesame | Una voce «Indicatori» sotto Report |
| Materiali e pagine più semplici | Meno voci, non più pilastri |

## 3. Sei regole

1. **Il menu segue la struttura.** Reparto, mansione, competenza: nello stesso ordine in cui la Qualità li scrive.
2. **Una parola, una cosa.** Le parole sono quelle del sistema di gestione.
3. **Si entra da «Oggi».** La prima voce mostra a ciascuno ciò che lo aspetta.
4. **Nel menu solo luoghi.** Azioni e filtri stanno dentro le pagine.
5. **Al massimo sei voci per pilastro**, su due livelli.
6. **Una pagina per tipo.** Una matrice, uno scadenzario, una copertura; il cruscotto è l'ingresso del pilastro.

**Le parole.**

| Oggi nel menu | Proposta | Perché |
| --- | --- | --- |
| Abilitazioni macchina, Matrice competenze | Skill matrix | È il nome del MOD.187 e della procedura |
| Mansionario | Mansioni | Come nella bozza |
| Qualifiche, Processi qualificati | Abilitazioni (un tipo di competenza) | Come nella bozza |
| Sessioni (della formazione) | Edizioni | «Sessione» resta alla sessione formativa |
| Refresh semestrale | Emissione semestrale | La procedura parla di emissione firmata |
| Onboarding, Recruiting | Inserimenti, Selezione | Italiano, come il resto del portale |
| Conformità mansione | Idoneità alla mansione | «Conformità» nel progetto indica le competenze |
| Copertura / gap | Pianificazione | Dice a che cosa serve |

## 4. Il menu proposto

| Pilastro | Domanda | Voci | Da dove arrivano |
| --- | --- | --- | --- |
| **Oggi** | Che cosa aspetta me? | Da fare · Scadenze · Il mio reparto · La mia scheda | Dashboard, i tre scadenzari, Il mio team |
| **Persone** | Chi c'è? | Dipendenti · Selezione · Inserimenti · Uscite · Documenti | Persone |
| **Organizzazione** | Che cosa serve? | Organigramma · Reparti · Mansioni · Competenze · Cambiamenti | Organizzazione, Mansionario, Catalogo qualifiche, Processi qualificati |
| **Competenze** | Chi sa fare che cosa? | Skill matrix · Richieste di mansione · Sessioni formative · Emissione semestrale · Copertura | Abilitazioni, Qualifiche, Cambi mansione |
| **Formazione** | Come si impara? | Corsi · Edizioni · Pianificazione · Corsi online · Istruttori | Competenze › Formazione |
| **Sicurezza** | È idonea? | Visite mediche · Referti · Idoneità alla mansione · Rischi per mansione | Salute e sicurezza |
| Amministrazione | | Cedolini · Costo orario · Ferie e permessi | Invariata |
| Report | | Report · Indicatori | Report; «Indicatori» è nuova |
| Impostazioni | | Impostazioni | Invariata, con dentro gli strumenti di servizio |

In tutto 34 voci: 28 nei sei pilastri, 6 di servizio.

**Che cosa si accorpa.**

| Oggi | Nella proposta |
| --- | --- |
| Tre scadenzari | «Scadenze», con il filtro per tipo |
| Tre matrici | «Skill matrix», con tre viste: per mansione, per competenza, solo abilitazioni |
| Quattro cruscotti | L'ingresso di ogni pilastro |
| Due coperture | «Copertura», per reparto e per turno |
| Struttura organizzativa, Esplora la struttura, Organigramma | «Organigramma», tre viste |
| Recruiting, Posizioni aperte | «Selezione» |
| Piani formativi, Corsi | «Corsi», raggruppabili per piano |
| E-learning, Corsi online | «Corsi online» |
| Referti da rivedere, Registro referti | «Referti», con il filtro |
| Visite mediche, Sessioni di visita, Libretto sanitario | «Visite mediche»: calendario e libretto sono viste |
| Reparti, Centri di costo | «Reparti»: nella bozza ogni reparto ha un solo centro di costo |
| Cambi mansione, «Aggiungi mansioni» | «Richieste di mansione», con dentro il passo della visita |

**Che cosa esce dal menu.** «Nuovo dipendente» e «Chiedi un report» diventano pulsanti; «Ex dipendenti» un filtro;
«Validazione abbinamento macchine» va fra gli strumenti di Impostazioni.

## 5. Chi vede che cosa

Il filtro per permessi c'è già: la tabella dice che cosa si vuole ottenere, non una regola nuova.

| Chi | Da dove entra | Usa soprattutto |
| --- | --- | --- |
| Operatore | Oggi › La mia scheda | I suoi livelli, le scadenze, i corsi online |
| Capo reparto | Oggi › Il mio reparto | Skill matrix del reparto, richieste, conferma semestrale, copertura per turno |
| Qualità | Oggi › Da fare | Organizzazione (mansioni e competenze), sessioni formative, emissione |
| RDD | Oggi › Da fare | Firma dell'emissione, richieste da approvare, indicatori |
| Risorse umane | Persone | Inserimenti, uscite, formazione, amministrazione |
| Sicurezza | Sicurezza | Visite, referti, idoneità, rischi per mansione |

«Il mio reparto» è la pagina nuova più utile: la bozza dice chi è il responsabile di ogni reparto, e il portale può
mostrargli in una pagina persone, livelli, scadenze e richieste dei suoi.

## 6. La forma: tre alternative

| | A. Barra a due righe, riordinata | B. Menu laterale del modulo | C. Ingressi a schede e ricerca |
| --- | --- | --- | --- |
| Com'è | La forma di oggi, con il contenuto nuovo | Un albero fisso a sinistra | In barra solo i pilastri; ogni pilastro apre una pagina con schede e numeri; una ricerca unica |
| Pregi | Nessuna abitudine rotta; già provata sul telefono; costo minimo | Tutte le voci sempre visibili | Parla per domande; regge la crescita |
| Difetti | La seconda riga regge sei voci, non di più | Toglie larghezza alle matrici; chi tiene a lato il menu del portale ne avrebbe due | Un clic in più; la ricerca è da costruire |
| Costo | Basso | Alto | Medio |

**Raccomandazione: A, con le pagine d'ingresso di C.** La regola delle sei voci tiene la seconda riga leggibile. Le
pagine d'ingresso dei pilastri sono già previste come modello di pagina. La ricerca unica (persona, mansione,
competenza, corso) si può aggiungere dopo. B è scartata: la skill matrix ha già 79 colonne.

Resta fuori la barra del portale (moduli e preferiti): quel riordino è stato accantonato l'8/11/2026 e qui non si tocca.

## 7. Come arrivarci

| Passo | Contenuto | Giorni | Rischio |
| --- | --- | --- | --- |
| 1 | Riordino e nuovi nomi delle voci esistenti. È configurazione del menu, portata in produzione con un aggiornamento dei dati | 1-2 | Basso: gli indirizzi non cambiano |
| 2 | «Oggi»: una pagina che unisce Dashboard e Scadenzario, con le code per ruolo | 2-4 | Basso |
| 3 | Accorpamenti leggeri: una voce che apre le pagine di oggi come viste o filtri (Selezione, Organigramma, Referti, Corsi online, Report) | 2-4 | Basso |
| 4 | Accorpamenti veri: uno scadenzario, una matrice, una copertura | 6-12 | Medio: la matrice unica aspetta la regola unica dei livelli |
| 5 | Voci nuove (richieste, sessioni formative, emissione, indicatori, la mia scheda) | — | Arrivano con le tappe del progetto |
| 6 | Guide del portale: percorsi e nomi aggiornati | 1-2 | Basso |

I passi 1-3 valgono 5-10 giorni e si possono fare per primi, senza aspettare il resto. Sostituiscono la voce «menu
riordinato, 6-13 giorni» della stima.

## 8. Rischi e limiti

- **Abitudine.** Le voci cambiano posto e nome. Gli indirizzi restano, quindi i preferiti funzionano; per il primo mese
  conviene una nota «spostato in…» sulla pagina d'ingresso.
- **Vocabolario.** Unire qualifiche e abilitazioni sotto la skill matrix richiede l'accordo della Qualità.
- **Dati sanitari.** Libretto e referti cambiano posto nel menu, non i permessi: decide sempre il server.
- **Regole esistenti.** I ruoli restano in Impostazioni, come oggi. Vanno aggiornate le verifiche automatiche del
  menu (`anagrafica/tests_subnav_due_livelli.py`, dieci prove; una fissa il nome «Abilitazioni», riga 31).
- **Telefono.** Il pannello del telefono legge le voci dalla barra (`core/static/core/js/mobile-nav.js:92`): con meno
  voci migliora, ma va riprovato.
- **Non misurato.** Il menu è stato catturato da un amministratore: gli altri ruoli vedono meno voci, non so quante.
- **Prototipo.** Mostra ancora il menu a sei pilastri della prima proposta. Si allinea dopo l'approvazione di questo.

---

## Appendice: dove finisce ogni voce di oggi

| Oggi | Proposta |
| --- | --- |
| Dashboard | Oggi (ingresso) |
| Scadenzario | Oggi › Scadenze |
| Persone › Elenco dipendenti | Persone › Dipendenti |
| Persone › Il mio team | Oggi › Il mio reparto |
| Persone › Nuovo dipendente | Pulsante in Dipendenti |
| Persone › Ex dipendenti | Filtro in Dipendenti |
| Persone › Documenti | Persone › Documenti |
| Persone › Recruiting | Persone › Selezione |
| Persone › Posizioni aperte | Persone › Selezione (filtro) |
| Persone › Onboarding | Persone › Inserimenti |
| Organizzazione › Struttura organizzativa | Organizzazione › Organigramma (vista) |
| Organizzazione › Esplora la struttura | Organizzazione › Organigramma (vista) |
| Organizzazione › Organigramma | Organizzazione › Organigramma |
| Organizzazione › Prospetto dei cambiamenti | Organizzazione › Cambiamenti |
| Organizzazione › Mansionario | Organizzazione › Mansioni e Competenze |
| Organizzazione › Reparti | Organizzazione › Reparti |
| Organizzazione › Centri di costo | Organizzazione › Reparti (colonna e filtro) |
| Formazione › Dashboard | Formazione (ingresso) |
| Formazione › Piani formativi | Formazione › Corsi (raggruppamento) |
| Formazione › Corsi | Formazione › Corsi |
| Formazione › Sessioni | Formazione › Edizioni |
| Formazione › Istruttori | Formazione › Istruttori |
| Formazione › E-learning | Formazione › Corsi online |
| Formazione › Corsi online | Formazione › Corsi online |
| Formazione › Copertura / gap | Formazione › Pianificazione |
| Qualifiche › Cruscotto | Competenze (ingresso, filtro abilitazioni) |
| Qualifiche › Catalogo qualifiche | Organizzazione › Competenze (tipo abilitazione) |
| Qualifiche › Processi qualificati | Organizzazione › Competenze (tipo abilitazione) |
| Qualifiche › Matrice processi qualificati | Competenze › Skill matrix (vista abilitazioni) |
| Qualifiche › Sessioni di rinnovo | Competenze › Sessioni formative (tipo rinnovo) |
| Qualifiche › Scadenzario qualifiche | Oggi › Scadenze (filtro) |
| Abilitazioni › Matrice competenze | Competenze › Skill matrix (vista per competenza) |
| Abilitazioni › Abilitazioni macchina | Competenze › Skill matrix (vista per mansione) |
| Abilitazioni › Validazione abbinamento macchine | Impostazioni (strumenti) |
| Abilitazioni › Scadenzario abilitazioni | Oggi › Scadenze (filtro) |
| Abilitazioni › Refresh semestrale | Competenze › Emissione semestrale |
| Abilitazioni › Copertura abilitazioni | Competenze › Copertura |
| Sicurezza › Cruscotto sicurezza | Sicurezza (ingresso) |
| Sicurezza › Visite mediche | Sicurezza › Visite mediche |
| Sicurezza › Sessioni di visita | Sicurezza › Visite mediche (calendario) |
| Sicurezza › Referti da rivedere | Sicurezza › Referti (filtro) |
| Sicurezza › Registro referti | Sicurezza › Referti |
| Sicurezza › Libretto sanitario | Sicurezza › Visite mediche (scheda della persona) |
| Sicurezza › Conformità mansione | Sicurezza › Idoneità alla mansione |
| Sicurezza › Cambi mansione | Competenze › Richieste di mansione |
| Sicurezza › Mansioni di rischio | Sicurezza › Rischi per mansione |
| Amministrazione › Cedolini | Invariata |
| Amministrazione › Costo orario | Invariata |
| Amministrazione › Ferie e permessi | Invariata |
| Report › Reportistica | Report › Report |
| Report › Chiedi un report | Pulsante in Report |
| Report › Report dipendenti | Report › Report (predefinito) |
| Impostazioni | Invariata |
