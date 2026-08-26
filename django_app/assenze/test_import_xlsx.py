"""Test del comando ``import_assenze_xlsx``."""

from __future__ import annotations

import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase

from core.legacy_utils import legacy_table_columns

HEADER = [
    "Data inizio",
    "Data fine",
    "Nome Cognome",
    "Tipoassenza",
    "Nome",
    "Ricercanome",
    "Stato approvazione",
    "Tipo di elemento",
    "Percorso",
]


def _ensure_assenze_table() -> None:
    """Crea la tabella legacy ``assenze`` (sola SQLite: profilo di test)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS assenze (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sharepoint_item_id VARCHAR(64) NULL,
                copia_nome VARCHAR(200) NULL,
                email_esterna VARCHAR(200) NULL,
                tipo_assenza VARCHAR(100) NULL,
                data_inizio DATETIME NULL,
                data_fine DATETIME NULL,
                motivazione_richiesta VARCHAR(500) NULL,
                consenso VARCHAR(100) NULL,
                moderation_status INTEGER NULL
            )
            """
        )
        cursor.execute("DELETE FROM assenze")
    # Lo schema legacy e' dietro lru_cache: senza reset la tabella creata qui
    # resta "visibile" ai test successivi anche dopo il rollback.
    legacy_table_columns.cache_clear()


def _row(nome, inizio, fine, tipo="Ferie", stato="Approvato"):
    return [inizio, fine, nome, tipo, nome, None, stato, "Elemento", "Lists/Calendario assenze 2"]


