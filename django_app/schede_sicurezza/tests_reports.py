from __future__ import annotations

from django.test import TestCase

from anagrafica.models import Reparto

from .models import ProdottoChimico, SchedaSicurezza
from .reports import prodotti_senza_scheda_corrente


def _pdf():
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class ProdottiSenzaSchedaCorrenteTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")

    def test_prodotto_senza_nessuna_scheda_e_incluso(self):
        p = ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.assertIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_con_scheda_non_corrente_e_incluso(self):
        p = ProdottoChimico.objects.create(nome="Solo scheda vecchia", reparto=self.reparto)
        SchedaSicurezza.objects.create(prodotto=p, pdf=_pdf(), versione="1", is_corrente=False)
        self.assertIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_con_scheda_corrente_e_escluso(self):
        p = ProdottoChimico.objects.create(nome="Con scheda corrente", reparto=self.reparto)
        SchedaSicurezza.objects.create(prodotto=p, pdf=_pdf(), versione="1", is_corrente=True)
        self.assertNotIn(p, prodotti_senza_scheda_corrente())

    def test_prodotto_non_attivo_e_escluso(self):
        p = ProdottoChimico.objects.create(nome="Disattivato", reparto=self.reparto, attivo=False)
        self.assertNotIn(p, prodotti_senza_scheda_corrente())
