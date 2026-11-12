"""Richieste di appuntamento degli esterni e «Annuncia una visita». Dati sintetici."""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import NavigationItem, RoutePermissionBinding, UserOnboarding

from . import servizi, views_pubbliche
from .models import CategoriaVisita, Preregistrazione, Referente, RichiestaAppuntamento

MAIL = "core.email_utils.send_hub_mail"


def _firma(secondi_fa: int = 30) -> str:
    return signing.dumps(int(time.time()) - secondi_fa, salt=views_pubbliche.SALE_FIRMA)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.ref = Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local")
        CategoriaVisita.objects.create(nome="Riunione")
        self.domani = timezone.localdate() + timedelta(days=1)

    def richiesta(self, **kw) -> RichiestaAppuntamento:
        dati = dict(nome="Anna", cognome="Esempio", email="anna@example.local", data_visita=self.domani,
                    referente_indicato="Prova Referente")
        dati.update(kw)
        return servizi.nuova_richiesta(**dati)

    def dati_modulo(self, **kw) -> dict:
        dati = {"nome": "Anna", "cognome": "Esempio", "email": "anna@example.local", "referente": "Referente Prova",
                "data_visita": self.domani.isoformat(), "ora_inizio": "10:30", "motivo": "Riunione",
                "informativa": "1", "firma": _firma()}
        dati.update(kw)
        return dati


class TrovaReferenteTests(Base):
    def test_riconosce_solo_senza_dubbi(self):
        self.assertEqual(servizi.trova_referente("referente@example.local"), self.ref)
        self.assertEqual(servizi.trova_referente("  prova   REFERENTE "), self.ref)
        self.assertEqual(servizi.trova_referente("Referente Prova"), self.ref)
        self.assertIsNone(servizi.trova_referente("Referente"))
        self.assertIsNone(servizi.trova_referente("Altro Nome"))
        Referente.objects.create(nome="Prova", cognome="Referente", email="omonimo@example.local")
        self.assertIsNone(servizi.trova_referente("Prova Referente"))

    def test_referente_disattivato_non_si_trova(self):
        Referente.objects.filter(pk=self.ref.pk).update(attivo=False)
        self.assertIsNone(servizi.trova_referente("referente@example.local"))


class ModuloPubblicoSpentoTests(Base):
    def test_spento_di_default(self):
        self.assertEqual(self.client.get(reverse("reception_pubblica:richiesta")).status_code, 404)
        r = self.richiesta()
        self.assertEqual(self.client.get(reverse("reception_pubblica:conferma", args=[r.token])).status_code, 404)

    @override_settings(RECEPTION_RICHIESTE_PUBBLICHE=True, RECEPTION_NATIVA=False)
    def test_serve_anche_la_reception_nativa(self):
        self.assertEqual(self.client.get(reverse("reception_pubblica:richiesta")).status_code, 404)


