"""Viste SQL ``bi_*`` per Power BI e altri strumenti di analisi.

Sola lettura, nessuna copia: ogni vista è una SELECT sulle tabelle dei moduli,
quindi Power BI vede i dati del portale nel momento in cui li legge.

Regole (vedi docs/moduli/dati_bi.md):

- **Niente dati personali nominativi**: niente assegnatari, richiedenti,
  dipendenti, email; niente testi liberi (descrizioni, note) che possono
  contenerne. Il personale non ha viste: solo conteggi aggregati dall'API.
- **SQL portabile** fra SQL Server (produzione) e SQLite (test): niente funzioni
  di data, niente concatenazioni. I giorni alla scadenza li calcola Power BI.
- Codici di stato come sono nel DB (es. ``OPEN``, ``CONSEGNATA``): le etichette
  sono in :data:`ETICHETTE` per chi costruisce il report.

Si creano con la migrazione ``dati_bi`` e si ricreano con
``manage.py bi_viste --applica`` (``CREATE OR ALTER`` su SQL Server). Il
permesso di lettura per l'utente SQL di Power BI: ``manage.py bi_viste --grant <login>``.
"""
from __future__ import annotations

PREFISSO = "bi_"

VISTE: dict[str, str] = {
    "bi_asset": """
SELECT
    a.id AS asset_id,
    a.asset_tag,
    a.internal_number AS numero_interno,
    a.name AS nome,
    a.asset_type AS tipo,
    c.label AS categoria,
    a.reparto,
    a.manufacturer AS costruttore,
    a.model AS modello,
    a.serial_number AS matricola,
    a.status AS stato,
    a.purchase_date AS data_acquisto,
    a.created_at AS creato_il
FROM assets_asset a
LEFT JOIN assets_assetcategory c ON c.id = a.asset_category_id
""",
    "bi_ordini_lavoro": """
SELECT
    w.id AS odl_id,
    w.asset_id,
    a.asset_tag,
    a.name AS asset_nome,
    a.reparto,
    w.kind AS tipo,
    w.priority AS priorita,
    w.status AS stato,
    w.origin AS origine,
    w.title AS titolo,
    w.opened_at AS aperto_il,
    w.started_at AS iniziato_il,
    w.closed_at AS chiuso_il,
    w.due_at AS scadenza,
    w.is_waiting AS in_attesa,
    w.wait_reason AS motivo_attesa,
    w.outcome AS esito,
    w.intervention_duration_minutes AS minuti_intervento,
    w.downtime_minutes AS minuti_fermo,
    w.labor_cost_eur AS costo_manodopera_eur,
    w.materials_cost_eur AS costo_materiali_eur,
    w.cost_eur AS costo_totale_eur,
    w.covered_by_contract AS coperto_da_contratto,
    w.supplier_id AS fornitore_id,
    f.ragione_sociale AS fornitore
FROM assets_workorder w
JOIN assets_asset a ON a.id = w.asset_id
LEFT JOIN anagrafica_fornitore f ON f.id = w.supplier_id
""",
    "bi_scadenze_asset": """
SELECT
    'amministrativa' AS fonte,
    d.id AS rif_id,
    d.title AS titolo,
    d.deadline_type AS tipo,
    d.asset_id,
    a.asset_tag,
    a.name AS asset_nome,
    a.reparto,
    a.status AS asset_stato,
    d.due_date AS scadenza,
    d.warning_days AS preavviso_giorni
FROM assets_assetadministrativedeadline d
JOIN assets_asset a ON a.id = d.asset_id
WHERE d.is_active = 1
UNION ALL
SELECT
    'licenza' AS fonte,
    l.id AS rif_id,
    l.product_name AS titolo,
    l.category AS tipo,
    l.asset_id,
    a.asset_tag,
    a.name AS asset_nome,
    CASE WHEN a.id IS NULL THEN l.assigned_reparto ELSE a.reparto END AS reparto,
    a.status AS asset_stato,
    l.expiry_date AS scadenza,
    30 AS preavviso_giorni
FROM assets_softwarelicense l
LEFT JOIN assets_asset a ON a.id = l.asset_id
WHERE l.is_active = 1 AND l.expiry_date IS NOT NULL
UNION ALL
SELECT
    'contratto' AS fonte,
    k.id AS rif_id,
    k.title AS titolo,
    k.contract_type AS tipo,
    k.asset_id,
    a.asset_tag,
    a.name AS asset_nome,
    a.reparto,
    a.status AS asset_stato,
    k.end_date AS scadenza,
    30 AS preavviso_giorni
FROM assets_assistancecontract k
LEFT JOIN assets_asset a ON a.id = k.asset_id
WHERE k.is_active = 1 AND k.end_date IS NOT NULL
UNION ALL
SELECT
    'verifica_impianto' AS fonte,
    t.id AS rif_id,
    t.name AS titolo,
    s.name AS tipo,
    s.asset_id,
    a.asset_tag,
    a.name AS asset_nome,
    a.reparto,
    a.status AS asset_stato,
    t.next_due_date AS scadenza,
    t.warning_days AS preavviso_giorni
FROM assets_periodicchecktype t
JOIN assets_periodicchecksystem s ON s.id = t.system_id
LEFT JOIN assets_asset a ON a.id = s.asset_id
WHERE t.is_active = 1 AND t.next_due_date IS NOT NULL
""",
    "bi_ticket": """
SELECT
    t.id AS ticket_id,
    t.numero_ticket,
    t.tipo,
    t.categoria,
    t.priorita,
    t.stato,
    t.incide_sicurezza,
    t.asset_id,
    a.asset_tag,
    a.reparto AS reparto_asset,
    t.tipo_fermo,
    t.ore_fermo_macchina,
    t.ricorrente,
    t.created_at AS aperto_il,
    t.data_presa_in_carico AS preso_in_carico_il,
    t.data_primo_intervento AS primo_intervento_il,
    t.closed_at AS chiuso_il,
    t.data_prevista_risoluzione AS risoluzione_prevista
FROM tickets_ticket t
LEFT JOIN assets_asset a ON a.id = t.asset_id
""",
    "bi_dpi_consegne": """
SELECT
    c.id AS consegna_id,
    r.numero AS richiesta,
    r.stato AS stato_richiesta,
    cat.nome AS categoria,
    r.richiedente_reparto AS reparto,
    r.quantita,
    c.data_consegna,
    c.data_scadenza_stimata AS scadenza_stimata,
    CASE WHEN c.sostituita_da_id IS NULL THEN 1 ELSE 0 END AS in_essere,
    c.data_sostituzione,
    c.firmato_ricevuta
FROM dpi_consegnadpi c
JOIN dpi_richiestadpi r ON r.id = c.richiesta_id
LEFT JOIN dpi_categoriadpi cat ON cat.id = r.categoria_id
""",
    "bi_capa": """
SELECT
    x.id AS capa_id,
    x.tipo,
    x.stato,
    x.source_code AS origine,
    x.reparto,
    x.data_scadenza AS scadenza,
    x.created_at AS aperta_il,
    x.data_chiusura AS chiusa_il,
    x.data_verifica AS verificata_il
FROM core_actionitem x
""",
}

