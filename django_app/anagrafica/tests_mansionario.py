"""Mansionario fase 2: mansione = colonna della skill matrix, abilitazioni anche sui processi.

Dati sintetici.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, CompetenzaSkm, Mansione, Reparto, RuoloOperativo,
)
from .services import mansionario_struttura as svc
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("mns_admin", "mns@example.invalid", "x")
        self.asset = Asset.objects.create(name="Tornio sintetico TC-02", reparto="TORNI")
        self.tornio = CompetenzaSkm.objects.create(competenza_key="TC-02", display="Tornio CNC TC-02",
                                                   tipo=CompetenzaSkm.TIPO_MACCHINA, asset=self.asset)
        self.processo = CompetenzaSkm.objects.create(competenza_key="P-LAV", display="Lavaggio pezzi",
                                                     tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.contatore = CompetenzaSkm.objects.create(competenza_key="CORSI", tipo=CompetenzaSkm.TIPO_CONTATORE)
        self.ruolo = RuoloOperativo.objects.create(nome="Operatore MU sintetico")
        self.rischio = Mansione.objects.create(nome="ADDETTO MACCHINE UTENSILI T")
        self.reparto = Reparto.objects.create(nome="LAVAGGIO T")
        self.p1 = AnagraficaDipendente.objects.create(nome="UNO", cognome="ESEMPIO", aliasusername="esempio.uno.t")
        self.p2 = AnagraficaDipendente.objects.create(nome="DUE", cognome="ESEMPIO", aliasusername="esempio.due.t")


class ModelloTests(_Base):
    def test_abilitazione_su_macchina_si_aggancia_alla_colonna(self):
        ab = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p1.pk, asset=self.asset, livello="U")
        self.assertEqual(ab.competenza_id, self.tornio.pk)

    def test_abilitazione_di_processo_senza_asset_unica_per_persona(self):
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p1.pk, competenza=self.processo, livello="L")
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p2.pk, competenza=self.processo, livello="U")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p1.pk, competenza=self.processo, livello="O")

    def test_due_processi_diversi_senza_asset_per_la_stessa_persona(self):
        altro = CompetenzaSkm.objects.create(competenza_key="P-VER", display="Verniciatura", tipo=CompetenzaSkm.TIPO_PROCESSO)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p1.pk, competenza=self.processo, livello="L")
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.p1.pk, competenza=altro, livello="L")
        self.assertEqual(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=self.p1.pk).count(), 2)

    def test_reparto_dall_asset_o_scelto(self):
        self.assertEqual(self.tornio.reparto_effettivo, "TORNI")
        self.processo.reparto = self.reparto
        self.assertEqual(self.processo.reparto_effettivo, "LAVAGGIO T")


class ServizioTests(_Base):
    def test_riepilogo_esclude_il_contatore_e_conta_i_livelli(self):
        svc.assegna(self.tornio, legacy_anagrafica_id=self.p1.pk, livello="U")
        svc.assegna(self.tornio, legacy_anagrafica_id=self.p2.pk, livello="I")
        righe = {r["mansione"].pk: r for r in svc.riepilogo()}
        self.assertNotIn(self.contatore.pk, righe)
        r = righe[self.tornio.pk]
        self.assertEqual((r["in_lista"], r["operativi"], r["livelli"]["U"], r["livelli"]["I"]), (2, 1, 1, 1))
        self.assertEqual(svc.kpi(list(righe.values()))["scoperte"], 1)  # il processo

    def test_assegna_processo_e_storicizza(self):
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="L")
        self.assertIsNone(ab.asset_id)
        self.assertEqual(ab.competenza_id, self.processo.pk)
        self.assertTrue(AbilitazioneMacchinaStorico.objects.filter(competenza=self.processo, livello="L").exists())
        svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U")  # aggiorna, non duplica
        self.assertEqual(AbilitazioneMacchina.objects.filter(competenza=self.processo).count(), 1)

    def test_togli_lascia_la_riga_fuori_lista(self):
        ab = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="L")
        svc.togli(ab)
        ab.refresh_from_db()
        self.assertFalse(ab.in_lista)
        self.assertEqual(svc.persone(self.processo), [])

    def test_livello_non_valido(self):
        with self.assertRaises(ValueError):
            svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="X")

    def test_reparto_principale_livello_poi_anzianita(self):
        self.processo.reparto = self.reparto
        self.processo.save()
        svc.assegna(self.tornio, legacy_anagrafica_id=self.p1.pk, livello="L")
        svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U")
        self.assertEqual(svc.reparto_principale(self.p1.pk), "LAVAGGIO T")


class PagineTests(_Base):
    def test_pagine_e_scheda_della_mansione(self):
        self.client.force_login(self.admin)
        svc.assegna(self.tornio, legacy_anagrafica_id=self.p1.pk, livello="U")
        r = self.client.get(reverse("anagrafica:mansionario"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="mns-elenco"')
        self.assertContains(r, reverse("anagrafica:mansionario_mansione", args=[self.tornio.pk]))
        self.assertNotContains(r, reverse("anagrafica:mansionario_mansione", args=[self.contatore.pk]))
        r = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.tornio.pk]))
        self.assertContains(r, "ESEMPIO UNO")
        self.assertContains(r, "(dall'asset)")
        self.assertEqual(self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.contatore.pk])).status_code, 404)

    def test_elenco_raggruppato_per_ruolo_con_quelle_da_collegare_in_fondo(self):
        self.client.force_login(self.admin)
        self.tornio.ruoli.set([self.ruolo])
        r = self.client.get(reverse("anagrafica:mansionario"))
        gruppi = r.context["gruppi"]
        self.assertEqual([g["nome"] for g in gruppi], ["Operatore MU sintetico", "Da collegare a un ruolo"])
        self.assertEqual([s["titolo"] for s in gruppi[0]["schede"]], ["Tornio CNC TC-02"])
        self.assertIn("senza-ruolo", gruppi[1]["schede"][0]["tags"])
        self.assertIn("lavaggio pezzi", gruppi[1]["schede"][0]["q"])
        self.assertEqual(r.context["kpi"]["ruoli"], 1)

    def test_configurazione_torna_sulla_tab_impostazioni(self):
        self.client.force_login(self.admin)
        url = reverse("anagrafica:mansionario_mansione", args=[self.processo.pk])
        r = self.client.post(url, {"attiva": "on"})
        self.assertEqual(r["Location"], url + "#impostazioni")

    def test_configurazione_salva_ruoli_rischi_e_reparto_del_processo(self):
        self.client.force_login(self.admin)
        url = reverse("anagrafica:mansionario_mansione", args=[self.processo.pk])
        self.client.post(url, {"ruoli": [self.ruolo.pk], "mansioni_rischio": [self.rischio.pk],
                               "reparto": self.reparto.pk, "attiva": "on"})
        self.processo.refresh_from_db()
        self.assertEqual(list(self.processo.ruoli.all()), [self.ruolo])
        self.assertEqual(list(self.processo.mansioni_rischio.all()), [self.rischio])
        self.assertEqual(self.processo.reparto, self.reparto)

    def test_reparto_della_macchina_non_si_sovrascrive(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:mansionario_mansione", args=[self.tornio.pk]),
                         {"reparto": self.reparto.pk, "attiva": "on"})
        self.tornio.refresh_from_db()
        self.assertIsNone(self.tornio.reparto)

    def test_assegna_e_togli_dalla_pagina(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:mansionario_assegna", args=[self.processo.pk]),
                         {"persona": self.p2.pk, "livello": "O"})
        ab = AbilitazioneMacchina.objects.get(competenza=self.processo, legacy_anagrafica_id=self.p2.pk)
        self.assertEqual(ab.livello, "O")
        self.client.post(reverse("anagrafica:mansionario_togli", args=[self.processo.pk, ab.pk]))
        ab.refresh_from_db()
        self.assertFalse(ab.in_lista)

    def test_utente_senza_permessi(self):
        semplice = User.objects.create_user("mns_semplice", "s@example.invalid", "x")
        self.client.force_login(semplice)
        self.assertEqual(self.client.get(reverse("anagrafica:mansionario")).status_code, 302)
        self.client.post(reverse("anagrafica:mansionario_assegna", args=[self.processo.pk]),
                         {"persona": self.p1.pk, "livello": "O"})
        self.assertFalse(AbilitazioneMacchina.objects.filter(competenza=self.processo).exists())
