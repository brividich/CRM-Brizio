"""Import HR e omonimi (analisi modulo HR, 16/10/2026). Dati sintetici.

Gli import abbinano per codice fiscale; il ripiego per nome non deve mai
mettere i dati di una persona sulla scheda di un omonimo.
"""
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO

from django.core.management import call_command
from django.test import TestCase

from anagrafica.models import DipendenteAnagraficaCivile, VoceRetributiva
from anagrafica.tests import _ensure_anagrafica_table
from core.legacy_models import AnagraficaDipendente

CF_ROSSI_A = "RSSMRA80A01H501U"
CF_ROSSI_B = "RSSMRA92C15F205X"


class _Base(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def setUp(self):
        self.rossi = AnagraficaDipendente.objects.create(nome="MARIO", cognome="ROSSI", reparto="Officina")
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=self.rossi.id, codice_fiscale=CF_ROSSI_A)
        self.senza_cf = AnagraficaDipendente.objects.create(nome="LUCA", cognome="NERI", reparto="Officina")


class NomiSicuriTests(_Base):
    def test_solo_nomi_unici_senza_cf(self):
        from core.legacy_anagrafica import nomi_sicuri_per_abbinamento

        AnagraficaDipendente.objects.create(nome="ANNA", cognome="VERDI")
        AnagraficaDipendente.objects.create(nome="ANNA", cognome="VERDI2")
        mappa = nomi_sicuri_per_abbinamento()
        self.assertEqual(mappa.get("NERI LUCA"), self.senza_cf.id)
        self.assertNotIn("ROSSI MARIO", mappa)  # ha già un CF: un CF diverso nel file è un omonimo


class ImportDipendentiOmonimiTests(_Base):
    def _xlsx(self, tmp, righe):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["Cognome", "Nome", "Codice fiscale", "E-mail", "Matricola"])
        for r in righe:
            ws.append(r)
        path = f"{tmp}/people.xlsx"
        wb.save(path)
        return path

    def test_omonimo_con_cf_diverso_diventa_una_scheda_nuova(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = self._xlsx(tmp, [["Rossi", "Mario", CF_ROSSI_B, "", ""]])
            call_command("import_dipendenti_xlsx", path, stdout=StringIO())
        rossi = AnagraficaDipendente.objects.filter(cognome__iexact="ROSSI", nome__iexact="MARIO")
        self.assertEqual(rossi.count(), 2)
        self.assertEqual(
            DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=self.rossi.id).codice_fiscale, CF_ROSSI_A)
        self.assertTrue(DipendenteAnagraficaCivile.objects.filter(codice_fiscale=CF_ROSSI_B).exists())

    def test_stesso_cf_aggiorna_la_stessa_scheda(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = self._xlsx(tmp, [["Rossi", "Mario", CF_ROSSI_A, "", "M100"]])
            call_command("import_dipendenti_xlsx", path, "--update-existing", stdout=StringIO())
        self.assertEqual(AnagraficaDipendente.objects.filter(cognome__iexact="ROSSI").count(), 1)

    def test_nome_senza_codici_si_aggancia_come_prima(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = self._xlsx(tmp, [["Neri", "Luca", "NRELCU85B41H501K", "", ""]])
            call_command("import_dipendenti_xlsx", path, stdout=StringIO())
        self.assertEqual(AnagraficaDipendente.objects.filter(cognome__iexact="NERI").count(), 1)
        self.assertEqual(
            DipendenteAnagraficaCivile.objects.get(legacy_anagrafica_id=self.senza_cf.id).codice_fiscale,
            "NRELCU85B41H501K")


class ImportRetribuzioniOmonimiTests(_Base):
    def test_csv_web_non_mette_le_voci_sull_omonimo(self):
        from django.contrib.auth import get_user_model

        from anagrafica.views import _import_csv_retribuzioni

        csv = ("tax_code;nome;pay_item;value;date\n"
               f"{CF_ROSSI_A};ROSSI MARIO;Paga base;1800,00;30/09/2026\n"
               f"{CF_ROSSI_B};ROSSI MARIO;Paga base;1500,00;30/09/2026\n"
               "NRELCU85B41H501K;NERI LUCA;Paga base;1600,00;30/09/2026\n")
        user = get_user_model().objects.create_user("imp_retr", password="x")
        _import_csv_retribuzioni(BytesIO(csv.encode("utf-8")), user, "paghe.csv")
        voci = {v.tax_code: v.legacy_anagrafica_id for v in VoceRetributiva.objects.all()}
        self.assertEqual(voci[CF_ROSSI_A], self.rossi.id)
        self.assertIsNone(voci[CF_ROSSI_B])  # omonimo con CF ignoto: non abbinato
        self.assertEqual(voci["NRELCU85B41H501K"], self.senza_cf.id)  # nome unico senza CF: abbinato

    def test_comando_xlsx_stessa_regola(self):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["tax_code", "nome", "pay_item", "value", "date"])
        ws.append([CF_ROSSI_B, "ROSSI MARIO", "Paga base", 1500, "30/09/2026"])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = f"{tmp}/storico.xlsx"
            wb.save(path)
            call_command("import_retribuzioni", path, stdout=StringIO(), stderr=StringIO())
        voce = VoceRetributiva.objects.get(tax_code=CF_ROSSI_B)
        self.assertIsNone(voce.legacy_anagrafica_id)
        self.assertEqual(voce.importo, Decimal("1500"))
