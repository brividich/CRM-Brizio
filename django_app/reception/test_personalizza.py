"""Testi personalizzabili (pagina pubblica, mail) e referenti presenti al chiosco. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import SiteConfig, UserOnboarding

from . import personalizza, servizi
from .models import Referente

MAIL = "core.email_utils.send_hub_mail"


class PersonalizzaTests(TestCase):
    def test_componi_solo_segnaposti_noti(self):
        self.assertEqual(personalizza.componi("Ciao {nome}, {ignoto}\n\n\n\nfine", {"nome": "Anna"}), "Ciao Anna, {ignoto}\n\nfine")

    def test_obbligatori_e_colore(self):
        self.assertIn("{codice}", personalizza.errore("invito_testo", "Senza codice"))
        self.assertEqual(personalizza.errore("invito_testo", "Codice {codice}"), "")
        self.assertIn("#RRGGBB", personalizza.errore("pagina_colore", "rosso"))
        self.assertEqual(personalizza.errore("invito_testo", ""), "")

    def test_il_predefinito_non_si_salva(self):
        personalizza.salva("pagina_titolo", personalizza.TESTI["pagina_titolo"].predefinito)
        self.assertFalse(SiteConfig.objects.filter(chiave="reception_testo_pagina_titolo").exists())
        personalizza.salva("pagina_titolo", "Prenota la tua visita")
        self.assertEqual(personalizza.leggi("pagina_titolo"), "Prenota la tua visita")


class Collegato(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser("rc_pers", "rc.pers@example.local", "x")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.ref = Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local")


class MailPersonalizzataTests(Collegato):
    def test_invito_con_testo_personalizzato(self):
        personalizza.salva("invito_oggetto", "Benvenuto {nome}")
        personalizza.salva("invito_testo", "Ciao {nome}, il codice è {codice}. {quando}")
        pre = servizi.crea_preregistrazione(ospite_nome="Ospite Uno", ospite_email="uno@example.local", referente=self.ref,
                                            creata_da="t", data_visita=timezone.localdate() + timedelta(days=1))
        from . import mail

        with patch(MAIL) as invia:
            mail.invia_invito(pre)
        oggetto, testo, dest = invia.call_args_list[0].args
        self.assertEqual((oggetto, dest), ("Benvenuto Ospite Uno", ["uno@example.local"]))
        # Modello NOVICROM HUB con il piè di pagina per gli esterni (non «portale interno»)
        self.assertIn("Costruzioni Novicrom Srl", invia.call_args_list[0].kwargs["footer_line"])
        self.assertIn(f"il codice è {pre.codice}. Visita prevista:", testo)

    def test_impostazioni_salva_rifiuta_e_prova(self):
        url = reverse("reception:impostazioni")
        self.assertContains(self.client.get(url), "Testi delle mail agli esterni")
        self.client.post(url, {"azione": "mail_invito", "invito_oggetto": "X", "invito_testo": "senza il codice"})
        self.assertEqual(personalizza.leggi("invito_oggetto"), personalizza.TESTI["invito_oggetto"].predefinito)
        self.client.post(url, {"azione": "mail_invito", "invito_oggetto": "Accesso", "invito_testo": "Codice {codice}"})
        self.assertEqual(personalizza.leggi("invito_testo"), "Codice {codice}")
        with patch(MAIL) as invia:
            self.client.post(url, {"azione": "prova_invito"})
            self.client.post(url, {"azione": "prova_conferma"})
            self.client.post(url, {"azione": "prova_rifiuto"})
        self.assertEqual([c.args[2] for c in invia.call_args_list], [["rc.pers@example.local"]] * 3)
        self.assertEqual(invia.call_args_list[0].args[1], "Codice AB12CD34")
        self.client.post(url, {"azione": "ripristina_invito"})
        self.assertEqual(personalizza.leggi("invito_testo"), personalizza.TESTI["invito_testo"].predefinito)

    @override_settings(RECEPTION_NATIVA=True, RECEPTION_RICHIESTE_PUBBLICHE=True, SECURE_SSL_REDIRECT=False)
    def test_pagina_pubblica_con_titolo_e_colore(self):
        self.client.post(reverse("reception:impostazioni"), {"azione": "pagina", "pagina_titolo": "Prenota la visita",
                                                             "pagina_intro": "Riga uno", "pagina_colore": "#aa3300"})
        self.client.logout()
        r = self.client.get(reverse("reception_pubblica:richiesta"))
        self.assertContains(r, "<h1>Prenota la visita</h1>", html=False)
        self.assertContains(r, "--accent:#aa3300")
        self.assertContains(r, "core/img/novicrom_hub.png")


@override_settings(RECEPTION_NATIVA=True)
class ReferentiPresentiTests(TestCase):
    def setUp(self):
        self.dentro = Referente.objects.create(nome="Anna", cognome="Dentro", email="dentro@example.local", dipendente_id=990010)
        self.fuori = Referente.objects.create(nome="Bruno", cognome="Fuori", email="fuori@example.local", dipendente_id=990011)
        self.libero = Referente.objects.create(nome="Carla", cognome="Senza", email="senza@example.local")

    def ids(self, valore):
        return patch("presenti.services.ids_presenti", return_value=valore)

    def test_solo_i_presenti(self):
        from fornitori import chiosco

        with self.ids({990010, 5}):
            self.assertEqual([r["id"] for r in chiosco.referenti_al_chiosco()], [self.dentro.pk])
            # L'ingresso accetta comunque anche chi non è in elenco
            self.assertIsNotNone(chiosco.referente(self.fuori.pk))

    def test_senza_presenze_o_nessuno_dentro_tutti(self):
        from fornitori import chiosco

        for valore in (None, set(), {12345}):
            with self.ids(valore):
                self.assertEqual(len(chiosco.referenti_al_chiosco()), 3)

    @override_settings(CHIOSCO_ALLOWED_IPS=["127.0.0.1"])
    def test_api_referenti_del_totem(self):
        with self.ids({990011}):
            r = self.client.post(reverse("chiosco:api", args=["referenti"]), "{}", content_type="application/json")
        self.assertEqual([x["nome"] for x in r.json()["referenti"]], ["Fuori Bruno"])
        self.assertNotIn("email", r.json()["referenti"][0])


class ModelloMailTests(TestCase):
    def test_riga_finale_personalizzabile_e_predefinita(self):
        from core.email_utils import render_hub_email_html

        self.assertIn("Portale interno", render_hub_email_html("<p>x</p>"))
        html = render_hub_email_html("<p>x</p>", footer_line="Costruzioni Novicrom Srl · NOVICROM HUB")
        self.assertNotIn("Portale interno", html)
        self.assertIn("Costruzioni Novicrom Srl · NOVICROM HUB", html)