@override_settings(RECEPTION_RICHIESTE_PUBBLICHE=True, RECEPTION_NATIVA=True, SECURE_SSL_REDIRECT=False)
class ModuloPubblicoTests(Base):
    url = property(lambda self: reverse("reception_pubblica:richiesta"))

    def test_pagina_senza_login_e_senza_elenco_dipendenti(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Registra la tua visita")
        self.assertNotContains(r, "referente@example.local")
        self.assertEqual(r["Referrer-Policy"], "same-origin")

    def test_invio_manda_la_mail_di_conferma_e_non_avvisa_nessuno(self):
        with patch(MAIL) as invia:
            r = self.client.post(self.url, self.dati_modulo())
        self.assertContains(r, "Controlla la tua email")
        richiesta = RichiestaAppuntamento.objects.get()
        self.assertEqual(richiesta.stato, RichiestaAppuntamento.DA_CONFERMARE)
        self.assertIsNone(richiesta.referente)
        self.assertEqual(invia.call_count, 1)
        self.assertEqual(invia.call_args.args[2], ["anna@example.local"])
        self.assertIn(reverse("reception_pubblica:conferma", args=[richiesta.token]), invia.call_args.args[1])

    @override_settings(RECEPTION_RICHIESTE_URL_PUBBLICO="https://visite.example.local/")
    def test_link_con_indirizzo_pubblico(self):
        with patch(MAIL) as invia:
            self.client.post(self.url, self.dati_modulo())
        self.assertIn("https://visite.example.local/richiesta-visita/conferma/", invia.call_args.args[1])

    def test_campo_trappola_finto_successo(self):
        with patch(MAIL) as invia:
            r = self.client.post(self.url, self.dati_modulo(sito_web="http://spam.example"))
        self.assertContains(r, "Controlla la tua email")
        self.assertFalse(RichiestaAppuntamento.objects.exists())
        invia.assert_not_called()

    def test_errori_di_compilazione(self):
        casi = {
            "informativa": {"informativa": ""},
            "giorno passato": {"data_visita": timezone.localdate().isoformat()},
            "troppo lontano": {"data_visita": (timezone.localdate() + timedelta(days=200)).isoformat()},
            "email": {"email": "non-una-email"},
            "troppo veloce": {"firma": _firma(0)},
            "firma falsa": {"firma": "x"},
            "referente": {"referente": ""},
        }
        for nome, modifica in casi.items():
            with patch(MAIL):
                r = self.client.post(self.url, self.dati_modulo(**modifica))
            self.assertEqual(r.status_code, 400, nome)
        self.assertFalse(RichiestaAppuntamento.objects.exists())

    def test_limite_per_ip(self):
        with patch(MAIL):
            for i in range(views_pubbliche.LIMITE_IP):
                self.client.post(self.url, self.dati_modulo(email=f"a{i}@example.local"), REMOTE_ADDR="10.9.9.9")
            r = self.client.post(self.url, self.dati_modulo(email="z@example.local"), REMOTE_ADDR="10.9.9.9")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(RichiestaAppuntamento.objects.count(), views_pubbliche.LIMITE_IP)

    def test_massimo_richieste_aperte_per_email(self):
        for _ in range(servizi.MAX_RICHIESTE_APERTE_PER_EMAIL):
            self.richiesta()
        with patch(MAIL):
            r = self.client.post(self.url, self.dati_modulo())
        self.assertContains(r, "già richieste in attesa", status_code=400)

    def test_mail_che_non_parte_cancella_la_richiesta(self):
        with patch(MAIL, side_effect=OSError):
            r = self.client.post(self.url, self.dati_modulo())
        self.assertEqual(r.status_code, 503)
        self.assertFalse(RichiestaAppuntamento.objects.exists())

    def test_conferma_con_post_avvisa_il_referente(self):
        r = self.richiesta()
        url = reverse("reception_pubblica:conferma", args=[r.token])
        self.assertContains(self.client.get(url), "Conferma e inoltra")
        r.refresh_from_db()
        self.assertEqual(r.stato, RichiestaAppuntamento.DA_CONFERMARE)  # l'apertura del link non conferma
        with patch(MAIL) as invia:
            self.assertContains(self.client.post(url), "Richiesta inoltrata")
        r.refresh_from_db()
        self.assertEqual((r.stato, r.referente), (RichiestaAppuntamento.IN_ATTESA, self.ref))
        self.assertEqual(invia.call_args.args[2], ["referente@example.local"])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_link_scaduto(self):
        r = self.richiesta()
        RichiestaAppuntamento.objects.filter(pk=r.pk).update(creata_il=timezone.now() - timedelta(hours=49))
        url = reverse("reception_pubblica:conferma", args=[r.token])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)


@override_settings(RECEPTION_NATIVA=True)
class DecisioniTests(Base):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("adm_rich", "adm@example.local", "x")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.r = self.richiesta()
        servizi.conferma_richiesta(self.r.token)

    def test_pannello_e_accetta(self):
        self.assertContains(self.client.get(reverse("reception:richieste")), "Anna Esempio")
        with patch(MAIL) as invia:
            self.client.post(reverse("reception:richiesta_azione", args=[self.r.pk]), {"azione": "approva", "ora_inizio": "11:00"})
        self.r.refresh_from_db()
        self.assertEqual(self.r.stato, RichiestaAppuntamento.APPROVATA)
        pre = self.r.preregistrazione
        self.assertEqual((pre.ospite_email, pre.referente_email, pre.data_visita), ("anna@example.local", "referente@example.local", self.domani))
        self.assertEqual(pre.ora_inizio.strftime("%H:%M"), "11:00")
        self.assertEqual(timezone.localtime(pre.scade_il).date(), self.domani)
        self.assertEqual(invia.call_args_list[0].args[2], ["anna@example.local"])
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.approva_richiesta(self.r.pk, autore="x")

    def test_rifiuta_con_nota(self):
        with patch(MAIL) as invia:
            self.client.post(reverse("reception:richiesta_azione", args=[self.r.pk]), {"azione": "rifiuta", "nota": "Sede chiusa"})
        self.r.refresh_from_db()
        self.assertEqual(self.r.stato, RichiestaAppuntamento.RIFIUTATA)
        self.assertIn("Sede chiusa", invia.call_args.args[1])
        self.assertFalse(Preregistrazione.objects.exists())

    def test_senza_referente_bisogna_sceglierlo(self):
        RichiestaAppuntamento.objects.filter(pk=self.r.pk).update(referente=None)
        with patch(MAIL):
            self.client.post(reverse("reception:richiesta_azione", args=[self.r.pk]), {"azione": "approva"})
            self.r.refresh_from_db()
            self.assertEqual(self.r.stato, RichiestaAppuntamento.IN_ATTESA)
            self.client.post(reverse("reception:richiesta_azione", args=[self.r.pk]), {"azione": "approva", "referente": self.ref.pk})
        self.r.refresh_from_db()
        self.assertEqual(self.r.stato, RichiestaAppuntamento.APPROVATA)

    @override_settings(RECEPTION_NATIVA=False)
    def test_prima_del_passaggio_non_si_accetta(self):
        with patch(MAIL):
            self.client.post(reverse("reception:richiesta_azione", args=[self.r.pk]), {"azione": "approva"})
        self.r.refresh_from_db()
        self.assertEqual(self.r.stato, RichiestaAppuntamento.IN_ATTESA)

    def test_dalla_pagina_personale_decide_solo_il_referente(self):
        url = reverse("reception:annuncia_decidi", args=[self.r.pk])
        self.assertEqual(self.client.post(url, {"azione": "rifiuta"}).status_code, 403)
        self.user.email = "REFERENTE@example.local"
        self.user.save()
        self.assertContains(self.client.get(reverse("reception:annuncia")), "Richieste per te")
        with patch(MAIL):
            self.client.post(url, {"azione": "approva"})
        self.r.refresh_from_db()
        self.assertEqual(self.r.stato, RichiestaAppuntamento.APPROVATA)


