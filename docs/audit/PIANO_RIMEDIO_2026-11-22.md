# Piano di rimedio dell'audit del 22/11/2026

Piano per chiudere le voci di [AUDIT_PORTALE_2026-11-22.md](AUDIT_PORTALE_2026-11-22.md); i numeri fra parentesi quadre sono quelli di [PROPOSTE_MIGLIORAMENTO_2026-11-22.md](PROPOSTE_MIGLIORAMENTO_2026-11-22.md). Basato su `main` `c29d82c7c`; voci S2, S3, C1, C2, G1, H1 ricontrollate sul codice il 22/11.

## Perimetro e decisioni prese

Perimetro: **Priorità 1 + robustezza** ([22], [43], [48], [50], [56]). Restano fuori le altre proposte di priorità 2 e 3 (nuove funzioni), da scegliere in un secondo momento. [1] è già fatta (anomalie 0032, rel `9d8a9091`); [2] è scartata: il link delle anomalie resta senza login.

| Tema | Decisione |
|---|---|
| G3 eliminazione segnalazioni | Archiviazione con motivo obbligatorio + «Ripristina», come nel Diario del preposto |
| G1 indice infortuni | Ore in proporzione all'anno trascorso (organico × 2.000 × giorni trascorsi/365); accanto all'indice va scritta la base usata |
| C2 gravità SOC | «Attenzione» sotto «Medio» anche nella postura |
| S6 presa visione SDS | Il link della mail apre una pagina con il pulsante «Confermo di aver letto» |
| K1 calendari | Fonte unica = **calendario Assenze** (festivi nazionali, patrono, sabato lavorativo e chiusure aziendali impostati lì) per tutti i moduli |
| K2 RENTRI | Termine di legge: festivi nazionali e patrono sì, chiusure aziendali **no** |
| S4 mail automazioni | Tutti i segnaposto neutralizzati, tranne un elenco esplicito di quelli generati dal portale (tabelle, link) |
| Piste | Verificate nell'ultima ondata; si propone solo ciò che risulta reale |
| Rilasci | Un'ondata = un branch `feature/…` → `main` → `release/prod` |

## Ondate

Ogni ondata è rilasciabile da sola. Per ciascuna: test solo delle app toccate con `--keepdb`, `makemigrations --check` (branch paralleli), `CHANGELOG.md` [Unreleased], guida in-app e Centro guide dove cambia ciò che l'utente vede, `docs/moduli/<app>.md`, checklist di bump versione.

### Ondata 1 — Sicurezza rapida · `feature/sicurezza-rimedi-audit` · nessuna migrazione

**Stato 22/11: fatta** (S2-S7). Censimento S4: nessun segnaposto con HTML generato dal portale, `SEGNAPOSTO_HTML_AMMESSI` vuoto. Trovato e corretto anche il corpo libero dei modelli di approvazione (`approval_email_templates.py`), che aveva lo stesso difetto.

