# MIGLIORAMENTI CONTATORI HUB

Analisi statica dell'app `django_app/contatori` (contatori MFC Canon, riconciliazione fatture).
Data analisi: 2026-07-13. Nessuna modifica applicata; test non eseguiti.

## Stato reale vs descrizione

- Modelli: **5**, non 4 (`Macchina`, `LetturaContatori`, `Fattura`, `RigaFattura`, `ImpostazioniSNMP` — models.py).
- Test: **8 classi / ~40 metodi** in `contatori/tests.py`, non 7 (il commit `c3a7497` dichiara "32 verdi", poi estesi con i 4 test D1 asset).
- Esiste già un'integrazione AI: il tool `contatori_summary` dell'assistente HUB (`ai_assistant/tools.py:2342-2454`, Ondata 6.1) espone aggregati read-only con gate ACL `contatori.dashboard.view` e audit — rilevante per la dimensione 3.
- Il modulo è innestato nell'HUB: navbar via migrazione `core/0067_soc_it_cn_category.py`, URL sotto `/contatori/` (`config/urls.py:70`), FK opzionale verso `assets.Asset` (D1).

---

## 1. CODICE

### 1.1 ALTO — Il pulsante "Leggi ora via SNMP" attribuisce la lettura al trimestre sbagliato nel flusso reale

`views.py:63-65` (e identico in `management/commands/leggi_contatori.py:17-18`): il trimestre è calcolato dalla **data odierna**. Ma il flusso operativo documentato è leggere i contatori *qualche giorno dopo* la chiusura fornitore (`services.py:6-8`; il seed conferma: la lettura Q2 è datata **6 luglio**, `seed_demo.py:25`). Se l'operatore preme il pulsante il 6 luglio, la lettura viene salvata come **2026-Q3**, non come Q2:

- la riconciliazione Q2 resta per sempre "lettura interna mancante";
- Q3 riceve una lettura prematura che verrà sovrascritta dalla lettura di ottobre (`update_or_create`), a sua volta attribuita a Q4 se fatta a gennaio… l'automazione SNMP, così com'è, **non serve mai il caso d'uso principale** (riconciliazione della fattura appena chiusa).

**Proposta (P0):** finestra di grazia — nei primi N giorni del trimestre (es. 15) attribuire la lettura al trimestre precedente — oppure select esplicita del trimestre accanto al pulsante. Nota correlata: `update_or_create` sovrascrive senza avviso anche una lettura `MANUALE`/`FATTURA` già presente per quel trimestre; almeno segnalare la sovrascrittura nel messaggio.

### 1.2 ALTO — `seed_demo` cancella TUTTI i dati senza conferma, e non è "demo"

`seed_demo.py:45-46`: `LetturaContatori.objects.all().delete(); RigaFattura...; Fattura...; Macchina.objects.all().delete()` — eseguito su produzione azzera lo storico reale (letture SNMP accumulate, collegamenti asset) e lo sostituisce con i 3 trimestri hardcoded. Il nome "seed_demo" invita a lanciarlo con leggerezza; il contenuto è costituito da **dati reali** (matricole vere, numeri fattura BASE 8658/V1, 1762/V1, 4095/V1, contatori reali) committati nel repo — sensibilità bassa (dati operativi propri, nessun dato personale) ma in tensione col principio "synthetic examples" del CLAUDE.md.

**Proposta (P0):** richiedere `--force` se esistono già dati; rinominare in `seed_contatori_storici` o spostare i valori in un fixture fuori dal codice.

### 1.3 MEDIO — `trimestre` è testo libero senza validazione

`LetturaContatori.trimestre` e `Fattura.trimestre` sono `CharField(max_length=8)` liberi (models.py:49,77) e il form di inserimento manuale (`forms.py:5-10`) non valida il formato. Un refuso ("2026Q2", "2026-q2", "Q2-2026") crea un trimestre fantasma che: rompe l'ordinamento lessicografico su cui si basa **tutto** (monotonia `services.py:97`, storico, `trimestri_disponibili`), spezza il join lettura↔fattura in `riconcilia`, e produce delta di consumo errati. L'intera correttezza del modulo poggia sulla convenzione `YYYY-Qn` mai enforced.

**Proposta (P1):** `RegexValidator(r"^\d{4}-Q[1-4]$")` sul campo + normalizzazione nel form. In alternativa (più robusta a lungo termine): campi `anno`/`quarter` interi con proprietà di visualizzazione.

### 1.4 MEDIO — Contatore azzerato/macchina sostituita: rilevato ma non gestibile

