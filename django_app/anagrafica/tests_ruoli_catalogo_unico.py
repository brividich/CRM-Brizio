"""Catalogo unico dei ruoli: una sola fonte, e chi ricopre ciascun ruolo.

Il «Ruolo aziendale» della scheda dipendente e i «Ruoli» del catalogo erano due
tabelle distinte (`RuoloAziendale` e `RuoloOperativo`), riallineate una tantum
dalla migration 0085: un ruolo creato dopo nel catalogo non compariva nella
tendina dello spostamento. Qui si verifica che la fonte sia una sola e che il
pulsante «Chi lo ricopre» elenchi entrambe le provenienze.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    RuoloOperativo,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CatalogoUnicoRuoliTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="ruoli_admin", email="ruoli_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            for alias, nome, cognome in (
                ("a.assegnato", "Anna", "Assegnato"),
                ("b.scheda", "Bruno", "Scheda"),
            ):
                cur.execute(
                    "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [alias, nome, cognome, "UT", "Tecnico", 1],
                )
            cur.execute("SELECT id, aliasusername FROM anagrafica_dipendenti")
            self.ids = {alias: int(pk) for pk, alias in cur.fetchall()}

    # -- tendina dello spostamento -------------------------------------------

    def test_ruolo_creato_nel_catalogo_compare_nella_tendina(self):
        RuoloOperativo.objects.create(nome="Capocommessa")
        resp = self.client.get(
            reverse("anagrafica:dipendente_detail", args=[self.ids["a.assegnato"]])
        )
        self.assertEqual(resp.status_code, 200)
        nomi = [r.nome for r in resp.context["ruoli_aziendali_catalogo"]]
        self.assertIn("Capocommessa", nomi)

    def test_ruolo_disattivato_resta_fuori_dalla_tendina(self):
        RuoloOperativo.objects.create(nome="Ruolo storico", is_active=False)
        resp = self.client.get(
            reverse("anagrafica:dipendente_detail", args=[self.ids["a.assegnato"]])
        )
        nomi = [r.nome for r in resp.context["ruoli_aziendali_catalogo"]]
        self.assertNotIn("Ruolo storico", nomi)

    # -- «Chi lo ricopre» -----------------------------------------------------

    def test_elenco_unisce_assegnazione_e_ruolo_da_scheda(self):
        ruolo = RuoloOperativo.objects.create(nome="Capocommessa")
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.ids["a.assegnato"], ruolo=ruolo
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["b.scheda"], ruolo_aziendale="capocommessa",
        )
        resp = self.client.get(
            reverse("anagrafica:ruolo_operativo_dipendenti", args=[ruolo.pk])
        )
        self.assertEqual(resp.status_code, 200)
        righe = {r["legacy_id"]: r for r in resp.context["righe"]}
        self.assertEqual(set(righe), {self.ids["a.assegnato"], self.ids["b.scheda"]})
        self.assertEqual(righe[self.ids["a.assegnato"]]["fonti"], ["Assegnato"])
        self.assertEqual(righe[self.ids["b.scheda"]]["fonti"], ["Da scheda"])

    def test_chi_e_in_entrambe_le_fonti_compare_una_volta_sola(self):
        ruolo = RuoloOperativo.objects.create(nome="Capocommessa")
        legacy_id = self.ids["a.assegnato"]
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=legacy_id, ruolo=ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=legacy_id, ruolo_aziendale="Capocommessa",
        )
        resp = self.client.get(
            reverse("anagrafica:ruolo_operativo_dipendenti", args=[ruolo.pk])
        )
        self.assertEqual(len(resp.context["righe"]), 1)
        self.assertEqual(resp.context["righe"][0]["fonti"], ["Assegnato", "Da scheda"])

    def test_ruolo_senza_nessuno_restituisce_elenco_vuoto(self):
        ruolo = RuoloOperativo.objects.create(nome="Ruolo vuoto")
        resp = self.client.get(
            reverse("anagrafica:ruolo_operativo_dipendenti", args=[ruolo.pk])
        )
        self.assertEqual(resp.context["righe"], [])

    # -- il catalogo mostra anche il conteggio testuale ------------------------

    def test_catalogo_conta_anche_i_ruoli_scritti_in_scheda(self):
        RuoloOperativo.objects.create(nome="Capocommessa")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["b.scheda"], ruolo_aziendale="Capocommessa",
        )
        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))
        per_nome = {r.nome: r for r in resp.context["ruoli"]}
        self.assertEqual(per_nome["Capocommessa"].n_assegnati, 0)
        self.assertEqual(per_nome["Capocommessa"].n_da_scheda, 1)

    # -- le rotte legacy non ricreano il doppione -----------------------------

    def test_create_legacy_non_scrive_piu_la_tabella_vecchia(self):
        from .models import RuoloAziendale

        resp = self.client.post(
            reverse("anagrafica:ruolo_aziendale_create"), {"nome": "Doppione"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(RuoloAziendale.objects.filter(nome="Doppione").exists())
