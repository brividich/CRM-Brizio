"""Dispositivi: elenco unico con fonti, backup, CVE e asset del registro. Dati sintetici."""
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
        self.assertEqual(svc.conteggi(rows), {"tutti": 3, "da_collegare": 3, "backup_ko": 0, "con_cve": 0, "problemi": 1,
                                              "non_intune": 1, "senza_edr": 1, "senza_backup": 2})

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
        self.assertIn('aria-current="page">Elenco</a>', sub)
        self.assertNotIn(">Asset</a>", sub)  # «Asset» non è più una pagina a parte

    def test_dispositivo_dei_report_backup_ko_cve_e_asset_in_una_riga(self):
        from assets.models import Asset
        from security.models import SecurityAsset, SecurityCveImpact, SecurityCveRecord

        hub = Asset.objects.create(asset_tag="SRV-T1", name="SRV-UNO")
        SecurityAsset.objects.create(hostname="SRV-UNO.dominio.local", hub_asset=hub)
        SecurityAsset.objects.create(hostname="PC-TRE")
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", cvss=9.8)
        SecurityCveImpact.objects.create(cve=cve, host="pc-tre.dominio.local", outcome=SecurityCveImpact.IMPACTS, explanation="sintetico")
        src = SecuritySource.objects.first()
        BackupJobRecord.objects.create(source=src, job_name="Job2", status="failed", completed_at=timezone.now() - timedelta(hours=1),
                                       payload={"device_name": "PC-DUE"}, dedup_hash="b2")
        rows = {r["key"]: r for r in svc.righe()}
        self.assertEqual(rows["srv-uno"]["asset"], hub)  # asset dal dispositivo SOC, una riga sola
        self.assertEqual(rows["pc-tre"]["cve"], {"cves": 1, "kev": 0, "gravi": 1})
        self.assertTrue(rows["pc-due"]["backup_ko"])
        self.assertEqual(svc.righe()[0]["key"], "pc-due")  # backup ko in cima
        page = self.client.get(reverse("security:pc_copertura") + "?f=con_cve")
        self.assertEqual([r["key"] for r in page.context["rows"]], ["pc-tre"])
        self.assertContains(page, "1 CVE · 1 gravi")
        scheda = self.client.get(reverse("security:pc_detail") + "?nome=PC-TRE")
        self.assertContains(scheda, "CVE-2099-0001")

    def test_scheda_anche_per_pc_solo_intune(self):
        self.assertEqual(self.client.get(reverse("security:pc_detail") + "?nome=PC-DUE").status_code, 200)
