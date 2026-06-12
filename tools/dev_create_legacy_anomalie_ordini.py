"""
DEV-ONLY: ricrea le tabelle legacy `ordini_produzione` e `anomalie` nel DB di
sviluppo quando sono assenti (es. droppate da un sync esterno) e inserisce
qualche OP di prova SINTETICO per poter testare il wizard di nuova segnalazione.

Schema derivato dalle query reali in anomalie/views.py (INSERT/SELECT) e dai
mock in anomalie/tests.py. NON usare in test/prod: quelle tabelle sono
popolate dal gestionale di produzione.

Uso:
    .venv\\Scripts\\python.exe django_app\\manage.py shell \
        --settings=config.settings.dev \
        -c "exec(open(r'tools/dev_create_legacy_anomalie_ordini.py', encoding='utf-8').read())"
"""
from django.conf import settings
from django.db import connections

conn = connections["default"]
if conn.vendor != "microsoft":
    raise SystemExit(f"Atteso SQL Server, trovato vendor={conn.vendor}; abort.")

db_name = conn.settings_dict.get("NAME")
# Guard-rail: NON eseguire mai su un DB che sembra prod/test.
lowered = str(db_name or "").lower()
if "prod" in lowered or lowered.startswith("test_") or "_test" in lowered:
    raise SystemExit(f"DB '{db_name}' sembra prod/test: script DEV-ONLY, abort.")

print(f"DB target: {db_name} (vendor={conn.vendor})")

DDL_ORDINI = """
IF OBJECT_ID(N'dbo.ordini_produzione', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ordini_produzione (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        sharepoint_item_id NVARCHAR(100) NULL,
        title             NVARCHAR(100) NULL,
        part_number       NVARCHAR(200) NULL,
        in1text           NVARCHAR(255) NULL,
        incaricato        NVARCHAR(255) NULL,
        capocomessa       NVARCHAR(255) NULL,
        stato             NVARCHAR(50)  NULL,
        created_by        NVARCHAR(255) NULL,
        modified_by       NVARCHAR(255) NULL,
        created_datetime  DATETIME2     NULL,
        modified_datetime DATETIME2     NULL
    );
END
"""

DDL_ANOMALIE = """
IF OBJECT_ID(N'dbo.anomalie', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.anomalie (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        sharepoint_item_id  NVARCHAR(100) NULL,
        op_lookup_id        INT           NULL,
        ex_op_nominativo    NVARCHAR(100) NULL,
        seriale             NVARCHAR(200) NULL,
        descrizione         NVARCHAR(MAX) NULL,
        note_capocommessa   NVARCHAR(MAX) NULL,
        pezzo_recuperato    INT           NULL DEFAULT 0,
        aprire_rdc          INT           NULL DEFAULT 0,
        segnalare_cliente   INT           NULL DEFAULT 0,
        chiudere            INT           NULL DEFAULT 0,
        avanzamento         NVARCHAR(100) NULL,
        numero_rdc          NVARCHAR(100) NULL,
        created_by_user_id  INT           NULL,
        modified_by_user_id INT           NULL,
        created_datetime    DATETIME2     NULL,
        modified_datetime   DATETIME2     NULL
    );
END
"""

SEED_ORDINI = """
IF NOT EXISTS (SELECT 1 FROM dbo.ordini_produzione)
BEGIN
    INSERT INTO dbo.ordini_produzione
        (sharepoint_item_id, title, part_number, in1text, incaricato, capocomessa, stato, created_by, modified_by, created_datetime, modified_datetime)
    VALUES
        (N'9001', N'OP/2026/0001', N'PN-AAA-001', N'OP di prova', N'Mario Rossi',  N'Luca Bianchi', N'Aperto',     N'seed-dev', N'seed-dev', SYSUTCDATETIME(), SYSUTCDATETIME()),
        (N'9002', N'OP/2026/0002', N'PN-BBB-002', N'OP di prova', N'Anna Verdi',   N'Luca Bianchi', N'Aperto',     N'seed-dev', N'seed-dev', SYSUTCDATETIME(), SYSUTCDATETIME()),
        (N'9003', N'OP/2026/0003', N'PN-CCC-003', N'OP benestare',N'Paolo Neri',   N'Sara Gialli',  N'Benestare',  N'seed-dev', N'seed-dev', SYSUTCDATETIME(), SYSUTCDATETIME());
END
"""

with conn.cursor() as cur:
    cur.execute(DDL_ORDINI)
    print("ordini_produzione: OK (creata se mancante)")
    cur.execute(DDL_ANOMALIE)
    print("anomalie: OK (creata se mancante)")
    cur.execute(SEED_ORDINI)
    print("seed OP di prova: OK (inserito se tabella vuota)")

    cur.execute("SELECT COUNT(*) FROM dbo.ordini_produzione")
    print("ordini_produzione righe:", cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM dbo.anomalie")
    print("anomalie righe:", cur.fetchone()[0])

print("FATTO.")
