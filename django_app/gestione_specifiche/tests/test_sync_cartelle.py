"""Catalogo allineato alla cartella delle specifiche (sola lettura della share)."""
from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteConfig
from gestione_specifiche import constants as C
from gestione_specifiche import sync_cartelle as sync
from gestione_specifiche.models import ClienteCartellaShare, EventoSpecifica, Specifica

User = get_user_model()


class SyncCartelleTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gs_share_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        ov = override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root], GESTIONE_SPECIFICHE_SHARE_EXCLUDE=["_SUPERATO"])
        ov.enable()
        self.addCleanup(ov.disable)

    def _pdf(self, rel):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4 x")
        return p

    def test_nomi_e_revisioni(self):
        self.assertEqual(sync.codice_e_revisione("15500 REV.0.pdf"), ("15500", "0"))
        self.assertEqual(sync.codice_e_revisione("DMH 00-04.002 REV. 02.pdf"), ("DMH 00-04.002", "02"))
        self.assertEqual(sync.codice_e_revisione("Capitolato tecnico.pdf"), ("Capitolato tecnico", ""))
        self.assertLess(sync.ordine_revisione("B"), sync.ordine_revisione("C"))
        self.assertLess(sync.ordine_revisione("9"), sync.ordine_revisione("10"))

    def test_primo_giro_fotografa_l_archivio(self):
        self._pdf("ALFA/15500 REV.0.pdf")
        self._pdf("ALFA/15500 REV.1.pdf")
        self._pdf("ALFA/_SUPERATO/15500 REV.00.pdf")
        self._pdf("BETA/sub/DMH 7 REV.A.pdf")
        self._pdf("BETA/DMH 7 MOD.133.pdf")
        ClienteCartellaShare.objects.create(cliente="Beta Elicotteri Srl", cartella="BETA")
        with mock.patch("gestione_specifiche.notifiche_gs.notifica_nuova_specifica") as avviso:
            esito = sync.esegui()
        self.assertTrue(esito["ok"])
        self.assertTrue(esito["prima_volta"])
        avviso.assert_not_called()
        rev1 = Specifica.objects.get(codice="15500", revisione="1")
        rev0 = Specifica.objects.get(codice="15500", revisione="0")
        self.assertEqual(rev1.stato, C.STATO_IN_VALIDITA)
        self.assertEqual(rev0.stato, C.STATO_SUPERATO)
        self.assertEqual(rev1.revisione_precedente, rev0)
        self.assertEqual(rev1.cliente, "ALFA")
        dmh = Specifica.objects.get(codice="DMH 7")
        self.assertEqual(dmh.cliente, "Beta Elicotteri Srl")  # cliente dalla mappatura della cartella
        self.assertFalse(Specifica.objects.filter(codice__icontains="MOD.133").exists())
        self.assertEqual(Specifica.objects.count(), 3)  # _SUPERATO esclusa
        self.assertTrue(EventoSpecifica.objects.filter(trigger=sync.TRIGGER, specifica=dmh).exists())

    def test_dopo_la_fotografia_i_nuovi_arrivano_in_bozza_con_avviso(self):
        self._pdf("ALFA/15500 REV.0.pdf")
        sync.esegui()
        self._pdf("ALFA/15500 REV.1.pdf")
        self._pdf("GAMMA/77 REV.0.pdf")
        with mock.patch("gestione_specifiche.notifiche_gs.notifica_nuova_specifica") as avviso:
            esito = sync.esegui()
        self.assertEqual((esito["nuove"], esito["nuove_revisioni"]), (1, 1))
        nuova_rev = Specifica.objects.get(codice="15500", revisione="1")
        self.assertEqual(nuova_rev.stato, C.STATO_BOZZA)
        self.assertEqual(nuova_rev.revisione_precedente.revisione, "0")
        self.assertEqual(Specifica.objects.get(codice="77").stato, C.STATO_BOZZA)
        self.assertEqual(avviso.call_count, 2)
        # Giro successivo senza cambiamenti: niente da fare.
        self.assertTrue(sync.esegui().get("invariata"))

    def test_file_spostato_e_specifica_gia_esistente(self):
        vecchio = os.path.join(self.root, "ALFA", "15500 REV.0.pdf")
        spec = Specifica.objects.create(codice="15500", revisione="0", titolo="T", percorso_esterno=vecchio)
        Specifica.objects.filter(pk=spec.pk).update(stato=C.STATO_IN_VALIDITA)
        nuovo = self._pdf("ALFA AEROSPACE/15500 REV.0.pdf")  # il file è stato spostato
        esito = sync.esegui()
        self.assertEqual(esito["riallineati"], 1)
        self.assertEqual(Specifica.objects.get(pk=spec.pk).percorso_esterno, nuovo)
        self.assertEqual(Specifica.objects.count(), 1)

    def test_gia_collegati_anche_con_radice_scritta_diversa(self):
        p = self._pdf("ALFA/15500 REV.0.pdf")
        Specifica.objects.create(codice="15500", revisione="0", titolo="T", percorso_esterno=p.upper())
        esito = sync.esegui()
        self.assertEqual((esito["collegati"], esito["nuove"]), (1, 0))

    def test_spenta_non_fa_nulla(self):
        SiteConfig.set(sync.FLAG, "0", "test")
        self._pdf("ALFA/1 REV.0.pdf")
        self.assertTrue(sync.esegui()["saltato"])
        self.assertFalse(Specifica.objects.exists())

    def test_pagina_di_amministrazione(self):
        self._pdf("ALFA/1 REV.0.pdf")
        sync.esegui()
        su = User.objects.create_superuser("sync_su", "s@example.invalid", "x")
        self.client.force_login(su)
        r = self.client.get(reverse("gestione_specifiche:admin_sincronizzazione"))
        self.assertContains(r, "Sincronizzazione accesa")
        self.assertContains(r, "Archivio fotografato")
        self.client.post(reverse("gestione_specifiche:admin_sincronizzazione"), {"azione": "interruttore", "attivo": "0"})
        self.assertFalse(sync.attivo())
