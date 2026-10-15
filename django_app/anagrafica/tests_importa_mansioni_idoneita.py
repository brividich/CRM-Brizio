"""Import della mansione dall'elenco idoneità (comando ``importa_mansioni_idoneita``).

Dati sintetici: CF e nominativi inventati, nessun dato reale.
"""
from __future__ import annotations

import datetime
import io
import os
import tempfile

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .management.commands.importa_mansioni_idoneita import normalizza, scomponi
from .models import (
    DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile, DipendenteAssegnazione,
    DipendenteCambiamentoOrganizzativo, Mansione,
)
from .tests import _ensure_anagrafica_table

CATALOGO = {normalizza(n): n for n in (
    "ADDETTO MACCHINE UTENSILI", "ADDETTO AGGIUSTAGGIO", "ADDETTO RITOCCHI",
    "ADDETTO MAGAZZINO", "ADDETTO MANUTENZIONE", "ADDETTO LAVAGGIO", "ADDETTO VERNICIATURA",
)}


class ScomponiTests(SimpleTestCase):
    def test_mansione_esatta(self):
        self.assertEqual(scomponi("ADDETTO MACCHINE UTENSILI", CATALOGO),
                         ("ADDETTO MACCHINE UTENSILI", [], []))

    def test_rischi_in_coda_restano_fuori_dalla_mansione(self):
        base, rischi, residui = scomponi("ADDETTO MACCHINE UTENSILI, CARRELLO E LAVORI IN ALTEZZA", CATALOGO)
        self.assertEqual(base, "ADDETTO MACCHINE UTENSILI")
        self.assertEqual(rischi, ["CARRELLO", "LAVORI IN ALTEZZA"])
        self.assertEqual(residui, [])

    def test_carrello_sospeso(self):
        _, rischi, _ = scomponi("ADDETTO MACCHINE UTENSILI (SOSPESO CARRELLO)", CATALOGO)
        self.assertEqual(rischi, ["CARRELLO (SOSPESO)"])

    def test_seconda_mansione_riportata_non_assegnata(self):
        for valore in ("ADDETTO AGGIUSTAGGIO E ADDETTO RITOCCHI", "ADD. AGGIUSTAGGIO E RITOCCHI"):
            base, rischi, residui = scomponi(valore, CATALOGO)
            self.assertEqual(base, "ADDETTO AGGIUSTAGGIO", valore)
            self.assertEqual(rischi, ["seconda mansione: ADDETTO RITOCCHI"], valore)
            self.assertEqual(residui, [], valore)

    def test_abbreviazioni_plurali_e_varianti(self):
        self.assertEqual(scomponi("ADD.LAVAGGIO, CARRELLO E LAVORI IN ALTEZZA", CATALOGO)[0], "ADDETTO LAVAGGIO")
        self.assertEqual(scomponi("ADDETTO MANUTENZIONI, CARRELLO", CATALOGO)[0], "ADDETTO MANUTENZIONE")
        self.assertEqual(scomponi("ADDETTO MAGAZZINO B E CARRELLO", CATALOGO), ("ADDETTO MAGAZZINO", ["CARRELLO"], []))

    def test_fuori_catalogo(self):
        self.assertEqual(scomponi("DL", CATALOGO), (None, [], ["DL"]))


