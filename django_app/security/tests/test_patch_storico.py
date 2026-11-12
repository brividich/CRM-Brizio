"""Storico delle patch WatchGuard chiuse (Dispositivi › Patch installate). Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityCveRecord, WatchGuardDispositivo, WatchGuardPatch
from security.services import patch_storico


def _patch(device, patch_id, *, giorni=1, esito=None, cve="", presente=False, criticita=None):
    return WatchGuardPatch.objects.create(
        device_id=device, patch_id=patch_id, host=f"pc-{device}", host_display=f"PC-{device}".upper(),
        nome=f"Acme Patch {patch_id}", programma="Acme Viewer", cve=cve, esito=esito, criticita=criticita,
        presente=presente, chiusa_il=None if presente else timezone.now() - timedelta(days=giorni),
    )


class PatchStoricoTests(TestCase):
    def setUp(self):
        WatchGuardDispositivo.objects.create(device_id="d1", host="pc-d1", presente=True)
        WatchGuardDispositivo.objects.create(device_id="d3", host="pc-d3", presente=False)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0301", kev=True)
        _patch("d1", "p1", esito=1, cve="|CVE-2099-0301|CVE-2099-0302|", criticita=201)
        _patch("d1", "p2", giorni=5)
        _patch("d3", "p3", giorni=10)
        _patch("d1", "p4", giorni=120)
        _patch("d1", "p5", presente=True)

    def test_motivi_periodo_e_kpi(self):
        d = patch_storico.installate("90")
        motivi = {r["p"].patch_id: r["motivo"] for r in d["righe"]}
        self.assertEqual(motivi, {"p1": "confermata", "p2": "non_segnalata", "p3": "pc_uscito"})
        self.assertEqual([r["p"].patch_id for r in d["righe"]], ["p1", "p2", "p3"])
        self.assertEqual((d["kpi"]["patch"], d["kpi"]["pc"], d["kpi"]["cve"], d["kpi"]["kev"], d["kpi"]["critiche"]), (3, 2, 2, 1, 1))
        self.assertEqual(d["righe"][0]["kev"], ["CVE-2099-0301"])
        self.assertEqual(patch_storico.installate("tutto")["kpi"]["patch"], 4)

    def test_filtri_e_contatore_unico(self):
        self.assertEqual([r["p"].patch_id for r in patch_storico.installate("90", "pc_uscito")["righe"]], ["p3"])
        self.assertEqual([r["p"].patch_id for r in patch_storico.installate("90", q="cve-2099-0302")["righe"]], ["p1"])
        self.assertEqual(patch_storico.installate("xx", "yy")["periodo"], patch_storico.PERIODO_DEFAULT)
        self.assertEqual(patch_storico.conta_chiuse(30), patch_storico.installate("30")["kpi"]["patch"])

    def test_pagina_csv_e_accesso(self):
        url = reverse("security:watchguard_patch_installate")
        utente = get_user_model().objects.create(username="wg_storico_no")
        self.client.force_login(utente)
        self.assertNotEqual(self.client.get(url).status_code, 200)
        admin = get_user_model().objects.create(username="wg_storico", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(url)
        self.assertContains(page, "Acme Patch p1")
        self.assertContains(page, "Installata (esito del task WatchGuard)")
        self.assertContains(page, "CVE sfruttata")
        self.assertNotContains(page, "Acme Patch p5")
        csv = self.client.get(url, {"formato": "csv", "periodo": "tutto"})
        self.assertEqual(csv.status_code, 200)
        testo = b"".join(csv).decode("utf-8-sig")
        self.assertIn("Acme Patch p4", testo)
        self.assertIn("CVE-2099-0301", testo)
        self.assertContains(self.client.get(reverse("security:watchguard_pc")), url)
