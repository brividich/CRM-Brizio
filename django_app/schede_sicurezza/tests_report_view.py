from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .models import ProdottoChimico

User = get_user_model()


def _pdf():
    return SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class ReportComplianceViewTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.admin = User.objects.create_user(username="admin_report", password="x", is_superuser=True, is_staff=True)

    def test_report_visibile_a_utente_con_permesso(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senza scheda")

    def test_report_negato_a_utente_senza_permesso(self):
        utente = User.objects.create_user(username="senza_permesso_report", password="x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertNotEqual(resp.status_code, 200)

    def test_report_negato_senza_login(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())


import csv
import io

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale
from core.models import Profile

from .models import PresaVisioneScheda, SchedaSicurezza


class ReportComplianceCsvExportTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.senza_scheda = ProdottoChimico.objects.create(
            nome="Senza scheda", reparto=self.reparto, fornitore="ACME",
        )
        self.con_scheda = ProdottoChimico.objects.create(nome="Con scheda", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.con_scheda, pdf=_pdf(), versione="Rev.2", is_corrente=True,
        )
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=9101, area_aziendale=self.area)
        dip_user = User.objects.create_user(username="dip9101", password="x")
        Profile.objects.create(user=dip_user, legacy_user_id=9101)
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=dip_user)

        self.admin = User.objects.create_user(username="admin_csv", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_export_csv_gap(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"), {"formato": "csv", "sezione": "gap"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        righe = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        self.assertEqual(righe[0], ["Prodotto", "Reparto", "Fornitore"])
        self.assertIn(["Senza scheda", "Produzione", "ACME"], righe)

    def test_export_csv_matrice(self):
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"), {"formato": "csv", "sezione": "matrice"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        righe = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        self.assertEqual(
            righe[0],
            ["Reparto", "Prodotto", "Versione scheda", "Dipendenti totali", "Confermati", "Percentuale"],
        )
        self.assertIn(["Produzione", "Con scheda", "Rev.2", "1", "1", "100%"], righe)


class ReportComplianceTemplateTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.prodotto = ProdottoChimico.objects.create(nome="Con scheda", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_pdf(), versione="Rev.2", is_corrente=True,
        )
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=9201, area_aziendale=self.area)
        dip_user = User.objects.create_user(username="dip9201", password="x")
        Profile.objects.create(user=dip_user, legacy_user_id=9201)
        self.admin = User.objects.create_user(username="admin_tpl", password="x", is_superuser=True, is_staff=True)

    def test_matrice_mostra_percentuale_e_badge(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:report_compliance"))
        self.assertContains(resp, "Rev.2")
        self.assertContains(resp, "0%")  # nessuna presa visione ancora confermata

    def test_link_report_presente_in_lista_prodotti(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, reverse("schede_sicurezza:report_compliance"))