@override_settings(LEGACY_AUTH_ENABLED=False)
class ComandoImportaMansioniTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        for nome in ("ADDETTO MACCHINE UTENSILI", "ADDETTO AGGIUSTAGGIO", "ADDETTO RITOCCHI", "ADDETTO UFFICI"):
            Mansione.objects.get_or_create(nome=nome)

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
        self.vuota = self._dip("t.vuota", "")
        self.uguale = self._dip("t.uguale", "ADDETTO UFFICI")
        self.diversa = self._dip("t.diversa", "ADDETTO RITOCCHI")
        self.cessato = self._dip("t.cessato", "")
        DipendenteAnagraficaAziendale.objects.update_or_create(
            legacy_anagrafica_id=self.cessato, defaults={"data_cessazione": datetime.date(2025, 1, 31)},
        )
        self.xlsx = self._xlsx([
            ("TSTVUO80A01H501A", "ADDETTO MACCHINE UTENSILI, CARRELLO E LAVORI IN ALTEZZA"),
            ("TSTUGU80A01H501A", "ADDETTO UFFICI"),
            ("TSTDIV80A01H501A", "ADDETTO AGGIUSTAGGIO"),
            ("TSTCES80A01H501A", "ADDETTO UFFICI"),
            ("TSTIGN80A01H501A", "ADDETTO UFFICI"),       # CF assente in anagrafica
            ("", "ADDETTO UFFICI"),                        # CF mancante
        ])

    def tearDown(self):
        os.unlink(self.xlsx)

    def _dip(self, alias, mansione):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s, %s)", [alias, "Test", alias.upper(), "", mansione, 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", [alias])
            lid = int(cur.fetchone()[0])
        cf = {"t.vuota": "TSTVUO80A01H501A", "t.uguale": "TSTUGU80A01H501A",
              "t.diversa": "TSTDIV80A01H501A", "t.cessato": "TSTCES80A01H501A"}[alias]
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=lid, codice_fiscale=cf)
        return lid

    def _xlsx(self, righe):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ELENCO CONFRONTO PDF 2025"
        ws.append(["Cognome", "Nome", "Codice fiscale", "", "MANSIONE DI RISCHIO", "Prescrizioni o Limitazioni"])
        for cf, mansione in righe:
            ws.append(["X", "Y", cf, "", mansione, ""])
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)
        return path

    def _mansione(self, lid):
        with connection.cursor() as cur:
            cur.execute("SELECT mansione FROM anagrafica_dipendenti WHERE id = %s", [lid])
            return (cur.fetchone()[0] or "").strip()

    def _run(self, *args):
        out = io.StringIO()
        call_command("importa_mansioni_idoneita", self.xlsx, *args, stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_dry_run_non_scrive_e_conta_gli_esiti(self):
        out = self._run()
        self.assertIn("DRY-RUN", out)
        for riga in ("ASSEGNATA", "GIA_UGUALE", "DIVERSA_NON_TOCCATA", "CESSATO", "CF_NON_TROVATO", "CF_MANCANTE"):
            self.assertIn(riga, out)
        self.assertEqual(self._mansione(self.vuota), "")
        self.assertFalse(DipendenteAssegnazione.objects.exists())

    def test_output_senza_cf(self):
        self.assertNotIn("TSTVUO80A01H501A", self._run())

    def test_commit_assegna_solo_le_mansioni_vuote_con_storico(self):
        out = self._run("--commit")
        self.assertIn("Scritte: 1", out)
        self.assertEqual(self._mansione(self.vuota), "ADDETTO MACCHINE UTENSILI")
        self.assertEqual(self._mansione(self.diversa), "ADDETTO RITOCCHI")
        self.assertEqual(self._mansione(self.cessato), "")
        ass = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.vuota)
        self.assertEqual(ass.data_inizio, timezone.localdate())
        self.assertIsNotNone(ass.attivata_il)
        self.assertIn("CARRELLO", ass.note)
        self.assertTrue(DipendenteCambiamentoOrganizzativo.objects.filter(
            legacy_anagrafica_id=self.vuota, tipo=DipendenteCambiamentoOrganizzativo.TIPO_MANSIONE,
            valore_nuovo="ADDETTO MACCHINE UTENSILI",
        ).exists())

    def test_sovrascrivi_corregge_la_mansione_diversa(self):
        self._run("--commit", "--sovrascrivi")
        self.assertEqual(self._mansione(self.diversa), "ADDETTO AGGIUSTAGGIO")

    def test_idempotente(self):
        self._run("--commit")
        out = self._run("--commit")
        self.assertIn("Scritte: 0", out)
        self.assertEqual(DipendenteAssegnazione.objects.filter(legacy_anagrafica_id=self.vuota).count(), 1)

    def test_decorrenza_futura_resta_programmata(self):
        futura = (timezone.localdate() + datetime.timedelta(days=10)).isoformat()
        self._run("--commit", "--dal", futura)
        self.assertEqual(self._mansione(self.vuota), "")
        self.assertIsNone(DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.vuota).attivata_il)
        # Rilanciato prima della decorrenza non ne programma una seconda.
        self._run("--commit", "--dal", futura)
        self.assertEqual(DipendenteAssegnazione.objects.filter(legacy_anagrafica_id=self.vuota).count(), 1)
