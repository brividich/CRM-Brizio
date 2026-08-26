"""Test della barriera di sola lettura usata da `config.settings.prod_readonly`."""

from __future__ import annotations

from django.test import SimpleTestCase

from config.readonly_guard import (
    ReadOnlyRouter,
    ReadOnlyViolation,
    is_write_statement,
    reject_writes,
)


class IsWriteStatementTests(SimpleTestCase):
    def test_letture_consentite(self):
        for sql in (
            "SELECT 1",
            "  select count(*) from assenze ",
            "SELECT * FROM assenze WHERE copia_nome = 'DELETE ME'",
            "WITH ultime AS (SELECT TOP 5 id FROM assenze) SELECT * FROM ultime",
            "SET NOCOUNT ON",
        ):
            with self.subTest(sql=sql):
                self.assertFalse(is_write_statement(sql))

    def test_scritture_bloccate(self):
        for sql in (
            "INSERT INTO assenze (copia_nome) VALUES ('X')",
            "insert into assenze (copia_nome) values ('X')",
            "UPDATE assenze SET consenso = 'Approvato'",
            "DELETE FROM assenze",
            "MERGE assenze AS t USING altro AS s ON t.id = s.id",
            "TRUNCATE TABLE assenze",
            "DROP TABLE assenze",
            "ALTER TABLE assenze ADD col INT",
            "CREATE TABLE tmp (id INT)",
            "GRANT SELECT ON assenze TO qualcuno",
            "REVOKE SELECT ON assenze FROM qualcuno",
            "WITH nuove AS (SELECT 1 AS id) INSERT INTO assenze (id) SELECT id FROM nuove",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(is_write_statement(sql))

    def test_sql_vuoto_non_e_scrittura(self):
        self.assertFalse(is_write_statement(None))
        self.assertFalse(is_write_statement(""))


class RejectWritesTests(SimpleTestCase):
    def test_la_lettura_passa_al_livello_sottostante(self):
        chiamate = []

        def execute(sql, params, many, context):
            chiamate.append(sql)
            return "risultato"

        esito = reject_writes(execute, "SELECT 1", None, False, {})

        self.assertEqual(esito, "risultato")
        self.assertEqual(chiamate, ["SELECT 1"])

    def test_la_scrittura_non_arriva_al_database(self):
        def execute(sql, params, many, context):  # pragma: no cover - non deve essere chiamata
            raise AssertionError("la query non doveva partire")

        with self.assertRaises(ReadOnlyViolation) as ctx:
            reject_writes(execute, "DELETE FROM assenze WHERE id = 1", None, False, {})

        self.assertIn("DELETE FROM assenze", str(ctx.exception))


class ReadOnlyRouterTests(SimpleTestCase):
    def test_nessuna_migrazione_consentita(self):
        router = ReadOnlyRouter()
        self.assertFalse(router.allow_migrate("default", "assenze"))
        self.assertFalse(router.allow_migrate("default", "core", model_name="Profile"))
