"""Tessere dei prodotti chimici cliccabili: «Senza SDS» apre l'elenco con lo stesso numero. Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .models import ProdottoChimico, SchedaSicurezza

User = get_user_model()


class ProdottiKpiLinkTests(TestCase):
    def setUp(self):
        reparto = Reparto.objects.create(nome="Produzione KPI")
        con = ProdottoChimico.objects.create(nome="Prodotto con SDS", reparto=reparto)
        ProdottoChimico.objects.create(nome="Prodotto senza SDS 1", reparto=reparto)
        ProdottoChimico.objects.create(nome="Prodotto senza SDS 2", reparto=reparto)
        SchedaSicurezza.objects.create(
            prodotto=con, versione="1", is_corrente=True,
            pdf=SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto contenuto SDS\n", content_type="application/pdf"),
        )
        self.client.force_login(User.objects.create_user(username="sds_kpi", password="x", is_superuser=True, is_staff=True))
        self.url = reverse("schede_sicurezza:prodotto_list")

    def test_tessere_href_e_conteggi(self):
        r = self.client.get(self.url)
        self.assertContains(r, f'href="{self.url}?stato=senza_scheda#sds-elenco"')
        dest = self.client.get(self.url, {"stato": "senza_scheda"})
        self.assertEqual(dest.context["n_mostrati"], r.context["n_senza_scheda"])
        self.assertEqual(r.context["n_senza_scheda"], 2)
        self.assertEqual(r.context["n_mostrati"], 3)

    def test_da_leggere_porta_alla_sezione(self):
        r = self.client.get(reverse("schede_sicurezza:sds_da_leggere"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="#ss-da-leggere"')
        self.assertContains(r, 'id="ss-da-leggere"')
