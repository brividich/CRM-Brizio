# Diario di lavoro — fattibilità Ruoli → Mansioni → Competenze → Formazione

## Impostazione (21/11/2026)

- Worktree dedicato: `C:\Dev\pn-fattibilita-rmc`, ramo `feature/anagrafica-fattibilita-rmc`, base `origin/main` = `784cbf3ae` (21/11/2026).
  Tutte le citazioni `file:riga` si riferiscono a questo commit.
- Il prompt di missione è `PROMPT_fattibilita_ruoli_mansioni_competenze.md` (nel checkout condiviso, non tracciato).
- Input Qualità: nel checkout condiviso erano in `docs/feasibility/ruoli-mansioni-competenze/` (già convertiti in `.md`
  dai `.docx` il 21/11/2026; i `.docx` originali non sono nella cartella). Copiati in `input/`.
  - `input/MOD.053 BOZZA.md` — bozza della scheda formazione personale (assunzione, aggiornamento mansione, riepilogo).
  - `input/Specifica_Funzionale_Piattaforma_Formazione_Skill_Matrix_v2.md` — SF / RAM / SKM / MOD.053 dinamico.
- Vincoli: sola analisi, scrivo solo in questa cartella, nessuna scrittura su DB, subagenti solo sequenziali,
  GATE 1 dopo `01_asis.md`.

## Requisiti chiave letti negli input (prima lettura)

- Principio: competenza = ciò che la persona sa fare; mansione = ciò che è formalmente autorizzata a fare.
- SF (Sessione Formativa, `SF-AAAA-NNNN`) = unico evento che modifica le competenze; RAM (Richiesta Aggiornamento
  Mansione, `RAM-AAAA-NNNN`) = unico evento che aggiunge una mansione.
- P/A/C = modalità (Pregressa/esperienza, Affiancamento, Corso), non livelli; eventi multipli storicizzati.
- Livello corrente = ultima valutazione valida.
- Mansioni potenziali segnalate, mai assegnate in automatico.
- MOD.053 = report dinamico; SKM = fotografia corrente; MOD.040 = registro affiancamento allegato alla SF.
- MOD.053: all'assegnazione la mansione entra in SKM a livello I-Principiante (no firma OP); esito POS impossibile
  se il livello minimo non è raggiunto; firma RDD (assunzione) / MSO (aggiornamento mansione); verifica efficacia =
  conferma periodica SKM tracciata.
- Nota: l'esempio del MOD.053 usa livelli numerici (1, 2) mentre il testo parla di «I-Principiante» → da chiarire.

## Scoperte della ricognizione (21/11/2026) — percorsi relativi a `django_app/anagrafica/`

Vocabolario del codice (attenzione, i nomi ingannano):
- `CompetenzaSkm` (`models_skillmatrix.py:142`) = **mansione lavorativa** (colonna della skill matrix: macchina o processo).
- `VoceMacchinaCatalogo` (`:491`) = **competenza** di una mansione (livello minimo, bloccante, requisiti formali corso/qualifica/MOD.128).
- `CompetenzaCatalogo` (`:464`) = catalogo unico competenze (stessa competenza su più mansioni).
- `AbilitazioneMacchina` (`:324`) = persona × mansione lavorativa, livello I/L/U/O, `in_lista`.
- `AbilitazioneMacchinaVoce` (`:546`) = livello persona × competenza. Storici: `ValutazioneCompetenzaStorico` (`:568`), `AbilitazioneMacchinaStorico` (`:594`).
- `Mansione` (`models.py:637`) = **mansione di rischio** (DVR). La persona vi è legata per NOME (testo legacy `mansione`).
- `RuoloOperativo` (`models.py:396`) = catalogo unico ruoli (ha assorbito `RuoloAziendale`, `:1149`, 1 riga residua in prod).
- Etichette livelli a codice: I «In formazione», L «Intermedio», U «Autonomo», O «Formatore/Esperto» (`models_skillmatrix.py:33-37`).