class ImportAssenzeXlsxTests(TestCase):
    def setUp(self):
        _ensure_assenze_table()
        self.addCleanup(legacy_table_columns.cache_clear)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    # -- helper ------------------------------------------------------------

    def _make_xlsx(self, rows, *, header=None, name="assenze.xlsx") -> str:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "query (3)"
        ws.append(list(header if header is not None else HEADER))
        for row in rows:
            ws.append(list(row))
        path = Path(self._tmp.name) / name
        wb.save(path)
        return str(path)

    def _run(self, path, **kwargs):
        out = StringIO()
        call_command("import_assenze_xlsx", path, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def _fetch(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, copia_nome, tipo_assenza, data_inizio, data_fine, consenso, "
                "moderation_status, sharepoint_item_id FROM assenze ORDER BY id"
            )
            cols = [c[0] for c in cursor.description]
            return [dict(zip(cols, r)) for r in cursor.fetchall()]

    # -- test --------------------------------------------------------------

    def test_inserisce_le_righe_nuove(self):
        path = self._make_xlsx(
            [
                _row("PASQUINUCCI ANDREA", datetime(2026, 7, 17), datetime(2026, 7, 27, 23, 59)),
                _row("CARLOTTI MIRKO", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ]
        )
        output = self._run(path)

        rows = self._fetch()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["copia_nome"], "PASQUINUCCI ANDREA")
        self.assertEqual(rows[0]["tipo_assenza"], "Ferie")
        self.assertEqual(rows[0]["consenso"], "Approvato")
        self.assertEqual(rows[0]["moderation_status"], 0)
        self.assertIn("create                     2", output)

    def test_seconda_esecuzione_non_duplica(self):
        path = self._make_xlsx(
            [
                _row("PASQUINUCCI ANDREA", datetime(2026, 7, 17), datetime(2026, 7, 27, 23, 59)),
                _row("CARLOTTI MIRKO", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ]
        )
        self._run(path)
        output = self._run(path)

        self.assertEqual(len(self._fetch()), 2)
        self.assertIn("create                     0", output)
        self.assertIn("aggiornate                 0", output)
        self.assertIn("invariate                  2", output)

    def test_aggiorna_solo_la_riga_cambiata(self):
        first = self._make_xlsx(
            [
                _row("PASQUINUCCI ANDREA", datetime(2026, 7, 17), datetime(2026, 7, 27, 23, 59), stato="In attesa"),
                _row("CARLOTTI MIRKO", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ]
        )
        self._run(first)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE assenze SET sharepoint_item_id = '4321' WHERE copia_nome = %s", ["PASQUINUCCI ANDREA"])

        second = self._make_xlsx(
            [
                _row("PASQUINUCCI ANDREA", datetime(2026, 7, 17), datetime(2026, 7, 27, 23, 59), stato="Approvato"),
                _row("CARLOTTI MIRKO", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ],
            name="assenze2.xlsx",
        )
        output = self._run(second)

        rows = self._fetch()
        self.assertEqual(len(rows), 2)
        aggiornata = next(r for r in rows if r["copia_nome"] == "PASQUINUCCI ANDREA")
        self.assertEqual(aggiornata["consenso"], "Approvato")
        self.assertEqual(aggiornata["moderation_status"], 0)
        # L'update non tocca il legame con SharePoint
        self.assertEqual(aggiornata["sharepoint_item_id"], "4321")
        self.assertIn("aggiornate                 1", output)
        self.assertIn("invariate                  1", output)

    def test_cambio_orario_nello_stesso_giorno_e_un_aggiornamento(self):
        first = self._make_xlsx(
            [_row("MARINI MATTEO", datetime(2026, 7, 22, 8, 0), datetime(2026, 7, 22, 12, 0), tipo="Permesso")]
        )
        self._run(first)
        second = self._make_xlsx(
            [_row("MARINI MATTEO", datetime(2026, 7, 22, 9, 0), datetime(2026, 7, 22, 13, 0), tipo="Permesso")],
            name="assenze2.xlsx",
        )
        output = self._run(second)

        rows = self._fetch()
        self.assertEqual(len(rows), 1)
        self.assertIn("aggiornate                 1", output)
        self.assertIn("create                     0", output)

    def test_nome_con_spaziatura_diversa_non_duplica(self):
        self._run(
            self._make_xlsx([_row("ROSSI  MARIO", datetime(2026, 9, 1), datetime(2026, 9, 5, 23, 59))])
        )
        output = self._run(
            self._make_xlsx(
                [_row("rossi mario", datetime(2026, 9, 1), datetime(2026, 9, 5, 23, 59))],
                name="assenze2.xlsx",
            )
        )

        self.assertEqual(len(self._fetch()), 1)
        self.assertIn("invariate                  1", output)

    def test_dry_run_non_scrive(self):
        path = self._make_xlsx([_row("SANGARI GIUSEPPE", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59))])
        output = self._run(path, dry_run=True)

        self.assertEqual(self._fetch(), [])
        self.assertIn("create                     1", output)
        self.assertIn("DRY-RUN", output)

    def test_righe_incomplete_sono_saltate(self):
        path = self._make_xlsx(
            [
                _row("", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
                _row("BIANCHI LUCA", None, datetime(2026, 8, 28, 23, 59)),
                _row("BIANCHI LUCA", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ]
        )
        output = self._run(path)

        self.assertEqual(len(self._fetch()), 1)
        self.assertIn("saltate_dati_mancanti      1", output)
        self.assertIn("saltate_date_non_valide    1", output)

    def test_header_incompleto_fallisce(self):
        path = self._make_xlsx([["2026-08-24", "x"]], header=["Data inizio", "Qualcosa"])
        with self.assertRaises(CommandError):
            self._run(path)

    def test_limit_ferma_la_lettura(self):
        path = self._make_xlsx(
            [
                _row("PRIMO NOME", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
                _row("SECONDO NOME", datetime(2026, 8, 24), datetime(2026, 8, 28, 23, 59)),
            ]
        )
        self._run(path, limit=1)
        self.assertEqual(len(self._fetch()), 1)


class ImportAssenzeVincoloLegacyTests(TestCase):
    """Una riga rifiutata dal DB non deve far fallire tutto l'import."""

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS assenze")
            cursor.execute(
                """
                CREATE TABLE assenze (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sharepoint_item_id VARCHAR(64) NULL,
                    copia_nome VARCHAR(200) NULL,
                    tipo_assenza VARCHAR(100) NULL
                        CHECK (tipo_assenza IN ('Ferie', 'Permesso', 'Malattia', 'Infortunio', 'Altro')),
                    data_inizio DATETIME NULL,
                    data_fine DATETIME NULL,
                    consenso VARCHAR(100) NULL,
                    moderation_status INTEGER NULL
                )
                """
            )
        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_riga_rifiutata_non_blocca_le_altre(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(list(HEADER))
        ws.append(_row("ROSSI MARIO", datetime(2026, 7, 1), datetime(2026, 7, 4, 23, 59)))
        # 'Flessibilita'' non e' ammesso dal vincolo legacy di questa tabella
        ws.append(
            _row("VERDI ANNA", datetime(2026, 7, 2, 6, 0), datetime(2026, 7, 2, 16, 0), tipo="Flessibilità")
        )
        ws.append(_row("BIANCHI LUCA", datetime(2026, 7, 3, 8, 0), datetime(2026, 7, 3, 12, 0), tipo="Permesso"))
        path = Path(self._tmp.name) / "assenze.xlsx"
        wb.save(path)

        out = StringIO()
        call_command("import_assenze_xlsx", str(path), stdout=out, stderr=out)
        output = out.getvalue()

        with connection.cursor() as cursor:
            cursor.execute("SELECT copia_nome FROM assenze ORDER BY id")
            nomi = [r[0] for r in cursor.fetchall()]

        self.assertEqual(nomi, ["ROSSI MARIO", "BIANCHI LUCA"])
        self.assertIn("create                     2", output)
        self.assertIn("errori                     1", output)
