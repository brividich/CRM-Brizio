<!-- Fonte: Specifica_Funzionale_Piattaforma_Formazione_Skill_Matrix_v2.docx · convertito il 21/11/2026 -->

SPECIFICA FUNZIONALE v2

**Piattaforma Formazione • Competenze • Skill Matrix**

Modello aggiornato: separazione fra Sessione Formativa e Richiesta di Aggiornamento Mansione

|  |
| --- |
| **PRINCIPIO ARCHITETTURALE  <br>La competenza descrive ciò che la persona sa fare. La mansione descrive ciò che la persona è formalmente autorizzata a svolgere. La Sessione Formativa modifica e documenta le competenze; la Richiesta di Aggiornamento Mansione modifica le autorizzazioni operative.** |

# 1\. Oggetti principali e nomenclatura

|  |  |  |
| --- | --- | --- |
| **Oggetto** | **Funzione** | **Progressivo** |
| Catalogo Competenze | Elenco standard delle competenze valutabili | ID stabile |
| Catalogo Corsi | Modelli didattici standard riutilizzabili; ogni corso indica quali competenze può alimentare | ID corso stabile, es. CRS-014 |
| Sessione Formativa | Evento che registra incremento/conferma di competenze, modalità P/A/C, evidenze e valutatori | SF-AAAA-NNNN |
| Richiesta Aggiornamento Mansione | Evento autorizzativo per aggiungere una mansione alla persona | RAM-AAAA-NNNN |
| Skill Matrix | Stato corrente delle mansioni assegnate e dei relativi livelli | Vista corrente |
| MOD.053 dinamico | Output sempre aggiornato dello storico professionale/formativo della persona | Report dinamico, non evento |
| MOD.040 | Registro operativo allegato agli eventi A – Affiancamento | Allegato alla SF |

# 2\. Relazioni fondamentali

-   Una Sessione Formativa può alimentare più competenze e più persone.
-   Un corso di catalogo può alimentare più competenze ed essere richiamato da molte Sessioni Formative.
-   Una Richiesta Aggiornamento Mansione può collegarsi a 0..N Sessioni Formative.
-   Una Sessione Formativa può esistere senza una Richiesta Aggiornamento Mansione, ad esempio per aggiornamento normativo o crescita professionale.
-   Una Richiesta Aggiornamento Mansione può chiudersi senza nuova Sessione Formativa quando tutte le competenze richieste sono già formalmente possedute.

|  |
| --- |
| **REGOLA DECISIVA  <br>Non creare una nuova Sessione Formativa solo per chiudere una Richiesta di Aggiornamento Mansione. Le evidenze già presenti nel profilo vengono riutilizzate.** |

# 3\. Flusso A – Sessione Formativa

|  |
| --- |
| **FABBISOGNO  <br>Inserimento • Gap competenza • Aggiornamento • Esperienza da formalizzare • Corso** |

**↓**

|  |
| --- |
| **APERTURA SESSIONE FORMATIVA SF-AAAA-NNNN  <br>Persone • competenze interessate • causale • responsabile/tutor** |

**↓**

|  |
| --- |
| **REGISTRAZIONE EVIDENZE  <br>P = esperienza verificata • A = affiancamento documentato • C = corso di catalogo/sessione** |

**↓**

|  |
| --- |
| **VALUTAZIONE  <br>Livello raggiunto per ogni competenza • data • valutatore • allegati** |

**↓**

|  |
| --- |
| **CHIUSURA SESSIONE  <br>Profilo competenze aggiornato • storico conservato • ricalcolo delle mansioni potenzialmente soddisfatte** |

# 4\. P/A/C: modalità, non livelli

|  |  |  |
| --- | --- | --- |
| **Modalità** | **Registrazione minima** | **Evidenza tipica** |
| P – Esperienza | Breve descrizione standardizzata; verifica; data; valutatore; livello | Esperienza precedente/interna, osservazione, prova pratica, colloquio tecnico, equivalenza |
| A – Affiancamento | Tutor; periodo; ore; attività; livello finale | MOD.040 o registro digitale allegato |
| C – Corso | ID corso; sessione/data; docente/ente; partecipanti; esito; livello | Materiale didattico, test, attestato se previsto |

