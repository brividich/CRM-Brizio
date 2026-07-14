# BUILD_SPEC — Modulo Suggestion Corner (NOVICROM HUB)

**Basata su:** ANALISI_FATTIBILITA_suggestion_corner.md + decisioni Brizio 08/07/2026
**App Django:** `suggestion_corner` (nuova app, top-level — non dentro `anagrafica`, per isolare l'endpoint pubblico)

---

## 0. Decisioni chiuse

| # | Decisione |
|---|---|
| 5.1 | Pagina pubblica **non-ACL** dentro HUB (sostituisce Microsoft Forms), rate-limited, senza login |
| 5.2 | Migrazione storico da fonte pulita (**non** dal CSV fornito — vedi §7) |
| 5.3 | Cutover netto: PowerApps dismesso dopo go-live, nessun doppio binario. Righe aggiunte tra oggi e go-live: caricamento manuale a cura di Brizio |
| 5.4 | Promemoria automatici confermati (30/15/5 giorni) |
| 5.5 | `Reparto` → riuso modello esistente in `anagrafica`. `Processo` → da valutare in corso d'opera, per ora FK nullable con fallback a testo libero |
| 5.6 | Storicizzazione reale dei cambi di stato (non solo `updated_at`/`updated_by`) |
| 6.1 | AI copilot per classificazione SMS_SI/NO + bozza PLAN — **incluso in MVP** |
| 6.2 | Deduplica semantica — **incluso in MVP** |
| 6.3 | Escalation automatica su scaduto — **incluso in MVP** |
| 6.4 | Audit trail completo — **incluso in MVP** |
| 6.5 | Dashboard KPI — **incluso**, con dati veritieri (niente placeholder/mock) |
| 6.6 | Collegamento a NC/Azioni Correttive — **rimandato**, confluirà in futuro portale OFI aggregatore |
| 6.7 | Notifiche in-app oltre email — **incluso** |
| 6.8 | Regola compilatore≠controllore — **inclusa**, parametri di soglia escalation gestibili da sezione admin del modulo |

---

## 1. Modelli

### 1.1 `SuggestionCorner` (record principale)

```python
class SuggestionCorner(models.Model):
    class StatoSMS(models.TextChoices):
        DA_GESTIRE = "DA_GESTIRE", "Da gestire"
        SMS_SI = "SMS_SI", "SMS Sì"
        SMS_NO = "SMS_NO", "SMS No"

    class EsitoAttivita(models.TextChoices):
        SI = "SI", "Sì"
        NO = "NO", "No"

    class EsitoCheck(models.TextChoices):
        POSITIVO = "POSITIVO", "Positivo"
        NEGATIVO = "NEGATIVO", "Negativo"
        RINVIATO = "RINVIATO", "Rinviato"  # confermato dai dati reali (2/55 record) — assente nella prima bozza

    # Identificazione / provenienza
    legacy_sharepoint_id = models.IntegerField(null=True, blank=True, unique=True, db_index=True)
    da_portale = models.BooleanField(default=True)  # True = nuovo, False = migrato
    anonima = models.BooleanField(default=False)

    data_segnalazione = models.DateField(auto_now_add=True)
    reparto_provenienza = models.ForeignKey("anagrafica.Reparto", on_delete=models.PROTECT, related_name="segnalazioni_provenienza")
    reparto_destinazione = models.ForeignKey("anagrafica.Reparto", on_delete=models.PROTECT, null=True, blank=True, related_name="segnalazioni_destinazione")
    processo = models.ForeignKey("anagrafica.Processo", on_delete=models.SET_NULL, null=True, blank=True)
    processo_libero = models.CharField(max_length=255, blank=True)  # fallback se FK non popolabile

    opportunity = models.TextField()

    # PLAN
    plan_testo = models.TextField(blank=True)
    plan_eseguito = models.BooleanField(default=False)
    incaricato = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="suggestioncorner_do")
    controllore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="suggestioncorner_check")
    data_limite_esecuzione = models.DateField(null=True, blank=True)
    data_limite_controllo = models.DateField(null=True, blank=True)

    # DO
    do_testo = models.TextField(blank=True)
    do_eseguito = models.BooleanField(default=False)
    data_esecuzione_do = models.DateField(null=True, blank=True)
    esito_do = models.CharField(max_length=8, choices=EsitoAttivita.choices, blank=True)

    # CHECK
    check_testo = models.TextField(blank=True)
    check_eseguito = models.BooleanField(default=False)
    data_esecuzione_check = models.DateField(null=True, blank=True)
    esito_check = models.CharField(max_length=10, choices=EsitoCheck.choices, blank=True)

    # ACT
    vuoi_inserire_act = models.BooleanField(default=False)
    act_testo = models.TextField(blank=True)
    act_eseguito = models.BooleanField(default=False)
    nuova_segnalazione_da_act = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="generata_da")

    # Stato FSM
    stato = FSMField(default="INSERITA")
    stato_sms = models.CharField(max_length=10, choices=StatoSMS.choices, default=StatoSMS.DA_GESTIRE)

    # Reminder tracking (non più colonne statiche Scaduto*, calcolate a runtime — vedi §3)
    sollecito_do_30 = models.BooleanField(default=False)
    sollecito_do_15 = models.BooleanField(default=False)
    sollecito_do_5 = models.BooleanField(default=False)
    sollecito_check_30 = models.BooleanField(default=False)
    sollecito_check_15 = models.BooleanField(default=False)
    sollecito_check_5 = models.BooleanField(default=False)
    escalation_do_inviata = models.BooleanField(default=False)
    escalation_check_inviata = models.BooleanField(default=False)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    @property
    def scaduto_do(self):
        return bool(self.data_limite_esecuzione and not self.do_eseguito and self.data_limite_esecuzione < timezone.now().date())

    @property
    def scaduto_check(self):
        return bool(self.data_limite_controllo and not self.check_eseguito and self.data_limite_controllo < timezone.now().date())
```

`ScadutoC`/`ScadutoD` diventano **property calcolate**, non colonne — eliminano il rischio di disallineamento visto nel sistema legacy.

### 1.2 `SuggestionCornerAllegato`

```python
class SuggestionCornerAllegato(models.Model):
    segnalazione = models.ForeignKey(SuggestionCorner, on_delete=models.CASCADE, related_name="allegati")
    file = models.FileField(upload_to="suggestion_corner/%Y/")
    link_esterno = models.URLField(blank=True)  # per i vecchi path \\novisrv\... non migrabili come file reali
    caricato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    caricato_il = models.DateTimeField(auto_now_add=True)
```

I path storici tipo `\\novisrv\Area Qualità\SMS_Suggestion Corner\2024` (visti nel CSV) **non sono file scaricabili via CSV** — vanno recuperati dalla share di rete direttamente o lasciati come `link_esterno` testuale in migrazione.

### 1.3 `SuggestionCornerStorico` (audit trail reale — punto 5.6)

```python
class SuggestionCornerStorico(models.Model):
    segnalazione = models.ForeignKey(SuggestionCorner, on_delete=models.CASCADE, related_name="storico")
    stato_precedente = models.CharField(max_length=30)
    stato_nuovo = models.CharField(max_length=30)
    campo_modificato = models.CharField(max_length=50, blank=True)  # opzionale, per modifiche di campo fuori transizione FSM
    valore_precedente = models.TextField(blank=True)
    valore_nuovo = models.TextField(blank=True)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
```

Popolato automaticamente da signal `post_transition` di django-fsm-2 + da un `pre_save` che diffa i campi PLAN/DO/CHECK/ACT.

### 1.4 `SuggestionCornerConfig` (singleton, punto 6.8 — sezione admin del modulo)

```python
class SuggestionCornerConfig(models.Model):
    giorni_sollecito_1 = models.PositiveIntegerField(default=30)
    giorni_sollecito_2 = models.PositiveIntegerField(default=15)
    giorni_sollecito_3 = models.PositiveIntegerField(default=5)
    giorni_escalation_oltre_scadenza = models.PositiveIntegerField(default=7)  # X giorni dopo la scadenza → mail al responsabile
    email_responsabile_escalation = models.EmailField(blank=True)
    sms_team_group_name = models.CharField(max_length=100, default="SMS_TEAM")

    class Meta:
        verbose_name = "Configurazione Suggestion Corner"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
```

---

## 2. FSM — stati e transizioni

```python
class SuggestionCorner(models.Model):
    ...
    @transition(field=stato, source="INSERITA", target="DA_CLASSIFICARE")
    def notifica_sms_team(self): ...

    @transition(field=stato, source="DA_CLASSIFICARE", target="CLASSIFICATA")
    def classifica(self, stato_sms): ...
        # se SMS_SI -> trigger invio mail cliente (azione separata, manuale via bottone)

    @transition(field=stato, source="CLASSIFICATA", target="PLAN_DEFINITO")
    def definisci_plan(self, incaricato, controllore, data_limite_esecuzione, data_limite_controllo): ...

    @transition(field=stato, source="PLAN_DEFINITO", target="DO_IN_CORSO")
    def avvia_do(self): ...

    @transition(field=stato, source="DO_IN_CORSO", target="DO_COMPLETATO")
    def completa_do(self): ...
        # regola: request.user deve essere self.incaricato (enforce lato view/permission, non lato FSM)

    @transition(field=stato, source="DO_COMPLETATO", target="DO_IN_CORSO",
                conditions=[lambda self: self.esito_do == "NO"])
    def do_da_rifare(self): ...
        # nuova data_limite_esecuzione richiesta in input, mail incaricato

    @transition(field=stato, source="DO_COMPLETATO", target="CHECK_IN_CORSO",
                conditions=[lambda self: self.esito_do == "SI"])
    def avvia_check(self): ...

    @transition(field=stato, source="CHECK_IN_CORSO", target="DO_IN_CORSO",
                conditions=[lambda self: self.esito_check == "NEGATIVO"])
    def check_negativo(self): ...

    @transition(field=stato, source="CHECK_IN_CORSO", target="CHECK_IN_CORSO",
                conditions=[lambda self: self.esito_check == "RINVIATO"])
    def check_rinviato(self, nuova_data_limite_controllo): ...
        # self-loop: richiede nuova data_limite_controllo, nessuna mail di chiusura, solo notifica di rinvio

    @transition(field=stato, source="CHECK_IN_CORSO", target="CHECK_COMPLETATO",
                conditions=[lambda self: self.esito_check == "POSITIVO"])
    def check_positivo(self): ...

    @transition(field=stato, source="CHECK_COMPLETATO", target="ACT_INSERITO",
                conditions=[lambda self: self.vuoi_inserire_act])
    def inserisci_act(self): ...

    @transition(field=stato, source=["CHECK_COMPLETATO", "ACT_INSERITO"], target="CHIUSA")
    def chiudi(self): ...
```

**Regola compilatore≠controllore (punto 6.4/§4 analisi):** enforced come `clean()`/validator sul modello, non nella FSM: `incaricato != controllore`, con eccezione loggata se qualcuno prova a bypassare (utile in audit ISO 27001).

---

## 3. Notifiche (django-q2)

Task schedulato giornaliero `check_scadenze_suggestion_corner`:

1. Per ogni record con `data_limite_esecuzione`/`data_limite_controllo` a **30/15/5 giorni** dalla scadenza e non ancora sollecitato per quella soglia → invia mail incaricato/controllore + flag `sollecito_*` a True.
2. Per ogni record **scaduto da più di `giorni_escalation_oltre_scadenza`** (config, default 7) e non ancora "escalation_inviata" → mail a `email_responsabile_escalation` (nuovo, punto 6.3) + flag.
3. Notifiche in-app (punto 6.7): stessa logica dei task PLAN/DO/CHECK assegnati, popolano un modello `Notifica` generico se già esiste in HUB (verificare — probabile riuso da altre app tipo `gestione_specifiche`), altrimenti nuovo modello leggero `SuggestionCornerNotificaInApp`.

Email esistenti da riprodurre 1:1 (dalla procedura): notifica nuova segnalazione a SMS Team, notifica cliente (SMS_SI), notifica incarico PLAN, notifica DO completato, notifica esito CHECK positivo/negativo, notifica ACT inserito.

---

## 4. ACL v2

| Gruppo | Permessi |
|---|---|
| `SMS_TEAM` (nuovo gruppo, membri configurabili da admin) | Vede tutte le segnalazioni, classifica SMS_SI/NO, definisce PLAN, può inserire ACT, invia mail cliente |
| Utenti normali autenticati | Vedono solo le proprie segnalazioni create (se non anonime) + eventuali incarichi DO/CHECK assegnati a loro |
| Pubblico (form anonimo) | Solo `POST` di creazione, nessun accesso in lettura |

View "Segnalazioni da gestire" e "Segnalazioni che riguardano SMS" (viste negli screenshot) → querysets filtrati, non permessi separati.

---

## 5. Form pubblico anonimo (sostituisce Microsoft Forms — punto 5.1)

- Route dedicata fuori dal middleware ACL standard, es. `/suggestion-corner/nuova/` — **nessun login richiesto**.
- Rate limiting per IP (es. `django-ratelimit`, già eventualmente in uso altrove nel progetto — verificare) per mitigare spam/abuso.
- Honeypot field anti-bot (campo nascosto via CSS, se compilato la request viene silenziosamente scartata).
- Campo reparto come select (no free text, per popolare correttamente la FK fin da subito — miglioria rispetto al CSV storico che aveva reparti a testo libero disomogenei).
- Campo opzionale "vuoi restare anonimo?" → se sì, `anonima=True` e nessun collegamento a `created_by`, coerente con la tutela dati descritta nei poster S_Corner.
- Al submit: crea record in stato `INSERITA`, poi transizione automatica a `DA_CLASSIFICARE` + mail SMS Team.
- QR code generato dinamicamente (o statico, puntando alla route) — puoi rigenerarlo con lo stesso stile grafico del poster esistente.

**Nota sicurezza:** questa è l'unica superficie pubblica non autenticata del portale. Va isolata a livello di IIS (site/application separata o path escluso da regole SSO) e trattata nell'audit di sicurezza in corso come nuovo perimetro da monitorare.

**Nota dati reali (§7.0):** nei 55 record storici analizzati, `Autore` non è mai vuoto — l'invio anonimo dichiarato nella procedura non risulta mai stato usato in pratica finora. Non cambia la decisione presa (pagina pubblica non-ACL, confermata da Brizio), ma vale la pena verificare a runtime, dopo il go-live, l'effettivo utilizzo dell'opzione anonima per capire se lo sforzo di isolamento è giustificato dal volume reale.

---

## 6. AI copilot (punto 6.1/6.2 — riuso `ai_assistant/services.py`)

1. **Suggerimento classificazione SMS_SI/NO**: al momento della classificazione da parte di SMS Team, il copilot propone una classificazione basata sul testo di `opportunity`, con motivazione breve. Umano conferma/corregge sempre (mai automatico).
2. **Bozza PLAN**: dato `opportunity` + reparto + storico simile, propone una bozza di testo PLAN modificabile.
3. **Deduplica semantica**: alla creazione (anche dal form pubblico, lato SMS Team quando gestisce), ricerca ibrida BM25+dense sulle segnalazioni esistenti (stesso reparto/processo) e segnala eventuali duplicati probabili con link diretto.

Tutto **on-premise** via Ollama, coerente con lo stack esistente (`qwen2.5:14b-instruct`).

---

## 7. Migrazione dati — piano

### 7.0 Dati reali (da export pulito via API, sostituisce le stime del primo CSV)

Il secondo export fornito da Brizio (con `ListSchema` incluso, quindi generato via Graph/PnP e non via Excel) si è parsato correttamente al 100%. Numeri reali:

- **55 record validi**, ID SharePoint da 1 a 100 con **45 ID mancanti** nel range — da chiarire con Brizio se sono cancellazioni, test, o righe escluse dalla vista esportata, prima di considerare la migrazione "completa".
- SMS: 50 `SMS_NO`, 4 `SMS_SI`, 1 ancora `Da gestire` (aperta).
- **`REPARTO PROVENIENZA SEGNALAZIONE` è realmente un campo Choice** con 14 valori codificati (`AGGIUSTAGGIO, AMMINISTRAZIONE, CN5, CNC, ESTERNO, LOGISTICA, MENSA, PRESETTING, TORNI, UFFICIO TECNICO, SALA TAGLIO, REPARTO IT, QUALITA', DIREZIONE`) — ma nei dati storici compaiono comunque valori fuori lista (`Altro`, `Generico`, `LOG`, `IT`, `MAGAZZINO`, 2 vuoti), quasi certamente residui di quando il campo era testo libero. **Serve una tabella di normalizzazione manuale in fase di migrazione**, non un mapping automatico 1:1.
- **`Reparto destinazione` ha una choice list diversa e con case diverso** da quella di provenienza (`Acquisti, Amministrazione, Controllo, Ingegneria, Logistica, Programmatori, Qualità, Ufficio Tecnico, Vendite, It`) ed è valorizzato solo in 11/55 record (44 vuoti). **Confermato da Brizio: è lo stesso concetto/modello di `Reparto provenienza`** (`anagrafica.Reparto`) — la differenza di naming/case tra le due choice list SharePoint è solo un disallineamento storico dell'export, non una distinzione concettuale. In migrazione serve comunque una tabella di normalizzazione perché i valori letterali non coincidono (`UFFICIO TECNICO` vs `Ufficio Tecnico`, `QUALITA'` vs `Qualità`, ecc.), ma puntano allo stesso `Reparto` FK.
- Incaricati distinti: 9 persone, fortemente concentrati su 2 (`m.barbato`, `s.giani` = 34/55 incarichi). Controllori: 7 persone, stessa concentrazione.
- **`Vuoi inserire l'ACT?` è sempre `Falso` in tutti i 55 record storici** — il ramo ACT/loop non è mai stato usato in pratica. Resta nell'MVP per fedeltà alla procedura, ma è a bassissima priorità reale: se serve tagliare scope in corsa, è il primo candidato.
- **Nessun record ha `Autore` vuoto** — nello storico non risulta mai stata usata realmente la modalità anonima, nonostante sia dichiarata nella procedura/poster. Da chiedere a Brizio se l'anonimato è un requisito vivo o solo teorico: se è vivo, il form pubblico (§5) resta necessario così com'è; se è solo teorico, si potrebbe semplificare a "autenticato ma senza esporre il nome all'incaricato", riducendo la superficie di rischio del §5.1.
- Allegati reali: solo 4/55, di cui 3 sono lo stesso path di rete storico (`\\novisrv\Area Qualità\SMS_Suggestion Corner\2024`, non migrabile come file) e 1 è un link SharePoint valido. Volume di migrazione allegati basso, gestibile a mano.
- **Confermato da Brizio: i 45 ID mancanti nel range 1-100 sono cancellazioni reali** (non righe di test o filtri di vista). La migrazione riparte quindi in modo pulito dai 55 record esistenti, nessuna ricostruzione necessaria dei gap.

### 7.1 Fonte CSV

**Non usare il primo CSV fornito come fonte** (problemi di quoting verificati — solo 42/~100+ record ricostruibili con parsing tollerante). Usare il secondo export (via Graph/PnP, schema incluso) come riferimento di formato per il ri-export definitivo al momento della migrazione vera e propria — a ridosso del go-live, per avere il dataset più aggiornato possibile.

### 7.2 Script di import

Django management command `import_suggestion_corner_legacy`:

1. Mappa `legacy_sharepoint_id` = ID SharePoint.
2. Reparto (provenienza e destinazione) → **stessa FK `anagrafica.Reparto`** (confermato: sono concettualmente lo stesso dato). Serve comunque una tabella di normalizzazione manuale per allineare i due naming disallineati della choice list SharePoint (`UFFICIO TECNICO`/`Ufficio Tecnico`, `QUALITA'`/`Qualità`, ecc.) e i valori fuori-lista storici (`Altro`, `Generico`, `LOG`, `IT`, `MAGAZZINO`). Log dei match falliti per revisione manuale.
3. Persone (Incaricato/Controllore/Autore) → match su `User` via indirizzo email (il nuovo export usa email dirette, es. `m.barbato@costruzioninovicrom.it` — molto più affidabile del nome libero del primo CSV). Log dei non trovati.
4. `EsitoCheck = "Rinviato"` → gestito esplicitamente come stato valido (§1.1/§2), non scartato o forzato a Negativo/Positivo.
5. Allegati con path di rete (`\\novisrv\...`) → salvati come `link_esterno` testuale, non come file migrati automaticamente (solo 4 record coinvolti, recupero manuale se necessario).
6. `da_portale=False` per tutti i record migrati.
7. Nessuna transizione FSM rieseguita in migrazione: lo stato finale viene assegnato direttamente in base ai campi P/D/C/A e agli esiti, senza rigenerare lo storico completo (lo storico pre-migrazione non è ricostruibile con precisione — `SuggestionCornerStorico` parte con una singola voce "Importato da SharePoint il [data]" per record migrato).
8. Dataset di partenza: 55 record (ID mancanti = cancellazioni reali, confermato — nessuna ricostruzione necessaria).

### 7.3 Dry-run e go-live

- Dry-run con report di validazione (quante righe, quanti match falliti su reparti/persone) **prima** di scrivere in produzione.
- Le righe aggiunte su PowerApps tra oggi e il go-live → caricamento manuale a cura di Brizio, stesso script ma eseguibile più volte in modalità incrementale (skip se `legacy_sharepoint_id` già presente).

---

## 8. Dashboard KPI (punto 6.5 — dati veritieri, no placeholder)

Vista card cliccabili stile Anagrafica HR (#12395f/#1f5c91):
- Segnalazioni aperte per reparto (query reale su dati esistenti)
- Tempo medio ciclo PDCA (calcolato da `created_at` a transizione `CHIUSA`, solo su record con date complete)
- Tasso di generazione ACT (% segnalazioni con `vuoi_inserire_act=True`)
- Trend mensile (conteggio per mese di `data_segnalazione`)
- Segnalazioni scadute (DO/CHECK) — calcolate dalle property, non da colonne cache

Se in fase di sviluppo non ci sono ancora dati migrati, la dashboard mostra stato vuoto onesto ("Nessun dato disponibile"), mai numeri finti.

---

## 9. Ordine di sviluppo consigliato (sessioni Claude Code separate, sequenziali)

1. Modelli + migrations + admin base (incl. `SuggestionCornerConfig`)
2. FSM + regole di validazione (incaricato≠controllore)
3. ACL v2 (gruppo `SMS_TEAM`) + viste protette (elenco, dettaglio, "da gestire", "riguarda SMS")
4. Form pubblico anonimo + rate limiting
5. Notifiche email (django-q2) + reminder scheduler
6. Notifiche in-app
7. Audit trail (`SuggestionCornerStorico` + signal)
8. Script di migrazione + dry-run
9. AI copilot (classificazione + dedup)
10. Dashboard KPI
11. Test suite (pytest, come da standard HUB)

Ogni punto = una sessione Claude Code dedicata, `/compact` prima del lancio, nessun subagent parallelo (vedi CLAUDE.md).