Fatti del prompt risultati SUPERATI:
- `TrainingDeadline` non è più «non schedulata»: la ricostruisce `services/scadenze.py:49` dal motore unico
  `services/requisiti.py`, ogni notte (`automazioni/schedules.py:603-608`, cron 00:20; in prod lo schedule c'è, come flusso gestito)
  e a ogni salvataggio (`segnali_scadenze.py`, `scadenze.py:217`).
- `views.py` non è più monolitico: pacchetto `views/` (formazione.py 5.877 righe, dipendenti.py 6.395).
- Divergenza residua: `services/training_eligibility.py:88` (selezione candidati) ha una sua espansione delle regole
  (non filtra ruoli conclusi `:117`, né finestra di validità regola `:101`, legge lo stato dalla cache `:232`).
- Non esiste un FK `timbro` in `models_mpq.py`; esiste `MODALITA_ORGANIZZATIVO` (`:159`) e `services/mpq_timbri.py`.

Mancanze rispetto alla richiesta Qualità: nessuna SF con numerazione SF-AAAA-NNNN, nessuna RAM, nessuna modalità P/A/C
sulle valutazioni, nessun MOD.053 dinamico, nessuna «mansione potenziale», assegnazione mansione diretta senza approvazione
(`views_mansionario.py:566`, `services/mansionario_struttura.py:128`), valutazione legata al permesso
`anagrafica.skillmatrix.manage` senza vincolo di reparto (`views/qualifiche.py:1740-1769`).

Qualità dati PRODUZIONE (sola lettura, profilo `prod_readonly`, solo conteggi, 21/11/2026):
- 135 in forza; 3 senza mansione; 3 senza area; 0 senza ruolo; 40 con più ruoli; **56 senza alcuna mansione lavorativa in lista**.
- 242 mansioni lavorative attive (44 macchina, 198 processo); **0 competenze definite**, 0 `CompetenzaCatalogo`;
  182 mansioni senza persone; 20 senza mansione di rischio; 3 senza ruolo; 14 senza area.
- 443 abilitazioni in lista: I 46, L 84, U 110, **O 203**; tutte «a mano» (765 scatti import, 32 manuali);
  `prossima_revisione` vuota su 443; `data_assegnazione` vuota su 420; 1 campagna refresh aperta; 0 soglie copertura;
  continuità operativa 0 righe; 17 mansioni con un solo U/O.
- Formazione: **0 regole di obbligo**, 0 fattori di rischio/esposizioni, 774 corsi (763 una tantum, 0 con fonte obbligo),
  4.071 scadenze tutte non obbligatorie (31 scadute), 995 sessioni, 0 approvate MOD.040, 0 verifiche efficacia.
- MOD.128: 14 processi, 7 abilitazioni, 3 ruoli di processo (0 collegati a una mansione), 0 requisiti persona.
- Cambio mansione: 165 assegnazioni organizzative, 0 adempimenti, 0 override.
- `TrainingDeadline.ricalcolato_il` max 07/10/2026: il `bulk_update` non aggiorna `auto_now` → non è un indicatore di freschezza.
Script usati: scratchpad della sessione (`dq_rmc.py`, `dq2.py`…), non committati.

## Avanzamento

- [x] Lettura input
- [x] Inventario studi precedenti (`_lavoro/fonti.md`) — l'«analisi di miglioramento Formazione» è solo e-learning
      (rimossa il 07/10, `93340a676`); la «versione unificata» non esiste
- [x] Modello dati AS-IS
- [x] Motori di calcolo e divergenze (M1-M16, D1-D15)
- [x] Qualità dati (produzione, sola lettura)
- [x] `01_asis.md` scritto → **FERMO AL GATE 1** (21/11/2026): attendo le risposte alle domande Q1-Q14 e T1-T9
- [x] Studio del modulo Formazione → `01_asis.md` §11 (ciclo, uso reale, giudizio); domande Q15-Q17; risposte T1-T9 in §9.2.
      Dati chiave: 774 corsi di cui 595 a edizione unica, 0 verifiche, 0 efficacia, 0 approvazioni MOD.040, 0 qualifiche.
      Aggancio per la SF: `views/formazione.py:3265` (`_post_completamento`), schema corso → qualifica (`models_formazione.py:318`).
- [x] **GATE 1 superato** (21/11/2026). Risposte aggiuntive del proprietario:
      - corsi storici: si traccerà una linea, ma sarebbe utile **pescare dal vecchio catalogo**; dubbio da risolvere con
        la Qualità e **da riportare nel PDF finale**;
      - competenza nuova: **creata sul momento** dal form del corso, se necessaria;
      - Fase 2: **procedere con ipotesi dichiarate**, mostrando anche le altre soluzioni;
      - questionario breve per la Qualità: fatto → `Domande_per_la_Qualita.md` (18 domande, con «nostra ipotesi»).
      Le ipotesi del questionario sono quelle da usare nel TO-BE.
- [x] Fase 2 scritta: `02_tobe_flusso_algoritmo.md`. Dataset finto e motore di riferimento in `build/motore_rif.py`
      (genera `prototipo/dati/dataset.json` e `build/risultati.json`; data di riferimento 15/03/2027).
      Numeri chiave: 32 persone, 14 mansioni, 30 competenze, 65 assegnazioni = 30 conformi + 11 con riserva +
      10 sotto supervisione + 14 non conformi (9 persone); 44 gap; scadenze 5 scadute / 1 / 1 / 1; potenziali 1 + 21.
      Modello raccomandato: D ibrido (livello = atto umano via SF; validità calcolata con grazia 30 gg, esercizio 9/12 mesi,
      conferma 6 mesi). Livello sulla mansione = minimo delle bloccanti (la media D16 penalizza chi è in regola:
      `services/mansionario_competenze.py:113-120`, `:242`). Assegnazione: avviata → effettiva.
      Persone tipo: P01 Marco Rivalta, P02 Giulia Ferrante, P03 Aldo Bianchetti, P04 Sara Colombari, P05 Piero Lombardini.
- [x] **GATE 2 superato** (21/11/2026). Decisioni: (1) ibrido **non bloccante, solo segnalazione**; la variante bloccante
      resta alternativa documentata → parametro `modalita_validita` SEGNALAZIONE|BLOCCO in `build/motore_rif.py`;
      (2) livello mansione = minimo delle bloccanti; (3) avviata → effettiva; (4) **avanti fino alla fine, un passo alla volta**.
      Numeri in modalità SEGNALAZIONE: 30 conformi / 13 con riserva / 10 sotto supervisione / 12 non conformi (8 persone),
      gap 42, 2 assegnazioni con segnalazione grave. In BLOCCO: 30 / 11 / 10 / 14 (9 persone), gap 44.
      Il prototipo deve avere l'interruttore Segnalazione/Blocco.
- [x] Fase 3 fatta: `03_ux.md`, `prototipo/prototipo_rmc.html` (332 KB, file unico, CSS reali dell'HUB incorporati da
      `build/costruisci_prototipo.py`; logica in `prototipo/src/app.js`, stili aggiunti in `prototipo/src/app.css`),
      12 PNG in `prototipo/png/`. Verifica: `build/verifica_prototipo.py` (Playwright del venv del checkout condiviso):
      25 controlli ok, 0 errori di console, 0 richieste di rete, 360 px ok. Rotte: cruscotto-qualita, matrice,
      dipendente-<cognome>, editor-mansione, simulatore, coda-car, pianificatore, vista-dipendente.
      Nota tecnica: in questa shell gli heredoc bash con apostrofi falliscono → scrivere gli script con lo strumento Write.
- [x] GATE 3 (21/11/2026), risposte: (1) **aggiungere le pagine mancanti** → fatte: `#ram` (MOD.053 a video, passi,
      firme, esito POS bloccato), `#sessione-formativa` (multi-persona, P/A/C, effetti in anteprima), `#cruscotto-rdd`;
      (2) **pubblicare il prototipo come pagina privata** (variante in `prototipo/pubblicazione/prototipo-competenze-hub.html`);
      (3) nel PDF Direzione la proposta principale è **solo segnalazione**, il blocco in una riga.
      Poi richiesta in corsa: **inserimento di un nuovo dipendente** riusando l'esistente → analisi in `01_asis.md` §12
      (pratica di onboarding a 5 fasi, `services/onboarding.py`), proposta in `02_tobe` §6.6, pagina `#inserimento`.
      Prototipo ora: 12 schermate, 19 PNG, 37 controlli ok.
- [x] Riscontro del proprietario (21/11): «a un primo sguardo mi sembra diverso da come è in realtà» + «proponi un bel
      refactoring della UX e UI se lo ritieni necessario, creando un bel filo logico conduttore».
      Fatto: catturate 9 pagine REALI da un server di prova locale (SQLite usa-e-getta copiato da
      `C:/Dev/.pn-testdb/mailreg_pulito.sqlite3`, migrato, 6 persone inventate; DB cancellato, server fermato).
      Differenze trovate e corrette: carattere Outfit (incorporato), barra e menu reali (`prototipo/src/guscio/`),
      nomi in maiuscolo, viste «Oggi» = catture reali (`prototipo/src/oggi/`). Script: `build/prepara_guscio.py`.
      Menu reale del modulo: Dashboard · Scadenzario · Persone · Organizzazione · Competenze · Salute e sicurezza ·
      Amministrazione · Report · Impostazioni. Oggi il dominio è sparso: Persone › Ingressi › Onboarding;
      Organizzazione › Struttura › Mansionario; Competenze › Formazione/Qualifiche/Abilitazioni; Salute e sicurezza › cambi mansione.
      Proposta (`03_ux.md` §9): filo conduttore a 5 domande = 5 sezioni del menu (Requisiti · Mansioni · Competenze ·
      Quadro · Decisioni), striscia «sei qui» (riusa `mns-filo`), «Prossimo passo», testata unica, una sola matrice;
      blocco B13 in `02_tobe` §7.6. Prototipo: 12 schermate, 39 controlli ok, ~1,1 MB.
- [x] Prototipo pubblicato come pagina privata: https://claude.ai/artifact/HkCWgMqL5SCKZA2MAqrnkZ
      (ripubblicare lo stesso file `prototipo/pubblicazione/prototipo-competenze-hub.html` per aggiornarlo).
      Catture «oggi» rifatte senza l'etichetta `.devgit`: DB di prova nello scratchpad con settings `pn_proto`
      (`from config.settings.dev import *` + `DATABASES["default"]["NAME"]` nello scratchpad, PYTHONPATH), nessun file del progetto toccato.
- [x] Vincolo del proprietario (21/11): **«senza toccare nessun file, solo prototipi»**.
- [x] Richiesta: restyling dell'INTERA Anagrafica nel prototipo. Scelte: menu intero + 5 modelli di pagina; pilastri per
      percorso della persona; due varianti di aspetto a confronto. Fatto (`03_ux.md` §10): sei pilastri = sei domande
      (Persone · Struttura · Competenze · Formazione · Sicurezza · Da fare), 42 voci navigabili (16 costruite, le altre
      con la scheda «dove va»), modelli: ingresso di sezione, elenco, scheda, pratica a passi, matrice; nuove pagine
      `#persone`, `#elenco-dipendenti`, `#corso`, `#da-fare`, `#v-<voce>`; matrice con vista per competenza/per mansione;
      interruttore Stile attuale / Stile rinfrescato (classe `px-fresco`). 51 controlli ok, 26 PNG.
- [x] Riscontro del proprietario sul prototipo (21/11): **«ok mi piace, procedi con gli step successivi»** → GATE 3 superato.
- [x] **Fase 4 fatta** (21/11/2026): `Fattibilita_RMC_Tecnico.pdf` (86 pagine alla prima emissione, 93 con il capitolo 3b) e
      `Fattibilita_RMC_Direzione.pdf` (10 pagine: copertina + 9). Script: `build/costruisci_pdf.py`
      (markdown-it-py → HTML con `build/stampa.css` → Playwright `page.pdf()` → unione e segnalibri con PyMuPDF).
      Testi propri del PDF tecnico in `build/pdf_tecnico_testi.md` (sommario, decisioni, glossario, EN 9100);
      corpo della sintesi in `build/pdf_direzione.html`. I rimandi «§» dei markdown vengono rinumerati sul PDF.
      16 diagrammi Mermaid in `build/svg/` (mermaid-cli installato nello scratchpad, Chromium di Playwright; senza
      mermaid-cli lo script riusa gli SVG se il sorgente non è cambiato). Esiti in `build/controlli_pdf.txt`.
      Controlli: ogni pagina rasterizzata e guardata; 0 elementi fuori dall'area di stampa; nessuna pagina vuota;
      termini vietati nel PDF Direzione: nessuno; numeri chiave presenti e uguali (19 su 19 e 13 su 13).
      Allineamenti fatti ai markdown per coerenza: 51 controlli e 16 schermate in `03_ux.md`; «Quattro modelli a
      confronto», 11 parametri, somma delle stime (7-11 / 10-15 / 18-31 settimane) e rischio «segnalazione ignorata»
      in `02_tobe`; diagramma ER diviso in due in `01_asis.md`; cattura `03_matrice_perche.png` rifatta a pannello fermo.
- [x] Scoperta: la regola `build/` del `.gitignore` del repository escludeva l'intera cartella `build/` dell'analisi:
      gli script non erano mai entrati in git. Ora sono tracciati (aggiunti con `git add -f`): le modifiche ai file già tracciati si vedono normalmente, i file NUOVI in `build/` vanno aggiunti con `git add -f`.
- [x] Rilievo del proprietario (21/11): «pensavo includessi anche analisi e gap con i documenti presenti su
      `\\novisrv\sistema gestione integrato`». Giusto: le procedure erano state cercate solo nel repository.
      Fatto → `04_gap_sgi.md` (capitolo 3b del PDF tecnico). Letti in sola lettura dalla cartella di rete (272 file):
      MT CN 06 Rev.21, MOD.187, MOD.053 Rev.4, MOD.039, MOD.040, MOD.128, MOD.188, Manuale e allegati, MT CN 65 e altri,
      prEN 9100. Nessun documento copiato nel repository, nessun nominativo riportato; le copie di lavoro nello
      scratchpad sono state cancellate.
      Esiti principali: (1) MT CN 06 §8.3 definisce i livelli: **a L si firma** → soglia di firma portata a L in
      `02_tobe` e in `build/motore_rif.py` (i conteggi di conformità non cambiano: 30/13/10/12); nel portale è U;
      (2) §8.5: ogni emissione della skill matrix è approvata da Direzione/RDD → aggiunta l'«emissione approvata»;
      (3) MT CN 65: sospensione obbligatoria per i controlli non distruttivi → lì vale il blocco;
      (4) il MOD.053 Rev.4 contiene già la tabella ruolo → mansione → competenze: la tappa 0 è un caricamento;
      (5) MOD.187 del 30/04/2026: circa 690 livelli, circa 100 persone, 79 mansioni, contro 443/82/60 del portale;
      (6) sigle: RDD Responsabile della Direzione, MSM/MSO/MSA funzione Qualità, CAR Capo Area o Reparto;
      (7) 9 domande su 18 del questionario trovano risposta, almeno in parte: questionario aggiornato.
- [x] Due cognomi inventati del prototipo coincidevano con cognomi reali della skill matrix: sostituiti ovunque
      (Marco Rivalta, Sara Colombari); nessun altro cognome del dataset compare nei documenti letti. Prototipo
      ripubblicato sulla stessa pagina privata.
- [ ] Aperto: le 18 risposte della Qualità; la data di demarcazione e il ripescaggio dei corsi storici; il reparto pilota;
      la scelta dello stile (attuale o rinfrescato). Il ramo `feature/anagrafica-fattibilita-rmc` non è mergiato in `main`.

## Risposte del proprietario al GATE 1 (21/11/2026) — domande tecniche

- **T1 SF**: oggetto **nuovo**. Ci saranno corsi «formativi» e altri no: formativo = **alimenta competenze**. È la
  Qualità, **alla creazione del corso**, a decidere se agganciarlo a una competenza esistente o a una nuova (creata
  sul momento — risposta troncata, da confermare).
- **Rilievo**: la Fase 1 non ha studiato il **modulo Formazione attuale** → richiesto **studio completo del modulo**
  (ciclo corso → edizione → iscrizione → presenze → completamento → attestato → efficacia, e-learning, MOD.040, pagine,
  stati, chi fa cosa, dati reali, punti deboli), da aggiungere a `01_asis.md`; poi si riapre il GATE 1.
- **T2 assegnazione diretta**: resta **solo agli amministratori**; per gli altri la **RAM compilata a video**
  (il MOD.053 sezione aggiornamento mansione diventa un modulo del portale, precompilato e firmato a schermo).
- **T3 livelli attuali (443)**: orientamento = **SF di impianto** con modalità «pregresso» e una **linea di
  demarcazione** tipo «da gennaio 2027, con l'introduzione dell'HUB». Ancora allo studio lato loro.
- **T4 ricalcolo automatico**: **validità distinta dal livello** (il livello valutato lo cambia solo una SF; il
  calcolo automatico produce uno stato di validità separato).
- **T5 MOD.128**: non assegna più, **propone una RAM** precompilata.
- **T6 rinomina modelli**: da **valutare nel TO-BE** come blocco facoltativo.
- **T7 chi valuta**: si appoggia alla **«Responsabilità del reparto/area»** (organigramma), non a permessi a mano.
- **T8 prototipo**: **template reali + dati finti**, nessun DB e nessun server.
- **T9 documenti Qualità**: **restano** nel repository.
- Le domande Q1-Q14 per la Qualità restano aperte.

## Decisioni di lavoro

- Niente modalità piano formale: la Fase 1 richiede di scrivere `01_asis.md`, incompatibile con il blocco delle scritture.
- `CHANGELOG.md` non toccato: il prompt vieta scritture fuori da questa cartella (solo documentazione).
- Ipotesi preliminare per la Fase 2 (da validare): distinguere **livello valutato** (atto umano, via SF) da
  **stato di validità** (calcolato: requisito formale scaduto, mancato esercizio) per conciliare REQ-11/12 con il
  ricalcolo automatico del 28/10.

## Punto di ripresa (21/11/2026, sessione interrotta per limite di utilizzo)

- Prototipo sul guscio reale: fatto e committato (39 controlli ok). NON ancora pubblicato come pagina privata.
- DA FARE prima di pubblicare: le 4 catture in `prototipo/src/oggi/` mostrano ancora l etichetta di sviluppo `.devgit`
  (ramo git, in basso a destra). Rifarle: copia `C:/Dev/.pn-testdb/mailreg_pulito.sqlite3` in `django_app/db.sqlite3`,
  `migrate --settings=config.settings.dev` (DJANGO_DEBUG=1 LEGACY_AUTH_ENABLED=0), seed sintetico, runserver 127.0.0.1:8047 --noreload,
  cattura nascondendo `.devgit`, poi `build/prepara_guscio.py`, `build/costruisci_prototipo.py`, `build/verifica_prototipo.py`;
  fermare il server e cancellare il db. Gli script di seed e cattura erano nello scratchpad della sessione (da riscrivere).
- Poi: pubblicare `prototipo/pubblicazione/prototipo-competenze-hub.html` (approvato: privato), attendere il riscontro, Fase 4 (PDF).
