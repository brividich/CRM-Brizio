"""Test del bridge read-only ``assenze.availability`` (overlay carichi macchina).

Logica pura (varianti nome) senza DB; il match/raggruppamento è verificato
mockando l'accesso legacy (``_resolve_identities`` / ``_fetch_dict``), così non
serve creare le tabelle legacy nei test.
"""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from assenze import availability as av


class NameVariantsTests(SimpleTestCase):
    def test_entrambi_gli_ordini_normalizzati(self):
        v = av._name_variants("Mario", "Rossi")
        self.assertEqual(v, {"ROSSI MARIO", "MARIO ROSSI"})

    def test_spazi_compattati(self):
        self.assertEqual(av._norm_key("  mario   rossi "), "MARIO ROSSI")

    def test_vuoto(self):
        self.assertEqual(av._name_variants("", ""), set())


class AssenzePerAnagraficaTests(SimpleTestCase):
    IDENTITIES = {
        42: {"nome": "Mario", "cognome": "Rossi",
             "names": {"ROSSI MARIO", "MARIO ROSSI"}, "emails": {"M.ROSSI@X.IT"}},
        43: {"nome": "Luca", "cognome": "Bianchi",
             "names": {"BIANCHI LUCA", "LUCA BIANCHI"}, "emails": set()},
    }
    COLS = {"data_inizio", "data_fine", "copia_nome", "email_esterna",
            "tipo_assenza", "moderation_status", "consenso"}

    def _run(self, rows):
        with mock.patch.object(av, "_resolve_identities", return_value=self.IDENTITIES), \
             mock.patch.object(av, "legacy_table_columns", return_value=self.COLS), \
             mock.patch.object(av, "_fetch_dict", return_value=rows) as fetch:
            out = av.assenze_per_anagrafica([42, 43], date(2026, 6, 22), date(2026, 6, 28))
        return out, fetch

    def test_match_per_nome_ed_email(self):
        rows = [
            {"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 25),
             "copia_nome": "Rossi Mario", "email_esterna": "", "tipo_assenza": "Ferie",
             "moderation_status": 0, "consenso": "Approvato"},
            {"data_inizio": date(2026, 6, 26), "data_fine": date(2026, 6, 26),
             "copia_nome": "", "email_esterna": "m.rossi@x.it", "tipo_assenza": "Permesso",
             "moderation_status": 4, "consenso": "Programmato"},
        ]
        out, _ = self._run(rows)
        self.assertIn(42, out)
        self.assertEqual(len(out[42]), 2)
        self.assertEqual(out[42][0]["tipo"], "Ferie")
        self.assertEqual(out[42][0]["nome"], "Rossi Mario")
        # 43 non ha assenze in queste righe
        self.assertNotIn(43, out)

    def test_dedup_riga_doppia(self):
        riga = {"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 25),
                "copia_nome": "Rossi Mario", "email_esterna": "", "tipo_assenza": "Ferie",
                "moderation_status": 0, "consenso": "Approvato"}
        out, _ = self._run([riga, dict(riga)])
        self.assertEqual(len(out[42]), 1)

    def test_query_filtra_stati_confermati_e_finestra(self):
        _, fetch = self._run([])
        sql, params = fetch.call_args[0]
        self.assertIn("IN (0, 4)", sql)
        self.assertIn("'APPROVATO'", sql)
        self.assertIn("'PROGRAMMATO'", sql)
        # primi due parametri = finestra [start, end]
        self.assertEqual(params[0], date(2026, 6, 22))
        self.assertEqual(params[1], date(2026, 6, 28))

    def test_nessun_id(self):
        self.assertEqual(av.assenze_per_anagrafica([], date(2026, 6, 1), date(2026, 6, 2)), {})

    def test_finestra_invalida(self):
        self.assertEqual(
            av.assenze_per_anagrafica([42], date(2026, 6, 5), date(2026, 6, 1)), {}
        )

    def test_fail_safe_su_eccezione(self):
        with mock.patch.object(av, "_resolve_identities", side_effect=RuntimeError("boom")):
            self.assertEqual(
                av.assenze_per_anagrafica([42], date(2026, 6, 1), date(2026, 6, 2)), {}
            )


class ResolveIdentitiesTests(SimpleTestCase):
    def test_solo_email_con_chiocciola_e_varianti_nome(self):
        cols = {"id", "nome", "cognome", "email", "email_notifica"}
        rows = [{"id": 42, "nome": "Mario", "cognome": "Rossi",
                 "email": "rossim", "email_notifica": "m.rossi@x.it"}]
        with mock.patch.object(av, "legacy_table_columns", return_value=cols), \
             mock.patch.object(av, "_fetch_dict", return_value=rows):
            out = av._resolve_identities([42])
        self.assertEqual(out[42]["names"], {"ROSSI MARIO", "MARIO ROSSI"})
        # 'rossim' (username legacy senza @) scartato, resta solo l'email vera
        self.assertEqual(out[42]["emails"], {"M.ROSSI@X.IT"})
