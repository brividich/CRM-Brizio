from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from anagrafica.models import Reparto

from .models import EstrazioneStato, PresaVisioneScheda, ProdottoChimico, SchedaSicurezza

User = get_user_model()


def _make_pdf_upload(name="scheda.pdf", content=b"%PDF-1.4\n%finto\n") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class ProdottoChimicoModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")

    def test_creazione_prodotto(self):
        prodotto = ProdottoChimico.objects.create(
            nome="Sgrassante XY", reparto=self.reparto, fornitore="ACME",
        )
        self.assertIsNotNone(prodotto.uuid)
        self.assertTrue(prodotto.attivo)
        self.assertIsNone(prodotto.scheda_corrente())

    def test_uuid_univoco_per_prodotto(self):
        p1 = ProdottoChimico.objects.create(nome="A", reparto=self.reparto)
        p2 = ProdottoChimico.objects.create(nome="B", reparto=self.reparto)
        self.assertNotEqual(p1.uuid, p2.uuid)


class SchedaSicurezzaModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)

    def test_una_sola_scheda_corrente_per_prodotto(self):
        s1 = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1", is_corrente=True,
        )
        s2 = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="2", is_corrente=True,
        )
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertFalse(s1.is_corrente)
        self.assertTrue(s2.is_corrente)
        self.assertEqual(self.prodotto.scheda_corrente(), s2)

    def test_storicizzazione_versioni(self):
        SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1", is_corrente=True,
        )
        SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="2", is_corrente=True,
        )
        self.assertEqual(self.prodotto.schede.count(), 2)
        self.assertEqual(
            list(self.prodotto.schede.values_list("versione", flat=True).order_by("versione")),
            ["1", "2"],
        )

    def test_default_estrazione_stato_non_eseguita(self):
        scheda = SchedaSicurezza.objects.create(prodotto=self.prodotto, pdf=_make_pdf_upload())
        self.assertEqual(scheda.estrazione_stato, EstrazioneStato.NON_ESEGUITA)


class PresaVisioneSchedaModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1", is_corrente=True,
        )
        self.operatore = User.objects.create_user(username="op1", password="x")

    def test_creazione_presa_visione(self):
        pv = PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=self.operatore)
        self.assertEqual(self.scheda.prese_visione.count(), 1)
        self.assertEqual(pv.operatore, self.operatore)

    def test_unicita_operatore_scheda(self):
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=self.operatore)
        with self.assertRaises(Exception):
            PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=self.operatore)

    def test_nuova_versione_richiede_nuova_presa_visione(self):
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=self.operatore)
        nuova_scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="2", is_corrente=True,
        )
        # La presa visione sulla versione precedente non copre la nuova versione:
        # nessun record esiste ancora per (nuova_scheda, operatore).
        self.assertFalse(
            PresaVisioneScheda.objects.filter(scheda=nuova_scheda, operatore=self.operatore).exists()
        )
        PresaVisioneScheda.objects.create(scheda=nuova_scheda, operatore=self.operatore)
        self.assertEqual(PresaVisioneScheda.objects.filter(operatore=self.operatore).count(), 2)


from datetime import timedelta

from django.utils import timezone

from .models import SCADENZA_SDS_GIORNI


class SchedaSicurezzaScadutaTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)

    def test_scheda_recente_non_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        self.assertFalse(scheda.scaduta)

    def test_scheda_vecchia_e_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        vecchia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI + 10)
        SchedaSicurezza.objects.filter(pk=scheda.pk).update(data_caricamento=vecchia_data)
        scheda.refresh_from_db()
        self.assertTrue(scheda.scaduta)

    def test_scheda_esattamente_alla_soglia_non_e_scaduta(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_make_pdf_upload(), versione="1",
        )
        soglia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI - 1)
        SchedaSicurezza.objects.filter(pk=scheda.pk).update(data_caricamento=soglia_data)
        scheda.refresh_from_db()
        self.assertFalse(scheda.scaduta)
