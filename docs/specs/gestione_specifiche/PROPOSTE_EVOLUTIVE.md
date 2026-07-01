# Proposte evolutive — gestione_specifiche (benchmark pratiche QMS/DMS)

> Idee concrete ispirate alle pratiche di document/quality management (ISO 9001:2015 §7.5,
> AS/EN 9100 §8.1/§8.4, IATF 16949, firme elettroniche stile 21 CFR Part 11) e ai pattern di
> piattaforme note (M-Files metadata-driven, MasterControl/ETQ change control, Greenlight Guru/
> Qualio per e-signature e training-on-release, ARXivar workflow). **Ogni voce**: cosa, perché,
> come si mappa sul nostro modello (stati S1-S9 / MOD.133 / distribuzione).
>
> ⚠️ **Nota fonti**: elenco redatto dalla conoscenza dell'assistente — **senza citazioni web**
> perché la ricerca online si è bloccata (tool web non disponibili in questo ambiente). Le
> clausole delle norme sono richiami generali, da verificare sul testo ufficiale.
>
> Legenda sforzo: 🟢 quick win · 🟡 medio · 🔴 grosso. Ultimo agg.: 2026-07-01.

## (a) Flow-down dei requisiti

1. **Tracciabilità requisito → azione → evidenza (chiusura del cerchio)** 🟡
   - *Cosa*: ogni riga MOD.133 collegata all'**artefatto a valle** che la soddisfa (documento CN
     aggiornato, OdL, revisione procedura, OFI) con **stato** (aperto/fatto) ed evidenza.
   - *Perché*: AS9100 §8.1 richiede il flow-down dei requisiti applicabili e la loro attuazione;
     una matrice di tracciabilità dimostra che ogni requisito è stato gestito.
   - *Mappa*: `RigaMOD133` ha già `rif_doc_cn`/`genera_ofi`; aggiungere un link nullable
     riga→artefatto (FK a task/OdL/procedura) + campo `stato_azione` + una **vista matrice** che
     mostra requisiti scoperti.

2. **Caratteristiche chiave / requisiti critici + KPI copertura** 🟡
   - *Cosa*: flag «requisito critico / key characteristic» sulle righe; KPI «% requisiti critici
     coperti/verificati».
   - *Perché*: AS9100/IATF trattano special/key characteristics con controllo rafforzato.
   - *Mappa*: bool `critico` su `RigaMOD133` + widget nel cruscotto KPI esistente.

3. **Tassonomia TAG di processo controllata** 🟢
   - *Cosa*: i TAG diventano un vocabolario **governato** (enum + gestione admin) invece di testo
     libero → flow-down consistente e ricercabile (pattern M-Files metadata-driven).
   - *Mappa*: già c'è `tag`/`tag_processo`; aggiungere un modello `TagProcesso` (catalogo) +
     autocomplete; il copilota AI propone dal catalogo.

## (b) Controllo revisioni e copie controllate

4. **Watermark di stato dinamico sulla copia servita** 🟢
   - *Cosa*: la copia distribuita/scaricata porta un timbro dinamico «COPIA CONTROLLATA — valida al
     GG/MM/AAAA» e le superate «SUPERATO / OBSOLETO».
   - *Perché*: ISO 9001 §7.5.3 — impedire l'uso involontario di documenti obsoleti.
   - *Mappa*: il toolkit F3 (`pdf_compose.applica_protezione`) fa già la filigrana; agganciarla al
     download/composito con testo per-stato.

