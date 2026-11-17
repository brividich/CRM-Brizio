"""«Le mie attività»: le voci DPI che aspettano chi approva, l'incaricato delle scarpe e chi consegna."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import mie_attivita
from .models import CategoriaDPI, DPIImpostazioni, ModalitaNegozio, OrdineNegozioDPI, RichiestaDPI, StatoRichiesta

User = get_user_model()
CONV = ModalitaNegozio.CONVENZIONE
FUORI = ModalitaNegozio.FUORI


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MieAttivitaDpiTests(TestCase):
    def setUp(self):
        self.scarpe = CategoriaDPI.objects.create(nome="Scarpe", consegna_magazzino=False, si_ordina_al_negozio=True)
        self.guanti = CategoriaDPI.objects.create(nome="Guanti")
        impost = DPIImpostazioni.get_singleton()
        impost.negozio_operatore_emails = "Operatore@esempio.example"
        impost.magazzino_emails = "magazzino@esempio.example"
        impost.save()

    def _request(self, email, *, superuser=True):
        crea = User.objects.create_superuser if superuser else User.objects.create_user
        request = RequestFactory().get("/")
        request.user = crea(username=email.split("@")[0], password="x", email=email)
        return request

    def _richiesta(self, categoria, stato=StatoRichiesta.APPROVATA, **campi):
        campi.setdefault("richiedente_nome", "Persona Prova")
        return RichiestaDPI.objects.create(categoria=categoria, stato=stato, **campi)

    def test_incaricato_vede_le_scarpe_da_ordinare_e_fuori_convenzione(self):
        da_ordinare = self._richiesta(self.scarpe, modalita_negozio=CONV)
        fuori = self._richiesta(self.scarpe, modalita_negozio=FUORI)
        self._richiesta(self.scarpe, modalita_negozio=CONV, stato=StatoRichiesta.INVIATA)  # non ancora approvata
        voci = mie_attivita.scarpe(self._request("operatore@esempio.example"))
        self.assertEqual([(v["code"], v["status"]) for v in voci], [
            (da_ordinare.numero, "Scarpe da ordinare"),
            (fuori.numero, "Fuori convenzione: avvisa il negozio"),
        ])
        self.assertTrue(voci[0]["url"].startswith(reverse("dpi:negozio")))

    def test_scarpe_ordinate_restano_finche_non_si_avvisa_del_ritiro(self):
        ordine = OrdineNegozioDPI.objects.create(negozio_nome="Negozio")
        in_arrivo = self._richiesta(self.scarpe, modalita_negozio=CONV, ordine_negozio=ordine)
        self._richiesta(self.scarpe, modalita_negozio=CONV, ordine_negozio=ordine, pronta_ritiro_il=timezone.now())
        voci = mie_attivita.scarpe(self._request("operatore@esempio.example"))
        self.assertEqual([v["code"] for v in voci], [in_arrivo.numero])

    def test_chi_non_e_incaricato_non_vede_le_scarpe(self):
        self._richiesta(self.scarpe, modalita_negozio=CONV)
        self.assertEqual(mie_attivita.scarpe(self._request("altro@esempio.example")), [])

    def test_senza_incaricati_le_scarpe_vanno_ai_referenti(self):
        impost = DPIImpostazioni.get_singleton()
        impost.negozio_operatore_emails = ""
        impost.responsabile_email = "referente@esempio.example"
        impost.save()
        self._richiesta(self.scarpe, modalita_negozio=CONV)
        self.assertEqual(len(mie_attivita.scarpe(self._request("referente@esempio.example"))), 1)

    def test_incaricato_senza_permesso_lo_legge_nella_voce(self):
        self._richiesta(self.scarpe, modalita_negozio=CONV)
        with mock.patch("dpi.views._is_gestore", return_value=False):
            voce = mie_attivita.scarpe(self._request("operatore@esempio.example"))[0]
        self.assertIn("Ti manca il permesso", voce["meta"])
        self.assertEqual(voce["url"], reverse("dpi:dashboard"))

    def test_magazzino_vede_le_consegne_sue_e_non_le_scarpe(self):
        guanti = self._richiesta(self.guanti)
        self._richiesta(self.scarpe)  # la consegnano i referenti
        self._richiesta(self.scarpe, modalita_negozio=CONV)  # la segue l'incaricato
        voci = mie_attivita.da_consegnare(self._request("magazzino@esempio.example"))
        self.assertEqual([(v["code"], v["status"]) for v in voci], [(guanti.numero, "Da preparare e consegnare")])
        self.assertEqual(mie_attivita.da_consegnare(self._request("altro@esempio.example")), [])

    def test_preposto_scelto_vede_la_richiesta_da_approvare(self):
        scelta = self._richiesta(self.guanti, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=10, preposto_legacy_id=7)
        self._richiesta(self.guanti, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=11, preposto_legacy_id=8)
        del_team = self._richiesta(self.guanti, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=12)
        self._richiesta(self.guanti, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=7, preposto_legacy_id=7)  # la propria
        request = self._request("preposto@esempio.example", superuser=False)
        with mock.patch("dpi.views._legacy_id", return_value=7), mock.patch("dpi.views._scope_approvatore", return_value={11, 12}):
            voci = mie_attivita.da_approvare(request)
        self.assertEqual([v["code"] for v in voci], [scelta.numero, del_team.numero])
        self.assertEqual(voci[0]["url"], reverse("dpi:gestione_detail", args=[scelta.pk]))

    def test_sezione_in_le_mie_attivita(self):
        from dashboard.views_mie_attivita import build_cose_da_gestire

        richiesta = self._richiesta(self.scarpe, modalita_negozio=CONV)
        sezioni = {s["key"]: s for s in build_cose_da_gestire(self._request("operatore@esempio.example"))["sections"]}
        self.assertEqual([v["code"] for v in sezioni["dpi_da_fare"]["items"]], [richiesta.numero])

    def test_impostazioni_segnalano_gli_indirizzi_senza_utente(self):
        self._request("magazzino@esempio.example")
        self.assertEqual(mie_attivita.incaricati_senza_utente(), [
            {"elenco": "Scarpe: operatore incaricato", "email": "Operatore@esempio.example"},
        ])
