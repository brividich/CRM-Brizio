"""Test archiviazione notifiche in-app (scadenza automatica + azioni utente)."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import notifiche_archivio as na
from core.legacy_models import UtenteLegacy
from core.models import Notifica, Profile, SiteConfig


def _crea(legacy_user_id, *, giorni_fa=0, letta=False, letta_giorni_fa=None, **extra):
    n = Notifica.objects.create(legacy_user_id=legacy_user_id, tipo="generico", messaggio="Sintetica", letta=letta, **extra)
    updates = {"created_at": timezone.now() - timedelta(days=giorni_fa)}
    if letta_giorni_fa is not None:
        updates["letta_il"] = timezone.now() - timedelta(days=letta_giorni_fa)
    Notifica.objects.filter(pk=n.pk).update(**updates)
    n.refresh_from_db()
    return n


class PoliticaArchivioTests(TestCase):
    def test_default_e_normalizzazione(self):
        self.assertEqual(na.get_politica(), na.PoliticaArchivio(30, 14, 365))
        SiteConfig.set(na.KEY_NON_LETTE, "abc", "")
        SiteConfig.set(na.KEY_LETTE, "-5", "")
        SiteConfig.set(na.KEY_ELIMINA, "999999", "")
        p = na.get_politica()
        self.assertEqual((p.non_lette, p.lette, p.elimina), (30, 0, na.MAX_GIORNI))

    def test_set_politica_persistente(self):
        na.set_politica(non_lette="7", lette="3", elimina="0")
        self.assertEqual(na.get_politica(), na.PoliticaArchivio(7, 3, 0))


class ArchiviaScaduteTests(TestCase):
    UID = 4101

    def test_archivia_non_lette_oltre_soglia(self):
        vecchia = _crea(self.UID, giorni_fa=31)
        recente = _crea(self.UID, giorni_fa=29)

        esito = na.archivia_scadute()

        vecchia.refresh_from_db()
        recente.refresh_from_db()
        self.assertEqual(esito["non_lette"], 1)
        self.assertTrue(vecchia.archiviata)
        self.assertEqual(vecchia.archiviata_motivo, na.MOTIVO_NON_LETTA)
        self.assertIsNotNone(vecchia.archiviata_il)
        self.assertFalse(vecchia.letta)  # resta non letta: archiviata, non «letta»
        self.assertFalse(recente.archiviata)

    def test_lette_usano_letta_il_con_fallback_created_at(self):
        letta_da_poco = _crea(self.UID, giorni_fa=60, letta=True, letta_giorni_fa=2)
        letta_da_tempo = _crea(self.UID, giorni_fa=60, letta=True, letta_giorni_fa=20)
        letta_legacy = _crea(self.UID, giorni_fa=20, letta=True)  # senza letta_il

        esito = na.archivia_scadute()

        self.assertEqual(esito["lette"], 2)
        self.assertFalse(Notifica.objects.get(pk=letta_da_poco.pk).archiviata)
        self.assertTrue(Notifica.objects.get(pk=letta_da_tempo.pk).archiviata)
        self.assertTrue(Notifica.objects.get(pk=letta_legacy.pk).archiviata)

    def test_soglia_zero_disattiva(self):
        na.set_politica(non_lette=0, lette=0, elimina=0)
        _crea(self.UID, giorni_fa=400)
        _crea(self.UID, giorni_fa=400, letta=True)

        esito = na.archivia_scadute()

        self.assertEqual((esito["non_lette"], esito["lette"], esito["eliminate"]), (0, 0, 0))
        self.assertFalse(Notifica.objects.filter(archiviata=True).exists())

    def test_elimina_archiviate_oltre_conservazione(self):
        vecchia = _crea(self.UID, archiviata=True)
        Notifica.objects.filter(pk=vecchia.pk).update(archiviata_il=timezone.now() - timedelta(days=366))
        nuova = _crea(self.UID, archiviata=True)
        Notifica.objects.filter(pk=nuova.pk).update(archiviata_il=timezone.now() - timedelta(days=10))

        esito = na.archivia_scadute()

        self.assertEqual(esito["eliminate"], 1)
        self.assertFalse(Notifica.objects.filter(pk=vecchia.pk).exists())
        self.assertTrue(Notifica.objects.filter(pk=nuova.pk).exists())

    def test_dry_run_non_modifica(self):
        _crea(self.UID, giorni_fa=40)

        esito = na.archivia_scadute(dry_run=True)

        self.assertEqual(esito["non_lette"], 1)
        self.assertFalse(Notifica.objects.filter(archiviata=True).exists())

    def test_comando_management(self):
        _crea(self.UID, giorni_fa=40)
        out = StringIO()

        call_command("archivia_notifiche", stdout=out)

        self.assertIn("Non lette archiviate: 1", out.getvalue())
        self.assertTrue(Notifica.objects.filter(archiviata=True).exists())

    def test_task_schedulato_registrato(self):
        from automazioni.schedules import SCHEDULES
        from core.tasks import run_notifiche_archivio

        self.assertIn("core.tasks.run_notifiche_archivio", {s["func"] for s in SCHEDULES})
        _crea(self.UID, giorni_fa=40)
        self.assertEqual(run_notifiche_archivio()["non_lette"], 1)

    def test_data_archiviazione(self):
        politica = na.PoliticaArchivio(30, 14, 365)
        n = _crea(self.UID, giorni_fa=10)
        self.assertEqual((na.data_archiviazione(n, politica) - n.created_at).days, 30)
        letta = _crea(self.UID, giorni_fa=10, letta=True, letta_giorni_fa=1)
        self.assertEqual((na.data_archiviazione(letta, politica) - letta.letta_il).days, 14)
        self.assertIsNone(na.data_archiviazione(n, na.PoliticaArchivio(0, 14, 365)))


class NotificheArchivioViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ntfuser", password="pw")
        self.legacy = UtenteLegacy.objects.create(nome="Utente Sintetico", email="ntf@example.com", password="x", attivo=True)
        Profile.objects.create(user=self.user, legacy_user_id=self.legacy.id, legacy_ruolo="utente")
        other = UtenteLegacy.objects.create(nome="Altro Sintetico", email="ntf2@example.com", password="x", attivo=True)
        self.altrui = _crea(other.id)
        self.client.force_login(self.user)

    def test_archiviate_escluse_da_badge_live_e_pannello(self):
        attiva = _crea(self.legacy.id)
        Notifica.objects.filter(pk=attiva.pk).update(messaggio="Attiva visibile")
        archiviata = _crea(self.legacy.id, archiviata=True)
        Notifica.objects.filter(pk=archiviata.pk).update(messaggio="Archiviata nascosta")

        live = self.client.get(reverse("api_notifiche_live")).json()
        panel = self.client.get(reverse("api_notifiche_panel"))

        self.assertEqual(live["unread_count"], 1)
        self.assertEqual([p["id"] for p in live["popup_notifications"]], [attiva.id])
        self.assertContains(panel, "Attiva visibile")
        self.assertNotContains(panel, "Archiviata nascosta")

    def test_archivia_e_ripristina_singola(self):
        n = _crea(self.legacy.id)

        r = self.client.post(reverse("api_notifica_archivia", args=[n.id]))
        n.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(n.archiviata)
        self.assertEqual(n.archiviata_motivo, na.MOTIVO_UTENTE)

        r = self.client.post(reverse("api_notifica_archivia", args=[n.id]) + "?azione=ripristina")
        n.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(n.archiviata)
        self.assertTrue(n.letta)
        self.assertIsNotNone(n.letta_il)

    def test_non_si_archivia_notifica_altrui(self):
        r = self.client.post(reverse("api_notifica_archivia", args=[self.altrui.id]))
        self.assertEqual(r.status_code, 404)
        self.altrui.refresh_from_db()
        self.assertFalse(self.altrui.archiviata)

    def test_leggi_imposta_letta_il_e_non_tocca_altrui(self):
        n = _crea(self.legacy.id)
        r = self.client.post(reverse("api_notifica_leggi", args=[n.id]))
        n.refresh_from_db()
        self.assertEqual(r.json()["unread_count"], 0)
        self.assertTrue(n.letta)
        self.assertIsNotNone(n.letta_il)
        self.assertEqual(self.client.post(reverse("api_notifica_leggi", args=[self.altrui.id])).status_code, 404)

    def test_archivia_lette_in_blocco(self):
        letta = _crea(self.legacy.id, letta=True)
        non_letta = _crea(self.legacy.id)

        r = self.client.post(reverse("api_notifiche_archivia_lette"))

        self.assertEqual(r.json()["updated"], 1)
        self.assertTrue(Notifica.objects.get(pk=letta.pk).archiviata)
        self.assertFalse(Notifica.objects.get(pk=non_letta.pk).archiviata)

    def test_pagina_viste(self):
        attiva = _crea(self.legacy.id, popup_shown=True)  # niente banner globale
        Notifica.objects.filter(pk=attiva.pk).update(messaggio="Messaggio attivo")
        arch = _crea(self.legacy.id, archiviata=True, archiviata_motivo=na.MOTIVO_NON_LETTA)
        Notifica.objects.filter(pk=arch.pk).update(messaggio="Messaggio archiviato", archiviata_il=timezone.now())

        r = self.client.get(reverse("notifiche"))
        self.assertContains(r, "Messaggio attivo")
        self.assertNotContains(r, "Messaggio archiviato")
        self.assertContains(r, "Si archivia il")

        r = self.client.get(reverse("notifiche"), {"vista": "archiviate"})
        self.assertContains(r, "Messaggio archiviato")
        self.assertNotContains(r, "Messaggio attivo")
        self.assertContains(r, "Ripristina")

    def test_mark_all_read_ignora_archiviate(self):
        arch = _crea(self.legacy.id, archiviata=True)
        self.client.post(reverse("api_notifiche_mark_all_read"))
        self.assertFalse(Notifica.objects.get(pk=arch.pk).letta)
