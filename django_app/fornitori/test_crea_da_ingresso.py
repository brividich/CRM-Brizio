"""«+ Crea fornitore» da un ingresso del GuestPortal: fornitore e tecnico, senza doppioni né accessi."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Fornitore

from . import guestportal as gp
from .models import DittaGuestPortal, TecnicoFornitore


def _accesso(nome="Mario Esempio", azienda="Nuovi Impianti Srl", ditta=None):
    return gp.Accesso(7, "CHECKEDIN", "SUPPLIER", nome, azienda, "", "", "", datetime(2026, 3, 1, 8), None, ditta_gp_id=ditta)


class CreaFornitoreTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("adm_crea", "adm@example.local", "x")
        self.client.force_login(self.user)
        self.url = reverse("fornitori:ingresso_crea_fornitore", args=[7])

    def _post(self, accesso):
        with patch.object(gp, "visita", return_value=accesso):
            return self.client.post(self.url)

    def test_crea_fornitore_e_tecnico_e_porta_ai_tecnici(self):
        r = self._post(_accesso(ditta=55))
        f = Fornitore.objects.get(ragione_sociale="Nuovi Impianti Srl")
        self.assertIn(f"/{f.pk}/", r["Location"])
        self.assertIn("#tab-tecnici", r["Location"])
        t = f.tecnici.get()
        self.assertEqual((t.nome, t.origine, t.creato_da), ("Mario Esempio", "GUESTPORTAL", self.user))
        self.assertEqual(DittaGuestPortal.objects.get(ditta_gp_id=55).fornitore, f)
        self.assertFalse(f.accede_in_sede)

    def test_il_tecnico_non_diventa_utente(self):
        utenti = get_user_model().objects.count()
        self._post(_accesso())
        self.assertEqual(get_user_model().objects.count(), utenti)

    def test_due_tecnici_della_stessa_ditta_una_sola_ditta(self):
        self._post(_accesso())
        self._post(_accesso(nome="Luisa Prova", azienda="NUOVI IMPIANTI S.R.L."))
        f = Fornitore.objects.get()
        self.assertEqual(f.tecnici.count(), 2)

    def test_ditta_non_attiva_non_si_duplica(self):
        f = Fornitore.objects.create(ragione_sociale="Nuovi Impianti", is_active=False)
        self._post(_accesso())
        self.assertEqual(Fornitore.objects.count(), 1)
        self.assertEqual(f.tecnici.count(), 1)

    def test_nome_ambiguo_non_crea_niente(self):
        Fornitore.objects.create(ragione_sociale="Nuovi Impianti Srl")
        Fornitore.objects.create(ragione_sociale="Nuovi Impianti Spa")
        r = self._post(_accesso())
        self.assertIn("accessi-esterni", r["Location"])
        self.assertEqual(Fornitore.objects.count(), 2)
        self.assertFalse(TecnicoFornitore.objects.exists())

    def test_azienda_vuota_non_crea(self):
        self._post(_accesso(azienda=""))
        self.assertFalse(Fornitore.objects.exists())

    def test_anonimizzato_crea_solo_se_c_e_ma_non_registra_il_nome(self):
        self._post(_accesso(nome="Ospite anonimizzato"))
        self.assertFalse(TecnicoFornitore.objects.exists())

    def test_il_nome_si_legge_dal_guestportal_non_dal_post(self):
        with patch.object(gp, "visita", return_value=_accesso()):
            self.client.post(self.url, {"azienda": "Altra Srl", "nome": "Altro Nome"})
        self.assertFalse(Fornitore.objects.filter(ragione_sociale="Altra Srl").exists())

    def test_ingresso_sparito_o_guestportal_giu(self):
        self.assertIn("accessi-esterni", self._post(None)["Location"])
        with patch.object(gp, "visita", side_effect=gp.GuestPortalNonRaggiungibile("giù")):
            self.assertIn("accessi-esterni", self.client.post(self.url)["Location"])
        self.assertFalse(Fornitore.objects.exists())

    def test_get_non_crea(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_senza_permesso_403(self):
        with patch("fornitori.views.col.vede_ingressi", return_value=False), patch.object(gp, "visita", return_value=_accesso()):
            self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertFalse(Fornitore.objects.exists())


class PaginaTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("adm_pag", "pag@example.local", "x"))
        self.pagina = reverse("fornitori:accessi_esterni")

    def _get(self, *accessi):
        with patch.object(gp, "db_configurato", return_value=True), patch.object(gp, "presenti_ora", return_value=list(accessi)), \
                patch.object(gp, "storico", return_value=(list(accessi), False)), patch.object(gp, "sso_configurato", return_value=False):
            return self.client.get(self.pagina)

    def test_pulsante_solo_per_la_ditta_non_in_anagrafica(self):
        self.assertContains(self._get(_accesso()), "+ Crea fornitore")
        Fornitore.objects.create(ragione_sociale="Nuovi Impianti Srl")
        self.assertNotContains(self._get(_accesso()), "+ Crea fornitore")

    def test_niente_pulsante_senza_azienda_o_anonimizzato(self):
        self.assertNotContains(self._get(_accesso(azienda="")), "+ Crea fornitore")
        self.assertNotContains(self._get(_accesso(nome="Ospite anonimizzato")), "+ Crea fornitore")

    def test_niente_pulsante_senza_permesso(self):
        with patch("fornitori.views.col.apre", return_value=False):
            self.assertNotContains(self._get(_accesso()), "+ Crea fornitore")