# Etichette dei codici più usati nei filtri dei report (non esaustive).
ETICHETTE: dict[str, dict[str, str]] = {
    "bi_scadenze_asset.fonte": {
        "amministrativa": "Scadenza amministrativa",
        "licenza": "Licenza software",
        "contratto": "Contratto di assistenza",
        "verifica_impianto": "Verifica impianto",
    },
    "bi_dpi_consegne.in_essere": {"1": "Consegna in essere", "0": "Sostituita da una consegna successiva"},
}


def _is_sqlserver(vendor: str) -> bool:
    return vendor in ("microsoft", "mssql", "sql_server")


def statements_crea(vendor: str) -> list[str]:
    """Istruzioni per creare/aggiornare tutte le viste sul database ``vendor``."""
    out: list[str] = []
    for nome, sql in VISTE.items():
        body = sql.strip()
        if _is_sqlserver(vendor):
            out.append(f"CREATE OR ALTER VIEW {nome} AS\n{body}")
        else:
            out.append(f"DROP VIEW IF EXISTS {nome}")
            out.append(f"CREATE VIEW {nome} AS\n{body}")
    return out


def statements_elimina(vendor: str) -> list[str]:
    return [f"DROP VIEW IF EXISTS {nome}" for nome in VISTE]


def statements_grant(login: str) -> list[str]:
    """T-SQL per l'utente in sola lettura di Power BI (da far eseguire al DBA)."""
    login = str(login or "").strip()
    if not login or not all(ch.isalnum() or ch in "_-.\\" for ch in login):
        raise ValueError("Nome login non valido.")
    return [f"GRANT SELECT ON {nome} TO [{login}]" for nome in VISTE]


def crea_viste(connection) -> int:
    with connection.cursor() as cursor:
        for stmt in statements_crea(connection.vendor):
            cursor.execute(stmt)
    return len(VISTE)


def elimina_viste(connection) -> None:
    with connection.cursor() as cursor:
        for stmt in statements_elimina(connection.vendor):
            cursor.execute(stmt)