5. **Registro copie controllate per destinatario** 🟡
   - *Cosa*: log «n° copia → reparto/persona → data emissione → data ritiro → presa visione», il
     classico *controlled copy register*.
   - *Perché*: EN 9100/ISO — distribuzione controllata e recupero delle copie superate tracciabili.
   - *Mappa*: oggi `Distribuzione` ha `n_copie_distribuite/ritirate` aggregati; aggiungere un figlio
     `DistribuzioneCopia` (per singola copia) → riconciliazione ritirate=distribuite **per copia**,
     non solo per numero (rafforza l'algoritmo già presente).

6. **Change request / controllo modifiche prima della revisione** 🔴
   - *Cosa*: una **richiesta di modifica** (con impact assessment) precede la nuova revisione e la
     genera; il MOD.133 È di fatto l'impact assessment.
   - *Perché*: MasterControl/ETQ e AS9100 §8.5.6 «controllo delle modifiche» formalizzano il change
     control con approvazione prima dell'attuazione.
   - *Mappa*: stato/entità «richiesta modifica» → alla conferma crea la nuova `Specifica`
     (revisione) collegata via `revisione_precedente` e apre il MOD.133.

7. **Retention/archiviazione delle superate** 🟢
   - *Cosa*: politica di conservazione sui documenti in `_SUPERATO` (per quanto, poi cosa).
   - *Perché*: requisiti di conservazione delle registrazioni (settore aero spesso 10+ anni).
   - *Mappa*: campo `retention_until` + job che segnala (non cancella) le superate oltre soglia.

## (c) Riesame periodico

8. **Riesame con esito registrato e firmato (non solo reminder)** 🟡
   - *Cosa*: la verifica 6 mesi produce un **record di riesame** con esito {conferma valida /
     serve revisione / obsoleta} + chi + data (+ firma).
   - *Perché*: ISO 9001 §7.5.2 — riesame e approvazione per idoneità; serve l'**evidenza** del
     riesame, non solo il promemoria.
   - *Mappa*: oggi c'è `data_verifica` + reminder; aggiungere `VerificaPeriodica(specifica, esito,
     attore, data)` e, se «serve revisione», scorciatoia per aprire la nuova revisione.

9. **Frequenza di riesame risk-based** 🟢
   - *Cosa*: intervallo di verifica per **tipo/criticità** (es. specifiche safety-critical più
     frequenti), non fisso a 6 mesi.
   - *Mappa*: `VERIFICA_PERIODICA_MESI` per tipo documento / flag criticità.

## (d) Approvazione, firme, separazione dei compiti

10. **Firma elettronica conforme (significato + ri-autenticazione + manifest immutabile)** 🟡
    - *Cosa*: alla chiusura/approvazione, **ri-inserimento password** (re-auth) e registrazione di
      una firma con **significato** («Compilato da» / «Approvato da»), nome, ruolo, timestamp;
      manifest reso sulla pagina MOD.133.
    - *Perché*: pratica 21 CFR Part 11 / Greenlight Guru/Qualio — la firma elettronica deve avere
      significato, essere legata all'utente e non ripudiabile.
    - *Mappa*: `mod133_approva` + `EventoSpecifica` immutabile già ci sono; aggiungere re-auth al
      submit e rendere il blocco firme del renderer F4 con «firma elettronica — <nome>, <ruolo>,
      <data/ora>». (Separazione compilatore≠approvatore **già enforced**.)

11. **Routing di approvazione condizionale** 🟡
    - *Cosa*: l'approvatore/i dipendono da tipo/impatto (es. impatto sicurezza → firma aggiuntiva
      RSPP; piano di qualità → firma cliente).
    - *Mappa*: regole di routing per `tipo`/impatto → set di approvatori richiesti prima di S3.

## (e) Reminder / escalation / SLA

12. **Cruscotto SLA con aging** 🟢
    - *Cosa*: viste «MOD.133 in ritardo», «approvazioni pendenti», «verifiche in scadenza» con
      fasce di aging (0-7 / 8-14 / >14 gg).
    - *Mappa*: estendere la dashboard KPI esistente (`/gestione-specifiche/kpi/`).

13. **Catena di escalation configurabile a più livelli** 🟡
    - *Cosa*: 7gg→destinatario, 14gg→approvatore+DM, 21gg→direzione (oggi 7/14 fissi).
    - *Mappa*: settings `ESCALATION_*` già presenti; aggiungere livello 3 + destinatari
      configurabili.

14. **Reminder di presa in carico in S1 (IN1, 7gg)** 🟢 *(già nel backlog F7)*
    - *Cosa/Mappa*: come il reminder MOD.133 ma sull'ingresso in Bozza (FLUSSO R16).

## (f) AI human-in-the-loop

15. **Provenienza + confidenza sulle proposte AI** 🟡
    - *Cosa*: ogni riga MOD.133 proposta mostra il **paragrafo sorgente** (da quale cambiamento
      deriva) e un indice di confidenza → validazione più rapida e audit «AI-assisted».
    - *Perché*: best practice AI in ambito regolato — le proposte devono essere **tracciabili** e
      mai auto-applicate (già rispettato: `proposto=True`, l'umano firma).
    - *Mappa*: il diff F5 restituisce già i `cambiamenti`; legare ogni riga proposta al blocco
      cambiato che l'ha generata.

16. **Marcatura audit «AI-assistita vs manuale»** 🟢
    - *Cosa*: registrare se una riga/campo è stato pre-compilato dall'AI (poi validato) o inserito a
      mano → trasparenza e revisione qualità.
    - *Mappa*: flag `origine` (ai/manuale) su `RigaMOD133` valorizzato all'accettazione della
      proposta.

## Priorità suggerita (quick win ad alto valore)
- 🟢 **#4 watermark di stato**, **#12 cruscotto SLA**, **#14 reminder S1**, **#3 tassonomia TAG**,
  **#16 marcatura AI** — piccoli, alto ritorno, si appoggiano a componenti esistenti.
- 🟡 poi **#8 riesame con esito firmato**, **#5 registro copie**, **#10 firma elettronica**,
  **#15 provenienza AI**, **#1 tracciabilità requisito→azione**.
- 🔴 **#6 change control formale** come evoluzione strutturale (facoltativa).
