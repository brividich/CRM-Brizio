"""PC e fonti: per ogni PC quali fonti lo vedono (Intune, WatchGuard, Defender, backup). Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import DispositivoIntune
from core.models import UserOnboarding
from security.models import BackupJobRecord, SecuritySource, SoftwareInstallation, SourceType
from security.services import pc_copertura as svc


class PcCoperturaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="pcc_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        now = timezone.now()
        DispositivoIntune.objects.create(intune_id="i1", nome="PC-UNO", utente_nome="Utente Uno", conformita="compliant")
        DispositivoIntune.objects.create(intune_id="i2", nome="PC-DUE", problemi=[DispositivoIntune.PROBLEMA_NON_CIFRATO])
        DispositivoIntune.objects.create(intune_id="i3", nome="PC-VECCHIO", presente=False)

        def sw(host, fonti):
            SoftwareInstallation.objects.create(dedup_key=f"{host}{fonti}", source_kind=fonti[0], host=host, host_display=host.upper(),
                                                vendor="demo", product="prodotto", product_raw="Prodotto", version_raw="1", fonti=fonti,
                                                still_detected=True, seen_at=now, last_seen_at=now)

        sw("pc-uno.dominio.local", ["watchguard", "defender"])
        sw("pc-tre", ["watchguard"])
        sw("switch-01", ["snmp_firmware"])  # apparato di rete: non e' un PC
        src = SecuritySource.objects.create(name="Fonte sintetica", vendor="Demo", source_type=SourceType.EMAIL)
        BackupJobRecord.objects.create(source=src, job_name="Job", status="completed", completed_at=now - timedelta(hours=2),
                                       payload={"device_name": "PC-UNO"}, dedup_hash="b1")

    def test_un_pc_per_nome_con_le_sue_fonti(self):
        rows = {r["key"]: r for r in svc.righe()}
        self.assertEqual(set(rows), {"pc-uno", "pc-due", "pc-tre"})  # niente PC non piu' presente, niente switch
        uno = rows["pc-uno"]
        self.assertTrue(uno["intune"] and uno["watchguard"] and uno["defender"] and uno["backup"])
        self.assertEqual(uno["fonti"], 4)
        self.assertEqual(rows["pc-tre"]["fonti"], 1)
        self.assertEqual(rows["pc-due"]["problemi"], ["disco non cifrato (BitLocker)"])

    def test_ordine_e_filtri(self):
        rows = svc.righe()
        self.assertEqual(rows[0]["key"], "pc-due")  # prima chi ha problemi Intune
        self.assertEqual(svc.conteggi(rows), {"tutti": 3, "problemi": 1, "non_intune": 1, "senza_edr": 1, "senza_backup": 2})

    def test_pagina_e_chip_coerenti(self):
        page = self.client.get(reverse("security:pc_copertura"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "PC-UNO")
        self.assertContains(page, "Utente Uno")
        self.assertNotContains(page, "PC-VECCHIO")
        for f in page.context["filtri"]:
            filtrata = self.client.get(reverse("security:pc_copertura") + "?f=" + f["code"])
            self.assertEqual(len(filtrata.context["rows"]), f["count"], f["code"])

    def test_voce_di_menu(self):
        html = self.client.get(reverse("security:pc_copertura")).content.decode()
        sub = html.split('<nav class="soc-subnav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn('aria-current="page">PC e fonti</a>', sub)
