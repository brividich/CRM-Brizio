"""Pulsanti «Accetta» / «Rifiuta» nella mail «Richiesta DPI da approvare» (dpi/approva_mail.py)."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from . import approva_mail, flusso
from .models import CategoriaDPI, RichiestaDPI, RichiestaDPICommento, StatoRichiesta

CAPO = "capo@example.test"
ALTRO = "altro@example.test"


def _persona(legacy_id):
    return {102: CAPO, 101: "dipendente@example.test"}.get(legacy_id, "")


@override_settings(SITE_URL="https://hub.example.test", LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ApprovaDaMailTests(TestCase):
    def setUp(self):
        self.categoria = CategoriaDPI.objects.create(nome="Guanti")
        self.richiesta = RichiestaDPI.objects.create(
            categoria=self.categoria, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=101,
            richiedente_nome="Persona Prova", preposto_legacy_id=102,
        )
        for nome in ("dpi.flusso._email_persona",):
            p = mock.patch(nome, side_effect=_persona)
            p.start()
            self.addCleanup(p.stop)
        # Le notifiche successive (magazzino, richiedente) non sono oggetto di questi test.
        for nome in ("dpi.flusso.notifica_approvata", "dpi.flusso.notifica_esito_richiedente", "dpi.views._notifica_richiedente"):
            p = mock.patch(nome)
            p.start()
            self.addCleanup(p.stop)

    def _url(self, decisione, email=CAPO):
        return reverse("dpi_pubblico:approva_da_mail", args=[approva_mail.crea_token(self.richiesta, email), decisione])

    def test_la_mail_ha_i_due_link_personali(self):
        flusso.notifica_nuova_richiesta(self.richiesta)
        avvisi = [m for m in mail.outbox if "da approvare" in m.subject]
        self.assertEqual([m.to for m in avvisi], [[CAPO]])
        approva, rifiuta = approva_mail.link(self.richiesta, CAPO)
        html = avvisi[0].alternatives[0][0]
        self.assertTrue(approva.startswith("https://hub.example.test/approval-actions/dpi/richiesta/"))
        for testo in (">Accetta<", ">Rifiuta<", "Apri nel portale"):
            self.assertIn(testo, html)
        self.assertIn("/approva/", avvisi[0].body)
        self.assertIn("/rifiuta/", avvisi[0].body)

    @override_settings(SITE_URL="")
    def test_senza_indirizzo_del_sito_niente_pulsanti_di_decisione(self):
        flusso.notifica_nuova_richiesta(self.richiesta)
        avviso = [m for m in mail.outbox if "da approvare" in m.subject][0]
        self.assertNotIn("Accetta", avviso.body)
        self.assertNotIn("approval-actions", avviso.body)

    def test_aprire_il_link_non_decide(self):
        pagina = self.client.get(self._url("approva"))
        self.assertContains(pagina, "Accetta la richiesta")
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.INVIATA)

    def test_il_pulsante_accetta_approva_a_nome_del_destinatario(self):
        get_user_model().objects.create_user(username="capo", email=CAPO, first_name="Capo", last_name="Reparto", password="x")
        risposta = self.client.post(self._url("approva"), {"nota": "Va bene"})
        self.assertEqual(risposta.status_code, 302)
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.APPROVATA)
        commento = RichiestaDPICommento.objects.get(richiesta=self.richiesta)
        self.assertEqual((commento.autore_nome.casefold(), commento.testo), ("capo reparto", "Va bene"))
        self.assertContains(self.client.get(self._url("approva")), "è stata accettata")

    def test_il_pulsante_rifiuta_rifiuta_con_il_motivo(self):
        self.client.post(self._url("rifiuta"), {"nota": "Già consegnati"})
        self.richiesta.refresh_from_db()
        self.assertEqual((self.richiesta.stato, self.richiesta.note_gestione), (StatoRichiesta.RIFIUTATA, "Già consegnati"))
        self.assertEqual(RichiestaDPICommento.objects.get(richiesta=self.richiesta).autore_nome, CAPO)

    def test_secondo_clic_non_cambia_la_decisione(self):
        self.client.post(self._url("approva"))
        self.client.post(self._url("rifiuta"), {"nota": "ripensamento"})
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.APPROVATA)

    def test_chi_non_approva_piu_o_il_richiedente_non_decidono(self):
        for email in (ALTRO, "dipendente@example.test"):
            self.client.post(self._url("approva", email))
            self.richiesta.refresh_from_db()
            self.assertEqual(self.richiesta.stato, StatoRichiesta.INVIATA)
        self.assertContains(self.client.get(self._url("approva", ALTRO)), "non aspetta più la tua decisione")

    def test_link_manomesso_scaduto_o_decisione_sconosciuta(self):
        buono = self._url("approva")
        self.assertEqual(self.client.get(buono.replace("/approva/", "x/approva/")).status_code, 404)
        self.assertEqual(self.client.post(buono.replace("/approva/", "/elimina/")).status_code, 404)
        with mock.patch.object(approva_mail, "GIORNI_VALIDITA", -1):
            self.assertEqual(self.client.post(buono).status_code, 404)
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.INVIATA)
