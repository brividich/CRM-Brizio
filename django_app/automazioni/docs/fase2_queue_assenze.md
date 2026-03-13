# Fase 2: queue SQL Server per `assenze`

Questa fase introduce solo l'infrastruttura dati minima per accodare eventi `INSERT` e `UPDATE` dalla tabella `dbo.assenze` alla tabella tecnica `dbo.automation_event_queue`.

## Strategia payload

La queue usa principalmente i nomi DB reali della tabella `dbo.assenze` e aggiunge solo gli alias runtime strettamente utili alle automazioni (`dipendente_email`, `capo_email`):

- `id`
- `dipendente_id`
- `data_inizio`
- `data_fine`
- `tipo_assenza`
- `motivazione_richiesta`
- `moderation_status`
- `capo_reparto_id`
- `dipendente_email`
- `salta_approvazione`
- `capo_email`

Non vengono introdotti alias applicativi aggiuntivi come `utente_id` o `motivazione`.

## Vincoli operativi fissati

- I trigger sono interamente set-based e compatibili con `INSERT` e `UPDATE` multi-riga.
- Non vengono fatte assunzioni single-row su `inserted` o `deleted`.
- Se `dbo.automation_event_queue` esiste gia', questa fase non applica alter distruttivi.
- Gli `event_code` restano tecnici e stabili: `assenze_insert` e `assenze_update`.
- Le date nel payload JSON restano serializzate dal motore JSON nativo di SQL Server, senza conversioni custom.

## Artefatti SQL

Applicare gli script in questo ordine:

1. `sql/automation_event_queue.sql`
2. `sql/trg_assenze_automation_after_insert.sql`
3. `sql/trg_assenze_automation_after_update.sql`

La tabella `dbo.automation_event_queue` usa questi valori iniziali:

- `source_code = 'assenze'`
- `source_table = 'assenze'`
- `operation_type = 'INSERT' | 'UPDATE'`
- `event_code = 'assenze_insert' | 'assenze_update'`
- `status = 'pending'`
- `watched_field = NULL`

In questa fase `watched_field` resta sempre `NULL`. Il confronto puntuale tra `payload_json` e `old_payload_json` verra' gestito lato Django nelle fasi successive.

## Shape del payload JSON

```json
{
  "id": 123,
  "dipendente_id": 45,
  "data_inizio": "2026-03-11T08:00:00",
  "data_fine": "2026-03-11T17:00:00",
  "tipo_assenza": "Permesso",
  "motivazione_richiesta": "Visita medica",
  "moderation_status": 2,
  "capo_reparto_id": 7,
  "dipendente_email": "mario.rossi@example.com",
  "salta_approvazione": false,
  "capo_email": "responsabile@example.com"
}
```

## Verifica manuale

### 1. Creazione tabella queue

```sql
:r sql/automation_event_queue.sql
```

### 2. Creazione trigger

```sql
:r sql/trg_assenze_automation_after_insert.sql
:r sql/trg_assenze_automation_after_update.sql
```

### 3. Insert di test su `assenze`

Usa ID FK esistenti nel database attivo:

```sql
DECLARE @dipendente_id INT = (
    SELECT TOP (1) id
    FROM dbo.dipendenti
    ORDER BY id
);

DECLARE @capo_reparto_id INT = (
    SELECT TOP (1) id
    FROM dbo.capi_reparto
    ORDER BY id
);

IF @dipendente_id IS NULL OR @capo_reparto_id IS NULL
BEGIN
    THROW 50001, 'Mancano record validi in dbo.dipendenti o dbo.capi_reparto per il test.', 1;
END;

INSERT INTO dbo.assenze (
    dipendente_id,
    capo_reparto_id,
    tipo_assenza,
    data_inizio,
    data_fine,
    motivazione_richiesta,
    moderation_status
)
VALUES (
    @dipendente_id,
    @capo_reparto_id,
    N'Permesso',
    '2026-03-11T08:00:00',
    '2026-03-11T12:00:00',
    N'Test queue automazioni fase 2',
    2
);

DECLARE @assenza_id INT = CAST(SCOPE_IDENTITY() AS INT);

SELECT @assenza_id AS assenza_id_creata;
```

### 4. Controllo queue dopo `INSERT`

```sql
SELECT TOP (20)
    id,
    source_code,
    source_table,
    source_pk,
    operation_type,
    event_code,
    status,
    payload_json,
    old_payload_json,
    created_at
FROM dbo.automation_event_queue
ORDER BY id DESC;
```

### 5. Update di test sulla stessa riga

Sostituisci `@assenza_id` con l'ID restituito dall'insert precedente se stai eseguendo gli script in sessioni separate.

```sql
UPDATE dbo.assenze
SET
    moderation_status = 1,
    motivazione_richiesta = N'Test queue automazioni fase 2 - update'
WHERE id = @assenza_id;
```

### 6. Controllo queue dopo `UPDATE`

```sql
SELECT
    id,
    source_code,
    operation_type,
    status,
    payload_json,
    old_payload_json
FROM dbo.automation_event_queue
ORDER BY id DESC;
```

Atteso:

- una riga `INSERT` con `old_payload_json = NULL`
- una riga `UPDATE` con `old_payload_json` valorizzato
- entrambe con `status = 'pending'`

## Fuori scope in questa fase

- worker Django
- modelli ORM per la queue
- retry applicativi
- regole automazione
- action executors
- trigger su altre tabelle business