class AnnunciaTests(Base):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("dip_rc", "nuovo.dip@example.local", "x", first_name="Nuovo", last_name="Dipendente")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.dati = {"nome": "Ospite Prova", "email": "ospite@example.local", "data_visita": self.domani.isoformat(), "motivo": "Riunione"}

    @override_settings(RECEPTION_NATIVA=True)
    def test_annuncio_crea_codice_e_referente(self):
        self.assertContains(self.client.get(reverse("reception:annuncia")), "Annuncia una visita")
        with patch(MAIL) as invia:
            self.client.post(reverse("reception:annuncia"), self.dati)
        pre = Preregistrazione.objects.get()
        nuovo = Referente.objects.get(email="nuovo.dip@example.local")
        self.assertEqual((pre.referente_email, pre.referente_nome, pre.creata_da), (nuovo.email, "Dipendente Nuovo", "dip_rc"))
        self.assertEqual(invia.call_count, 2)  # ospite (codice e QR) e dipendente (calendario)
        self.assertContains(self.client.get(reverse("reception:annuncia")), pre.codice)

    def test_prima_del_passaggio_non_crea_niente(self):
        with patch(MAIL):
            self.client.post(reverse("reception:annuncia"), self.dati)
        self.assertFalse(Preregistrazione.objects.exists())
        self.assertFalse(Referente.objects.filter(email="nuovo.dip@example.local").exists())

    @override_settings(RECEPTION_NATIVA=True)
    def test_giorno_passato_rifiutato(self):
        with patch(MAIL):
            self.client.post(reverse("reception:annuncia"), {**self.dati, "data_visita": (timezone.localdate() - timedelta(days=1)).isoformat()})
        self.assertFalse(Preregistrazione.objects.exists())


class PuliziaRichiesteTests(Base):
    def test_pulizia(self):
        vecchia = self.richiesta(email="a@example.local")
        RichiestaAppuntamento.objects.filter(pk=vecchia.pk).update(creata_il=timezone.now() - timedelta(hours=49))
        decisa = self.richiesta(email="b@example.local")
        RichiestaAppuntamento.objects.filter(pk=decisa.pk).update(stato=RichiestaAppuntamento.RIFIUTATA, decisa_il=timezone.now() - timedelta(days=31))
        passata = self.richiesta(email="c@example.local")
        RichiestaAppuntamento.objects.filter(pk=passata.pk).update(stato=RichiestaAppuntamento.IN_ATTESA, data_visita=timezone.localdate() - timedelta(days=8))
        resta = self.richiesta(email="d@example.local")
        self.assertEqual(servizi.pulizia_richieste(), 3)
        self.assertEqual(list(RichiestaAppuntamento.objects.values_list("pk", flat=True)), [resta.pk])


class PermessiTests(TestCase):
    def test_binding_menu_e_dotazione_base(self):
        from core.permessi.preset import PRESETS

        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="reception:annuncia", permission_id="reception.annuncia.view").exists())
        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="reception:annuncia_decidi", permission_id="reception.annuncia.view").exists())
        voce = NavigationItem.objects.get(code="reception_annuncia")
        self.assertEqual((voce.route_name, voce.required_permission_code), ("reception:annuncia", "reception.annuncia.view"))
        for preset in (p for p in PRESETS if not p.amministratore):  # l'amministratore ha già tutto
            self.assertEqual(preset.celle.get("visite_ospiti", {}).get("vedere"), "tutti", preset.chiave)