| Voce | Intervento | File | Test |
|---|---|---|---|
| S2 [11] | `next` passato da `safe_next` / `url_has_allowed_host_and_scheme`, ripiego sulla pagina dell'attività | `tasks/views/spostamenti.py:35,38`; `core/views.py:1101-1116` | redirect esterno → pagina interna |
| S3 [12] | Il percorso deve stare dentro la cartella dei pacchetti (`Path.resolve()` + `is_relative_to`); meglio passare il solo nome del file | `admin_portale/views/release.py:357-369` | `..\`, UNC, altra cartella → 404 |
| S4 [13] | Prima censimento dei segnaposto usati dai modelli salvati; poi `escape()` su ogni valore, con elenco esplicito dei segnaposto HTML generati dal portale; via il `mark_safe` sul risultato grezzo | `automazioni/services.py:1585-1604`, `:4545`, `:4592` | `<a href>` in una descrizione arriva come testo; le tabelle generate restano tabelle |
| S5 [14] | Controllo del permesso di amministrazione in ogni vista (decoratore unico); legame canonico per `admin_sincronizzazione`; timbro validato da `core/upload_mime.py` | `gestione_specifiche/admin_views.py`, `acl_bootstrap.py`, `urls.py:52` | utente senza permesso → 403; file non immagine → rifiutato |
| S6 [9] | La GET mostra l'elenco delle schede da leggere e un form POST con CSRF; la presa visione si registra solo nel POST | `schede_sicurezza/views.py:682-706`, template | GET non registra nulla; POST registra |
| S7 [48] | `prod.py`: `ACL_STRICT_CANONICAL` attivo per default (spegnimento solo esplicito, come `ACL_DISABLE_ACKNOWLEDGED`) | `config/settings/prod.py` | test sulle impostazioni |

**Prerequisito S7, a mano su NOVISQL:** leggere `ACL_STRICT_CANONICAL` nel `config\.env` di produzione e lanciare `acl_strict_readiness`: se le rotte in fallback sono più di zero vanno legate prima del rilascio. Era attivo sul vecchio server dal 05/06/2026; dopo il passaggio a NOVISQL non è stato ricontrollato.

Guide: Schede di sicurezza (nuova pagina di conferma).

### Ondata 2 — Invii ripetuti o persi · `feature/invii-affidabili-audit` · migrazione solo se serve un campo versione

| Voce | Intervento | File | Test |
|---|---|---|---|
| A1-A3 [3] | Invio in due tempi: in transazione `select_for_update` si «prende» la notifica e si copia lo snapshot svuotandolo; invio fuori transazione; a fine invio si segna «notificato» solo se non sono arrivate decisioni nuove (confronto su un contatore o su `updated_at`). In caso di errore lo snapshot torna in coda | `anomalie/mail_action_service.py:833-949` | due invii in contemporanea = una mail; decisione durante l'invio = parte al giro dopo; seconda decisione = il riepilogo contiene solo quella |
| R1 [15] | Prossima data calcolata e salvata con `select_for_update` **prima** dell'invio; errore registrato sul report senza bloccare l'avanzamento | `core/report_centro/pianificazione.py:290-312` | errore durante l'invio → nessun nuovo tentativo ogni ora |
| R2 [16] | Promemoria se i giorni mancanti sono ≤ 7 (o ≤ 2) e quel promemoria non è ancora partito; serve la memoria di cosa è stato inviato (registro esistente o campo) | `procedure_refresh/tasks.py:231-235` | controllo saltato a 7 giorni → il promemoria parte a 6 |

Nota SQL Server: `select_for_update` va provato su SQL Server (`mssql-django` usa `WITH (UPDLOCK, ROWLOCK)`), non solo su SQLite.

### Ondata 3 — Sicurezza sul lavoro · `feature/hse-rimedi-audit` · migrazioni `rilevazione_incidenti`, `schede_sicurezza`

| Voce | Intervento | File | Test |
|---|---|---|---|
| G1 [4] | Ore = organico × 2.000 × giorni trascorsi/365 (anno intero per gli anni chiusi). Accanto al TRIR: «calcolato su N giorni, M ore stimate, organico X» | `rilevazione_incidenti/services.py:51-72`, template KPI | giugno: indice ≈ doppio di oggi a parità di dati |
| G2 [4] | `active_headcount` distingue «zero» da «non disponibile»: con anagrafica non raggiungibile si mostra un avviso e si registra nei log | `rilevazione_incidenti/services.py:23-27` | eccezione nell'anagrafica → avviso visibile |
| G3 [5] | Campi archiviazione (quando, chi, motivo); «Elimina» diventa «Archivia» con motivo obbligatorio; cestino con «Ripristina»; elenchi, KPI ed export escludono gli archiviati; registro azioni su entrambe le operazioni | `rilevazione_incidenti/models.py`, `views.py:1080-1104`, template | archivia/ripristina, archiviate escluse dal TRIR, permessi |
| H1 [8] | «Da rivedere» da `data_revisione_fornitore` (il campo c'è già), con `data_caricamento` come ripiego; il caricamento chiede la data di revisione | `schede_sicurezza/models.py:193-198`, form | scheda con revisione 2021 caricata oggi → da rivedere |
| H2 [18] | Cambio di versione corrente in `transaction.atomic` + `select_for_update` sulle sorelle; vincolo unico filtrato sulla versione corrente (condizione positiva `corrente=True`: SQL Server non accetta `NOT` negli indici filtrati) | `schede_sicurezza/models.py:185-190`, migrazione | due versioni correnti → errore di integrità |
| D1 [17] | «In ritardo» con `_locale(creata).date()` | `diario_preposto/cruscotto.py:83-84` | annotazione alle 00:30 ora italiana |

Prima della migrazione H2: controllo che in produzione non ci siano già due versioni correnti della stessa scheda; in caso contrario una migrazione dati tiene la più recente.

Guide: Segnalazioni (Archivia/Ripristina, spiegazione del TRIR), Schede di sicurezza (data di revisione), Centro guide degli stessi moduli.

### Ondata 4 — SOC · `feature/soc-rimedi-audit` · nessuna migrazione

| Voce | Intervento | File | Test |
|---|---|---|---|
| C1 [6] | Mappa dei passaggi ammessi (es. chiuso → solo «riapri»); `_transition_alert` rilegge la riga con `select_for_update` dentro `transaction.atomic`, rifiuta i passaggi non ammessi con un messaggio chiaro; il registro conserva il vecchio stato letto sotto blocco | `security/services/alert_lifecycle.py:136-180` e chiamanti | chiuso → in lavorazione rifiutato; due operatori: il secondo vede lo stato aggiornato |
| C2 [7] | Una sola scala in un punto solo (`_rango`); `ALERT_PENALTY[WARNING]` sotto `MEDIUM` (proposta: 3 contro 5) | `security/services/posture.py:36-42`, `rule_engine.py:1132` | ordine e pesi coerenti |
| S8 [22] | Test che apre ogni rotta di `security/urls_hub.py` con un utente senza permesso e pretende 403/redirect al login (JSON 401/403 per le API) | nuovo test in `security/` | fallisce se si aggiunge una rotta scoperta |

C2 cambia il voto di postura (sale un poco dove ci sono avvisi «attenzione»): va scritto nella guida SOC e nel CHANGELOG, perché lo storico dei voti avrà un piccolo salto.

### Ondata 5 — Calendario unico da Assenze · `feature/calendario-unico` · nessuna migrazione prevista

1. **Fonte unica:** il calcolo canonico resta in `core/calendario_it.py` (core non deve dipendere da un'app), ma legge da Assenze, con import ritardato e ripiego sui soli festivi nazionali se la lettura fallisce: festivi nazionali (compreso **San Francesco, 4 ottobre, dal 2026**, oggi assente in `core/calendario_it`), patrono e sabato lavorativo dalle impostazioni Assenze, `ChiusuraAziendale`. Due funzioni: `giorni_lavorativi(..., chiusure=True)` per l'operatività e `chiusure=False` per i termini di legge. `assenze/hr.festivita` diventa un adattatore sullo stesso calcolo.
2. **Moduli da portare sul calcolo unico:** anomalie (`tempi_service.py:82`), attività (`tasks/services/calendar_it.py`), specifiche (`gestione_specifiche/date_utils.py`), scadenzario (`scadenzario/calendario.py`: il patrono in `SiteConfig «scadenzario_patrono»` va confrontato con quello di Assenze; se diversi ti chiedo quale tenere prima di togliere la chiave), carichi macchina (`saturazione.py:15` e gli altri otto punti, K3), RENTRI (`rentri/verifica.py:52-62`, K2, senza chiusure).
3. **Test:** stesso giorno lavorativo in tutti i moduli per Pasqua, 4 ottobre 2027 (lunedì), patrono, una chiusura aziendale; RENTRI con un festivo nel mezzo non segnala ritardo e con una chiusura sì.
4. **Prestazioni:** il calendario dell'anno viene letto una volta per richiesta/elaborazione (cache in memoria per anno), non per ogni giorno.

Guide: Impostazioni Assenze («questi giorni valgono per tutto il portale»), RENTRI, Carichi macchina, Scadenzario.

### Ondata 6 — Robustezza · `feature/robustezza-audit`

| Voce | Intervento |
|---|---|
| [56] | Tutti i caricamenti passano da `core/upload_mime.py` (elenco dell'audit: `security/views_backup.py:120`, `admin_portale/views_sapere.py:63`, `procedure_refresh/views_modifiche.py:266`, `sistema_gestione/esterni_views.py:136,257`, `attrezzature/views.py:290`, `assets/views/layout.py:530`, timbro specifiche); test che cerca `request.FILES` fuori dal validatore, sul modello di `core/test_sql_census.py` |
| [43] | Le 37 eccezioni inghiottite di anomalie e quelle del SOC citate (`overview.py`, `defender_alerts.py`, `event_triage.py`) ricevono almeno `logger.exception`; nessun cambio di comportamento |
| [50] | Prima verifica dei numeratori (`anagrafica/services/mpq_utensili.py:22`, `sistema_gestione/services/audit.py:171`) e dell'ordinamento come testo di DPI e ticket; se confermati, numeratore sicuro con ritentativo e ordinamento numerico |

### Ondata 7 — Verifica delle piste · solo analisi

Rilettura riga per riga delle voci «Pista» non coperte sopra: cartella di rete libera in specifiche, `AdaptiveSecureCookieMiddleware`, QR asset senza scadenza, `docs/ai/02_ARCHITECTURE.md` (S11), Diario `ripristina`/`rimanda_scheda`, ticket SLA, assenze per nome, approvatori DPI, soglie KICK-OFF, assistente AI, pausa automazioni, query per riga (segnalazioni, SDS, scadenzario, regole di soppressione SOC). Esito: tabella confermata/scartata, con la proposta di intervento per le confermate, da scegliere.

## Ordine e stima

| Ondata | Peso | Migrazioni | Rischio |
|---|---|---|---|
| 1 Sicurezza rapida | S-M | no | S4 può alterare mail esistenti: censimento prima |
| 2 Invii | M | forse | concorrenza: prova su SQL Server |
| 3 Sicurezza sul lavoro | M | sì | dati esistenti per H2 |
| 4 SOC | M | no | voto di postura che cambia |
| 5 Calendari | M-L | no | tocca 6 moduli: un test comune |
| 6 Robustezza | M | no | basso |
| 7 Piste | S | — | — |

Ondate 1-4 indipendenti; la 5 dopo la 3 solo se si vuole un rilascio per volta. Ogni ondata si chiude con commit e push del branch, merge in `main` e poi in `release/prod`; il deploy resta una scelta separata.