-   P/A/C sono eventi storicizzati e possono coesistere sulla stessa competenza.
-   Il livello corrente deriva dall’ultima valutazione valida, non dalla “forza” della modalità.

# 5\. Catalogo Corsi e Sessione Corso

-   Se il corso non esiste, viene creato una sola volta nel Catalogo Corsi con un ID stabile.
-   Il catalogo definisce titolo, programma, materiale, competenze alimentabili, durata indicativa, valutazione e periodicità.
-   Ogni erogazione concreta è una Sessione Formativa distinta con data, docente, partecipanti ed esito.

## Esempio – nuovo corso non ancora a catalogo

|  |  |
| --- | --- |
| **Passaggio** | **Registrazione** |
| 1 | Creazione CRS-027 – Fondamenti di metrologia di reparto |
| 2 | Associazione CRS-027 alle competenze “Uso strumenti di misura” e “Interpretazione risultati di misura” |
| 3 | Apertura SF-2027-0042 per Pippo e Caio |
| 4 | Modalità C → CRS-027 → sessione 15/03/2027 → docente X → esito |
| 5 | Aggiornamento dei livelli delle competenze; nessuna mansione viene assegnata automaticamente |

# 6\. Flusso B – Richiesta Aggiornamento Mansione

|  |
| --- |
| **RAM-AAAA-NNNN  <br>Persona • mansione richiesta • richiedente • motivazione • approvatore** |

**↓**

|  |
| --- |
| **CONFRONTO AUTOMATICO  <br>Competenze richieste dalla mansione vs competenze formalmente possedute** |

**↓**

|  |
| --- |
| **TUTTE LE COMPETENZE SODDISFATTE?** |

|  |  |
| --- | --- |
| **SÌ  <br>Nessuna nuova SF  <br>→ approvazione mansione** | **NO  <br>Apertura/collegamento di 1..N SF sui gap  <br>→ rivalutazione requisiti** |

**↓**

|  |
| --- |
| **APPROVAZIONE RAM  <br>Assegnazione formale della mansione • aggiornamento SKM • eventuale autorizzazione firma** |

# 7\. Casistiche operative

## Caso 1 – Competenze DM6 acquisite “per osmosi”

|  |  |
| --- | --- |
| **Fase** | **Comportamento corretto** |
| Situazione | Pippo è assegnato a DM3. Il CAR rileva che Pippo ha acquisito competenze utili a DM6. |
| Nessuna formalizzazione | Se il CAR non vuole riconoscerle, il profilo resta invariato. |
| Formalizzazione | Il CAR apre SF-2027-0050, seleziona le competenze DM6 maturate, modalità P “esperienza interna”, verifica con osservazione/prova pratica e assegna i livelli. |
| Esito competenze | Il sistema aggiorna il profilo e segnala DM6 come “requisiti soddisfatti” o “parzialmente soddisfatti”. |
| Assegnazione DM6 | Quando il CAR vuole ufficializzarla, apre RAM-2027-0018. Se i requisiti sono già completi, nessuna nuova SF; la RAM passa direttamente ad approvazione. |

## Caso 2 – Corso che rende potenzialmente idoneo a DM6

|  |  |
| --- | --- |
| **Fase** | **Comportamento corretto** |
| Corso | Pippo partecipa a SF-2027-0063 che richiama CRS-031 e alimenta competenze utili a DM6. |
| Chiusura SF | Il Responsabile valuta i livelli; il sistema aggiorna le competenze e segnala l’idoneità potenziale. |
| Nessuna assegnazione automatica | DM6 non viene aggiunta alla SKM solo perché le competenze sono sufficienti. |
| Decisione successiva | Il CAR apre una RAM per DM6 quando serve operativamente. La RAM riutilizza le evidenze della SF già chiusa; nessuna seconda SF. |

