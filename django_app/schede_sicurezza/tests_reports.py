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


from django.contrib.auth import get_user_model

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale
from core.models import Profile

from .models import PresaVisioneScheda
from .reports import matrice_presa_visione

User = get_user_model()


def crea_dipendente_con_account(etichetta: int | str, area_aziendale, *, cessato=False) -> "User":
    """Dipendente in forza + account portale, montati come in produzione.

    La catena reale passa da `anagrafica_dipendenti.utente_id`: l'id
    dell'anagrafica e l'id dell'utente legacy vivono in due tabelle diverse e
    **non** coincidono. Il primo `UtenteLegacy` creato qui e' un segnaposto
    scartato apposta, per far divergere le due sequenze di id: se coincidessero,
    un join sbagliato passerebbe i test.
    """
    from datetime import date

    from core.legacy_models import AnagraficaDipendente, UtenteLegacy

    UtenteLegacy.objects.create(
        nome=f"scarto{etichetta}", email=f"scarto{etichetta}@example.local", password="x",
    )
    utente = UtenteLegacy.objects.create(
        nome=f"dip{etichetta}", email=f"dip{etichetta}@example.local", password="x",
    )
    anagrafica = AnagraficaDipendente.objects.create(
        aliasusername=f"dip{etichetta}", utente=utente,
    )
    DipendenteAnagraficaAziendale.objects.create(
        legacy_anagrafica_id=anagrafica.id,
        area_aziendale=area_aziendale,
        data_cessazione=date(2020, 1, 1) if cessato else None,
    )
    user = User.objects.create_user(username=f"dip{etichetta}", password="x")
    Profile.objects.create(user=user, legacy_user_id=utente.id)
    return user


# Nome storico usato dai test di questo modulo.
_crea_dipendente_attivo = crea_dipendente_con_account


class MatricePresaVisioneTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.area = AreaAziendale.objects.create(nome="Produzione - Linea 1", reparto=self.reparto)
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_pdf(), versione="1", is_corrente=True,
        )

    def test_percentuale_calcolata_su_dipendenti_attivi_mappati(self):
        u1 = _crea_dipendente_attivo(9001, self.area)
        _crea_dipendente_attivo(9002, self.area)  # non conferma
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=u1)

        matrice = matrice_presa_visione()
        self.assertEqual(len(matrice), 1)
        reparto_row = matrice[0]
        self.assertEqual(reparto_row.reparto_id, self.reparto.id)
        self.assertEqual(len(reparto_row.righe), 1)
        riga = reparto_row.righe[0]
        self.assertEqual(riga.totale_dipendenti, 2)
        self.assertEqual(riga.confermati, 1)
        self.assertEqual(riga.percentuale, 50)

    def test_dipendente_cessato_escluso_dal_denominatore(self):
        u1 = _crea_dipendente_attivo(9003, self.area)
        _crea_dipendente_attivo(9004, self.area, cessato=True)
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=u1)

        riga = matrice_presa_visione()[0].righe[0]
        self.assertEqual(riga.totale_dipendenti, 1)
        self.assertEqual(riga.confermati, 1)
        self.assertEqual(riga.percentuale, 100)

    def test_nessun_dipendente_mappato_da_percentuale_none(self):
        # nessun DipendenteAnagraficaAziendale collegato all'area del reparto
        riga = matrice_presa_visione()[0].righe[0]
        self.assertEqual(riga.totale_dipendenti, 0)
        self.assertIsNone(riga.percentuale)

    def test_id_anagrafica_coincidente_con_id_utente_non_entra_nel_denominatore(self):
        """Regressione: `anagrafica_dipendenti.id` e `utenti.id` sono spazi separati.

        Un account il cui `legacy_user_id` coincide per caso con il
        `legacy_anagrafica_id` di un dipendente non e' quel dipendente. Prima
        della correzione la matrice lo contava nel reparto e ne registrava la
        presa visione: non un denominatore vuoto, una persona sbagliata.
        """
        from core.legacy_models import AnagraficaDipendente

        anagrafica = AnagraficaDipendente.objects.create(aliasusername="mai_loggato")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=anagrafica.id, area_aziendale=self.area,
        )
        estraneo = User.objects.create_user(username="estraneo", password="x")
        Profile.objects.create(user=estraneo, legacy_user_id=anagrafica.id)
        PresaVisioneScheda.objects.create(scheda=self.scheda, operatore=estraneo)

        riga = matrice_presa_visione()[0].righe[0]
        self.assertEqual(riga.totale_dipendenti, 0)
        self.assertEqual(riga.confermati, 0)
        self.assertIsNone(riga.percentuale)

    def test_prodotto_senza_scheda_corrente_non_appare_in_matrice(self):
        ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        _crea_dipendente_attivo(9005, self.area)
        nomi_prodotto = {r.prodotto_nome for r in matrice_presa_visione()[0].righe}
        self.assertNotIn("Senza scheda", nomi_prodotto)