Il caso "contatore che va indietro" è **rilevato** (`controllo_monotonia`, services.py:90-115; azzeramento del delta negativo in `consumo_per_trimestre`:213-215) ed è persino testato sul refuso reale di LOGISTICA. Ma non esiste alcun modo di **chiudere** la segnalazione: i "cali di lettura" sono ricalcolati a ogni caricamento della dashboard e un reset legittimo (scheda madre sostituita, macchina rimpiazzata mantenendo la matricola) resterebbe come warning rosso per sempre. Inoltre il delta di consumo di quel trimestre viene azzerato (perdendo le copie reali fatte prima del reset) senza possibilità di correzione.

**Proposta (P1):** flag `reset_verificato` (o nota strutturata) sulla lettura che assorbe il calo: la monotonia lo salta, il consumo usa il valore post-reset come nuova base. Per la sostituzione macchina la prassi corretta resta "nuova matricola = nuova Macchina" — documentarlo nell'help del form.

### 1.5 MEDIO — Robustezza SNMP: buona gestione errori, ma lettura sequenziale dentro la richiesta HTTP

Cose fatte bene: import lazy di puresnmp (l'app parte senza la libreria), eccezione unica `SNMPError` con messaggi chiari ("host non impostato", "nessuna counter_map per modello", "contatori assenti: [...]"), timeout configurabile dal singleton, fail per-macchina che non blocca le altre (`views.py:68-77`).

Limiti: `leggi_snmp` esegue **in sequenza e dentro la richiesta HTTP** un walk SNMP per ogni macchina attiva. Con 5 macchine e timeout 3s il caso pessimo (tutte offline) è già ~15s di worker Waitress bloccato; ogni macchina aggiunta peggiora linearmente. Non c'è retry (una perdita UDP transitoria = lettura mancata fino al prossimo click) e il timeout di `send_udp` è per-pacchetto, quindi un walk lento può superare di molto i 3s nominali.

**Proposta (P2):** lettura per-macchina via HTMX (pattern già usato per i consumabili, che infatti non soffre del problema) oppure un task django-q con esito in pagina; 1 retry sul walk. Nota memoria HUB: schedulare con "I" (minuti), mai "S".

### 1.6 BASSO — Dettagli minori

- `riconcilia` fa 2 query per riga fattura (`services.py:44-47`): N+1 irrilevante a questa scala (4 contratti), da tenere d'occhio solo se la flotta cresce.
- Con letture interne parziali (una macchina del pool manca) l'esito è un generico "lettura interna mancante": non dice **quale** macchina manca (services.py:51-57).
- `Fattura.fornitore` è CharField libero con default "BASE" (models.py:76) mentre `Macchina.fornitore` usa `TextChoices` — incoerenza; `Fattura.periodo_dal` non è mai usato.
- `ImpostazioniSNMP.community` in chiaro nel DB: è una community read-only, rischio basso, ma è pur sempre una credenziale di rete.
- La counter map dichiara di essere confermata via discover solo sul C5840i (`snmp.py:21-22`): la conferma on-site per C5535i/C3822i è un TODO aperto dichiarato nel codice — finché non fatta, una lettura "riuscita" su quei modelli potrebbe mappare le categorie in modo errato (rischio dati sbagliati, non errore visibile).
- ACL: il tool AI dichiara "binding canonico sulla dashboard" (`ai_assistant/tools.py:2349`), ma nel codice versionato non c'è traccia della creazione del binding route↔permesso (solo la voce navbar in core/0067). Se il binding vive solo nel DB di prod, un'installazione pulita ha route non coperte; e le route di scrittura (`leggi-snmp/`, `macchine/`, export) andrebbero verificate con `acl_fallback_report --only-unbound` (P1).

### 1.7 Test: qualità alta, buchi mirati

I ~40 test sono ben fatti: invarianti su dati reali (totali Q2, scarto pool +490, refuso monotonia 539→366), mock corretti di SNMP, verifica del contenuto Excel con `load_workbook`, test del gate POST-only e della config SNMP usata davvero. Buchi reali:

- **`leggi_snmp` (la vista bulk) non è testata** — proprio quella col bug di attribuzione trimestre (1.1).
- `importa_lettura` non testata (né il rifiuto del duplicato macchina+trimestre via unique_together).
- `snmp._tabella`/`_consumabili_raw` mai esercitate nemmeno con walk mockato (il parsing OID→numero contatore è logica pura testabile).
- Nessun test su trimestre malformato (1.3) né su contratto in fattura senza macchine corrispondenti.

---

## 2. FRUIBILITÀ

### 2.1 Chi lo usa e con che frequenza

Il ciclo naturale è **trimestrale** (arrivo fattura BASE → lettura interna → riconciliazione), più consultazioni spot per i consumabili. Utente: chi gestisce i contratti di noleggio (amministrazione/IT). Il modulo è raggiungibile dalla topbar HUB ("Contatori MFC", categoria SOC IT - CN) e l'assistente AI può già rispondere a domande aggregate. La dashboard con "ultima lettura" e soglia stale a 100 giorni (`services.py:137`) è la giusta misura per un ritmo trimestrale.

Manca però il **promemoria attivo**: nessuno avvisa che il trimestre è chiuso e va fatta la lettura (o che è arrivato il momento di caricare la fattura). L'HUB ha già l'infrastruttura scadenze/notifiche — un reminder trimestrale renderebbe il ciclo affidabile invece che dipendente dalla memoria dell'operatore (P1, effort basso).

### 2.2 Il risultato della riconciliazione è chiaro… ma parla in copie, non in euro

La vista riconciliazione è ben leggibile (esito a pill, scarto col segno, regola spiegata nel sottotitolo, pool marcato). Però per **giustificare un costo** manca l'anello finale: il modello non conosce le **tariffe** (costo copia BN/COL per contratto, eventuali canoni/franchigie). Lo scarto è espresso in copie: "il fornitore ha contato 490 copie in meno di noi" va bene per il controllo tecnico, ma l'amministrazione ragiona in euro e oggi deve fare il conto a mano.

**Proposta (P1, il singolo miglioramento di maggior valore):** modello `TariffaContratto` (contratto, periodo validità, €/copia per i 4 contatori) → colonna "impatto €" nella riconciliazione e nell'export, totale fattura atteso vs fatturato. Trasforma il modulo da "verifica contatori" a "verifica fattura".

### 2.3 Esportabilità: Excel c'è ed è buono, manca il PDF "da fornitore"

`export.py` produce xlsx puliti (intestazioni, righe anomale in rosso, riga di riepilogo, 4 fogli per l'analisi) e i test ne verificano il contenuto. Per l'uso dichiarato (contestazione al fornitore / amministrazione) mancano: intestazione con numero fattura e periodo nel foglio riconciliazione (il numero c'è solo nel riepilogo in fondo), e un PDF firmabile/allegabile a una PEC di contestazione. Il PDF è P2: l'xlsx copre già il 90% dei casi.

---

## 3. OPPORTUNITÀ AI — quasi tutto è overengineering a questa scala

Contesto dimensionale: **5 macchine × 4 contatori × 1 lettura a trimestre = 20 punti dato per trimestre**. Ogni proposta va misurata contro questo numero.

- **Rilevamento anomalie nei consumi: NON serve un modello.** Con 3 trimestri di storico e cadenza trimestrale, "incremento anomalo" = confronto del delta col delta medio dei trimestri precedenti (±X%). È una regola di 10 righe in `services.py`, deterministica e spiegabile ("LOGISTICA: +38% di colore vs media"), integrabile nella pagina Analisi che già calcola i delta. Un modello statistico/ML su 20 punti per trimestre è rumore travestito da intelligenza. **Proposta (P2): regola semplice, zero AI.**
- **Previsione toner/manutenzione: il problema non è il modello, è che i dati non vengono salvati.** I consumabili sono letti live via SNMP (`leggi_consumabili`) e **mai persistiti**: nessuna serie storica → nessuna previsione possibile, con o senza AI. Se si vuole ("toner nero finirà tra ~3 settimane"), il prerequisito è una tabella `LetturaConsumabile` alimentata da un task settimanale; a quel punto basta una **proiezione lineare**, non serve ML. Valore comunque modesto: sulle Canon a noleggio il toner è tipicamente gestito/spedito dal fornitore. **Proposta (P2 opzionale): persistenza + proiezione lineare; niente modelli.**
- **Riepilogo in linguaggio naturale: già coperto, non duplicare.** Il tool `contatori_summary` dell'assistente HUB espone già consumo, classifica e ripartizione in linguaggio naturale, con ACL e audit. Un "report trimestrale testuale" statico (3 frasi: esito riconciliazione, totale copie, top reparto) si genera con un template Python senza LLM — deterministico, gratis, sempre corretto. L'unico uso sensato dell'LLM qui è quello già in essere: il Q&A conversazionale nell'assistente. **Proposta: nessun nuovo componente AI dedicato.**

In sintesi: l'investimento "AI" giusto per questo modulo è **zero nuovi modelli**; le due funzioni utili (soglia anomalia consumi, frase di riepilogo nel report) sono codice deterministico.

---

## 4. UI

### 4.1 Bug concreto: il selettore trimestre della riconciliazione porta a un 404

`templates/contatori/riconciliazione.html:9` — `onchange="location='/riconciliazione/'+this.value+'/'"` usa il percorso **assoluto senza il prefisso `/contatori/`** (il modulo è montato sotto `/contatori/`, `config/urls.py:70`). Cambiare trimestre dal menu a tendina naviga a `/riconciliazione/2026-Q1/` → 404. La vista principale del modulo ha il suo controllo primario rotto. Fix da una riga con `{% url 'contatori:riconciliazione_trim' %}`-template (P0).

### 4.2 Banner fuorviante quando manca la fattura

Se l'ultimo trimestre ha letture ma la fattura non è ancora stata caricata, `riconcilia` ritorna 0 righe e `ok=False` → la dashboard mostra "⚠ 0 contatore/i da controllare" (`dashboard.html:29-31`): sembra un problema, è solo una fattura non ancora arrivata. Distinguere tre stati: OK / anomalie / **fattura non ancora caricata** (P1, piccolo).

### 4.3 Il "grafico" nella scheda macchina è finto

`macchina.html:41` — la barra "Andamento totale copie" ha `width:{% if valori %}100{% else %}0{% endif %}%`: è sempre piena al 100% per tutte le categorie, non comunica nulla (e può far credere a un dato). O si rende proporzionale (come fanno correttamente le barre di `analisi.html` con `and_max`/`cons_max`) o si toglie (P1, piccolo).

### 4.4 Dashboard con trend storico: esiste già, va solo collegata meglio

La pagina **Analisi** copre già il trend flotta (andamento cumulato, consumo per trimestre, classifica reparti, ripartizione BN/colore) con barre CSS proporzionali ed export dedicato: non serve una nuova dashboard. Ciò che manca:

- nella **vista puntuale di riconciliazione**, una colonna "scarto trimestre precedente" per capire a colpo d'occhio se uno scarto è fisiologico o in crescita;
- nella **scheda macchina**, una vera mini-serie per trimestre (tabella delta o sparkline) al posto del grafico finto — i dati sono già pronti in `storico_macchina`;
- la card "Trimestre corrente" in dashboard mostra in realtà *l'ultimo trimestre con dati* — etichettarla così.

Con questi tre ritocchi la struttura attuale (dashboard operativa + analisi storica + dettaglio macchina) è giusta per la scala del modulo.

---

## Priorità riassuntiva

| # | Intervento | Dim. | Severità/Valore | Effort |
|---|-----------|------|-----------------|--------|
| P0-1 | Fix selettore trimestre riconciliazione (404) — `riconciliazione.html:9` | UI | ALTO (vista principale rotta) | Minimo |
| P0-2 | Attribuzione trimestre in `leggi_snmp`/`leggi_contatori`: finestra di grazia o scelta esplicita | Codice | ALTO (l'automazione SNMP oggi non serve la riconciliazione) | Basso |
| P0-3 | Guardia `--force` su `seed_demo` (oggi cancella tutti i dati reali senza conferma) | Codice | ALTO | Minimo |
| P1-1 | Modello tariffe contratto → scarto e totale in € in riconciliazione ed export | Fruibilità | ALTO (chiude il caso d'uso fatturazione) | Medio |
| P1-2 | Validatore formato `trimestre` (`^\d{4}-Q[1-4]$`) su modello e form | Codice | MEDIO | Minimo |
| P1-3 | Flag "reset verificato" per assorbire cali legittimi di contatore | Codice | MEDIO | Basso |
| P1-4 | Stato "fattura non ancora caricata" in dashboard; test per `leggi_snmp` e `importa_lettura`; verifica binding ACL route non-dashboard (`acl_fallback_report`) | Codice/UI | MEDIO | Basso |
| P1-5 | Promemoria trimestrale "fai la lettura / carica la fattura" via scadenzario HUB | Fruibilità | MEDIO | Basso |
| P2-1 | Lettura SNMP per-macchina via HTMX o task background + 1 retry | Codice | MEDIO (scala con la flotta) | Medio |
| P2-2 | Soglia anomalia consumi (regola deterministica, no AI) nella pagina Analisi | AI→Codice | MEDIO | Basso |
| P2-3 | Persistenza letture consumabili + proiezione lineare esaurimento (solo se serve davvero: toner gestito dal fornitore) | AI→Codice | BASSO | Medio |
| P2-4 | Sparkline reale scheda macchina; colonna "scarto trimestre prec." in riconciliazione; export PDF contestazione | UI/Fruibilità | BASSO-MEDIO | Basso |
| P2-5 | Valutare convergenza con `assets.AssetMeter`/`AssetMeterHistory` (sistema contatori parallelo nel modulo assets, D1 ha già la FK) | Codice | BASSO (debito architetturale) | Alto |

## Limiti dell'analisi

- Analisi statica: test non eseguiti; comportamento SNMP non verificato contro macchine reali.
- Il binding ACL v2 delle route vive nel DB: la copertura effettiva in prod va confermata con `acl_fallback_report --only-unbound`.
- Non ispezionati: `admin.py`, CSS, `collega_asset.py` in dettaglio, template `analisi.html`/`macchine.html` (letti solo per verifiche mirate).