## Caso 3 – Richiesta DM6 con gap ancora presenti

|  |  |
| --- | --- |
| **Fase** | **Comportamento corretto** |
| RAM | Il CAR richiede DM6 per Pippo. |
| Gap automatico | Il sistema rileva che 4 competenze sono soddisfatte e 2 mancanti. |
| Formazione | La RAM genera o collega una SF solo per le 2 competenze mancanti; una può essere A con registro, l’altra C con corso di catalogo. |
| Chiusura | Dopo la chiusura delle SF, il sistema rivaluta i requisiti; se completi, la RAM passa all’approvazione finale. |

## Caso 4 – Aggiornamento generale senza nuova mansione

|  |  |
| --- | --- |
| **Fase** | **Comportamento corretto** |
| Esigenza | Aggiornamento FOD, nuova procedura o corso SGI. |
| Evento | Si apre una SF per le persone coinvolte e le competenze interessate. |
| Effetto | Si aggiornano competenze e storico; non viene aperta alcuna RAM se non cambia la mansione assegnata. |

# 8\. Cosa visualizza il sistema

|  |  |
| --- | --- |
| **Vista** | **Informazione** |
| Profilo persona | Ruolo, reparto, mansioni, competenze, livelli, qualifiche, evidenze P/A/C |
| Mansioni potenziali | Mansioni non assegnate per le quali i requisiti risultano soddisfatti |
| Cruscotto Responsabile | SF aperte, competenze da valutare, RAM da proporre, persone potenzialmente idonee |
| Cruscotto RDD | Chiusure e assegnazioni mansione da approvare |
| MOD.053 dinamico | Storico aggregato e stampabile della persona |
| Skill Matrix | Solo stato corrente delle mansioni formalmente assegnate e relativi livelli |

# 9\. Regole applicative da implementare

-   La competenza può essere aggiornata soltanto tramite una Sessione Formativa chiusa e valutata.
-   La mansione può essere aggiunta soltanto tramite una Richiesta Aggiornamento Mansione approvata.
-   Competenza soddisfatta non equivale a mansione assegnata.
-   La RAM non genera automaticamente una nuova SF se le competenze sono già sufficienti.
-   Il sistema deve mantenere il collegamento RAM ↔ SF utilizzate come evidenza, anche se precedenti alla RAM.
-   Il sistema deve proporre automaticamente le competenze mancanti prendendole dal Catalogo Mansioni/Competenze.
-   Il sistema deve segnalare le mansioni potenzialmente sbloccate senza assegnarle.
-   P/A/C devono essere eventi multipli e storicizzati; nessuna sovrascrittura dello storico.
-   Le qualifiche obbligatorie o a scadenza continuano a richiedere le evidenze specifiche previste.

# 10\. Modello logico sintetico

|  |
| --- |
| **CATALOGHI  <br>Mansioni ↔ Competenze ↔ Corsi** |

**↓**

|  |
| --- |
| **SESSIONE FORMATIVA  <br>Persona + competenze + P/A/C + evidenze + livelli** |

**↓**

|  |
| --- |
| **PROFILO COMPETENZE  <br>Storico e livello corrente** |

**↓**

|  |
| --- |
| **RICHIESTA AGGIORNAMENTO MANSIONE  <br>Verifica requisiti + eventuali SF collegate + approvazione** |

**↓**

|  |
| --- |
| **SKILL MATRIX  <br>Mansioni formalmente assegnate e livello attuale** |

|  |
| --- |
| **DECISIONE ARCHITETTURALE  <br>La Sessione Formativa è l’unico evento che modifica formalmente le competenze. La Richiesta Aggiornamento Mansione è l’unico evento che modifica formalmente le mansioni assegnate. Il MOD.053 è l’output dinamico dello storico; la Skill Matrix è la fotografia corrente delle autorizzazioni.** |
