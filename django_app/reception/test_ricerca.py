"""Ricerche live del pannello Reception e referenti dall'anagrafica. Dati sintetici."""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import DipendenteAnagraficaAziendale
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import legacy_table_has_column
from core.models import UserOnboarding

from . import servizi
from .models import Cartellino, CategoriaVisita, Ospite, Referente


@override_settings(SECURE_SSL_REDIRECT=False)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        Cartellino.objects.create(numero="01")
        CategoriaVisita.objects.create(nome="Riunione")
        self.user = get_user_model().objects.create_superuser("adm_ric", "adm@example.local", "x")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)


class RicercaOspitiTests(Base):
    def test_anonimo_json_401(self):
        self.client.logout()
        r = self.client.get(reverse("reception:api_ospiti"), {"q": "esem"})
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")

    def test_trova_per_nome_azienda_email_e_segna_chi_e_dentro(self):
        o = servizi.ospite_da_dati(nome="Mario", cognome="Esempio", email="mario@example.local", azienda="Ditta Prova")
        servizi.registra_ingresso(o, referente_nome="R")
        servizi.ospite_da_dati(nome="Luisa", cognome="Altra", azienda="Altra Srl")
        Ospite.objects.create(nome="Anonimo", cognome="Esempio", anonimizzato=True)
        for q in ("esempio mario", "ditta prova", "mario@example"):
            dati = self.client.get(reverse("reception:api_ospiti"), {"q": q}).json()["results"]
            self.assertEqual([d["cognome"] for d in dati], ["Esempio"], q)
            self.assertTrue(dati[0]["dentro"])
        self.assertEqual(self.client.get(reverse("reception:api_ospiti"), {"q": "e"}).json()["results"], [])

    def test_pagine_con_ricerca(self):
        Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local", reparto="IT")
        for nome in ("registra", "preregistrazioni", "referenti"):
            r = self.client.get(reverse(f"reception:{nome}"))
            self.assertContains(r, "reception/ricerca.js", msg_prefix=nome)
        self.assertContains(self.client.get(reverse("reception:registra")), '"nome": "Referente Prova"')

    def test_ingresso_con_telefono_e_referente_scelto(self):
        ref = Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local")
        self.client.post(reverse("reception:registra"), {"nome": "Anna", "cognome": "Prova", "telefono": "000 0000000",
                                                          "referente": ref.pk, "motivo": "Riunione", "cartellino": "01"})
        self.assertEqual(Ospite.objects.get(nome="Anna").telefono, "000 0000000")


class ReferentiDaAnagraficaTests(Base):
    def setUp(self):
        super().setUp()
        campi = {"nome": "MARIO", "cognome": "ESEMPIO", "reparto": "Qualità", "email": "m.esempio"}
        if legacy_table_has_column("anagrafica_dipendenti", "email_notifica"):
            campi["email_notifica"] = "Mario.Esempio@example.local"
        self.dip = AnagraficaDipendente.objects.create(**campi)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.dip.id, telefono_aziendale="0000 111")
        self.ex = AnagraficaDipendente.objects.create(nome="EX", cognome="ESEMPIO", reparto="Qualità", email="ex.esempio")
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.ex.id, data_cessazione=date(2025, 12, 31))

    def test_ricerca_solo_in_forza_con_email_di_notifica(self):
        dati = self.client.get(reverse("reception:api_dipendenti"), {"q": "esempio"}).json()["results"]
        self.assertEqual([(d["nome"], d["cognome"]) for d in dati], [("Mario", "Esempio")])
        d = dati[0]
        self.assertEqual((d["reparto"], d["telefono"], d["referente"]), ("Qualità", "0000 111", None))
        if legacy_table_has_column("anagrafica_dipendenti", "email_notifica"):
            self.assertEqual(d["email"], "mario.esempio@example.local")  # mai il login legacy

    def test_aggiunta_senza_doppioni_e_aggiorna(self):
        dati = {"nome": "Mario", "cognome": "Esempio", "email": "mario.esempio@example.local", "reparto": "Qualità", "dipendente_id": self.dip.id}
        self.client.post(reverse("reception:referenti"), dati)
        self.client.post(reverse("reception:referenti"), {**dati, "telefono": "1"})
        r = Referente.objects.get()
        self.assertEqual((r.dipendente_id, r.telefono), (self.dip.id, "1"))
        risposta = self.client.get(reverse("reception:api_dipendenti"), {"q": "mario"}).json()["results"]
        self.assertEqual(risposta[0]["referente"], r.pk)
        AnagraficaDipendente.objects.filter(id=self.dip.id).update(reparto="Acquisti")
        self.client.post(reverse("reception:referenti"), {"azione": "aggiorna"})
        r.refresh_from_db()
        self.assertEqual((r.reparto, r.telefono), ("Acquisti", "0000 111"))

    def test_chi_non_e_piu_in_forza_si_disattiva(self):
        r = Referente.objects.create(nome="Ex", cognome="Esempio", email="ex@example.local", dipendente_id=self.ex.id)
        self.assertContains(self.client.get(reverse("reception:referenti")), "Non più in forza")
        self.client.post(reverse("reception:referenti"), {"azione": "aggiorna"})
        r.refresh_from_db()
        self.assertFalse(r.attivo)
