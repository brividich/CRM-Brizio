"""Dispositivi Microsoft Intune (assets.services.intune). Graph sempre simulato."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from assets.models import Asset, AssetITDetails, DispositivoIntune
from assets.services import intune

ORA = datetime(2026, 10, 19, 6, 45, tzinfo=dt_timezone.utc)


def _device(did="d-1", nome="PC-SINTETICO-01", seriale="SN-SINT-001", *, cifrato=True, conformita="compliant",
            sync="2026-10-18T20:00:00Z"):
    return {
        "id": did, "deviceName": nome, "serialNumber": seriale, "manufacturer": "Lenovo", "model": "ThinkPad T14",
        "operatingSystem": "Windows", "osVersion": "10.0.26100", "complianceState": conformita,
        "isEncrypted": cifrato, "lastSyncDateTime": sync, "enrolledDateTime": "2025-01-10T08:00:00Z",
        "userPrincipalName": "utente.sintetico@example.com", "userDisplayName": "Utente Sintetico",
    }


class NormalizzazioneTests(TestCase):
    def test_seriali_di_comodo_scartati(self):
        self.assertEqual(intune.seriale_valido("To be filled by O.E.M."), "")
        self.assertEqual(intune.seriale_valido(" SN-1 "), "SN-1")

    def test_mai_sincronizzato(self):
        dati = intune.normalizza(_device(sync="0001-01-01T00:00:00Z"))
        self.assertIsNone(dati["ultima_sync"])
        self.assertIn(DispositivoIntune.PROBLEMA_NON_SINCRONIZZA, intune.problemi_di(dati, ORA))

    def test_problemi(self):
        dati = intune.normalizza(_device(cifrato=False, conformita="noncompliant", sync="2026-08-01T00:00:00Z"))
        self.assertEqual(intune.problemi_di(dati, ORA), ["non_cifrato", "non_conforme", "non_sincronizza"])
        self.assertEqual(intune.problemi_di(intune.normalizza(_device()), ORA), [])


class SincronizzazioneTests(TestCase):
    def test_crea_aggiorna_e_segna_usciti(self):
        esito = intune.sincronizza(ORA, devices=[_device(), _device("d-2", "PC-02", "SN-2")])
        self.assertEqual((esito["creati"], esito["aggiornati"]), (2, 0))
        esito = intune.sincronizza(ORA, devices=[_device()])
        self.assertEqual((esito["aggiornati"], esito["usciti"]), (1, 1))
        self.assertFalse(DispositivoIntune.objects.get(intune_id="d-2").presente)

    def test_problemi_dal_cambia_solo_se_cambiano_i_problemi(self):
        intune.sincronizza(ORA, devices=[_device(cifrato=False)])
        primo = DispositivoIntune.objects.get().problemi_dal
        intune.sincronizza(ORA + timedelta(days=1), devices=[_device(cifrato=False)])
        self.assertEqual(DispositivoIntune.objects.get().problemi_dal, primo)
        intune.sincronizza(ORA + timedelta(days=2), devices=[_device()])
        self.assertIsNone(DispositivoIntune.objects.get().problemi_dal)

    def test_completa_solo_i_campi_vuoti_dell_asset_collegato(self):
        asset = Asset.objects.create(asset_tag="PC-INT-1", name="PC sintetico", asset_type=Asset.TYPE_PC,
                                     manufacturer="Dell", serial_number="")
        intune.sincronizza(ORA, devices=[_device()])
        DispositivoIntune.objects.update(asset=asset)
        intune.sincronizza(ORA, devices=[_device()])
        asset.refresh_from_db()
        self.assertEqual(asset.manufacturer, "Dell")  # già scritto: non toccato
        self.assertEqual(asset.model, "ThinkPad T14")
        self.assertEqual(asset.serial_number, "SN-SINT-001")
        self.assertEqual(AssetITDetails.objects.get(asset=asset).os, "Windows 10.0.26100")

    def test_problemi_negli_avvisi_it(self):
        intune.sincronizza(ORA, devices=[_device(cifrato=False), _device("d-2", "PC-OK", "SN-OK")])
        problemi = intune.problemi_aperti(ORA + timedelta(hours=1))
        self.assertEqual(len(problemi), 1)
        self.assertIn("non cifrato", problemi[0]["title"])
        self.assertTrue(problemi[0]["new"])
        self.assertFalse(intune.problemi_aperti(ORA + timedelta(days=2))[0]["new"])

        from assets.management.commands.notify_it_monitoring import collect_problems

        self.assertTrue(any(p["kind"] == "intune" for p in collect_problems(ORA)))


class TaskTests(TestCase):
    def test_permesso_mancante_non_fa_fallire_il_task(self):
        from assets.tasks import run_intune_sync
        from core.m365_graph import GraphError

        with patch("core.m365_graph.configurato", return_value=True), \
             patch("core.m365_graph.get_all", side_effect=GraphError("manca il permesso", 403)):
            esito = run_intune_sync()
        self.assertFalse(esito["ok"])
        self.assertIn("permesso", esito["errore"])

    def test_graph_non_configurato(self):
        from assets.tasks import run_intune_sync

        with patch("core.m365_graph.configurato", return_value=False):
            self.assertFalse(run_intune_sync()["ok"])


class RiconciliazioneTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from core.models import UserOnboarding

        self.admin = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="PC-INT-2", name="PC ufficio", asset_type=Asset.TYPE_PC,
                                          serial_number="SN-SINT-001")
        intune.sincronizza(ORA, devices=[_device()])
        self.disp = DispositivoIntune.objects.get()

    def test_proposta_per_seriale_e_collegamento(self):
        from django.urls import reverse

        url = reverse("assets:it_reconciliation")
        resp = self.client.get(url)
        self.assertContains(resp, "PC-SINTETICO-01")
        self.assertContains(resp, "Intune")
        resp = self.client.post(url, {"row": f"intune:{self.disp.pk}:{self.asset.pk}"})
        self.assertEqual(resp.status_code, 302)
        self.disp.refresh_from_db()
        self.assertEqual(self.disp.asset_id, self.asset.pk)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.model, "ThinkPad T14")

    def test_proposta_cambiata_non_collega(self):
        from django.urls import reverse

        altro = Asset.objects.create(asset_tag="PC-INT-3", name="Altro", asset_type=Asset.TYPE_PC)
        self.client.post(reverse("assets:it_reconciliation"), {"row": f"intune:{self.disp.pk}:{altro.pk}"})
        self.disp.refresh_from_db()
        self.assertIsNone(self.disp.asset_id)

    def test_riquadro_nella_scheda_asset(self):
        from django.urls import reverse

        self.disp.asset = self.asset
        self.disp.save()
        resp = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(resp, "MICROSOFT INTUNE")
        self.assertContains(resp, "Sì (BitLocker)")
        self.assertContains(resp, "Visto da")
        self.assertContains(resp, "af-fonte is-")


class HardwareIntuneTests(TestCase):
    def _hw(self, **extra):
        return {**_device(), "totalStorageSpaceInBytes": 512 * 1024 ** 3, "freeStorageSpaceInBytes": 64 * 1024 ** 3,
                "wiFiMacAddress": "AABBCCDDEEFF", "ethernetMacAddress": "", "physicalMemoryInBytes": 0, **extra}

    def test_disco_mac_e_ram_letta_a_parte(self):
        letti = []

        def ram(intune_id):
            letti.append(intune_id)
            return 16 * 1024 ** 3

        esito = intune.sincronizza(ORA, devices=[self._hw()], dettaglio=ram)
        d = DispositivoIntune.objects.get()
        self.assertEqual((d.ram_label, d.disco_label, d.disco_libero_label, d.disco_usato_pct), ("16 GB", "512 GB", "64 GB", 88))
        self.assertTrue(d.mac_wifi)
        self.assertEqual(esito["ram_lette"], 1)
        # al giro dopo la RAM c'è già: non si rilegge e lo zero della lista non la cancella
        intune.sincronizza(ORA, devices=[self._hw()], dettaglio=ram)
        self.assertEqual(letti, ["d-1"])
        self.assertEqual(DispositivoIntune.objects.get().ram_bytes, 16 * 1024 ** 3)

    def test_completa_ram_e_disco_vuoti_dell_asset(self):
        asset = Asset.objects.create(asset_tag="HW-1", name="PC-SINTETICO-01")
        AssetITDetails.objects.create(asset=asset, disco="1 TB scritto a mano")
        intune.sincronizza(ORA, devices=[self._hw()], dettaglio=lambda _id: 8 * 1024 ** 3)
        DispositivoIntune.objects.update(asset=asset)
        intune.sincronizza(ORA, devices=[self._hw()])
        details = AssetITDetails.objects.get(asset=asset)
        self.assertEqual((details.ram, details.disco), ("8,0 GB", "1 TB scritto a mano"))

    def test_campi_hardware_rifiutati_si_rilegge_senza(self):
        from core.m365_graph import GraphError

        chiamate = []

        def get_all(url, *, permesso, params=None):
            chiamate.append(params["$select"])
            if len(chiamate) == 1:
                raise GraphError("campo sconosciuto", 400)
            return [_device()]

        with patch("core.m365_graph.get_all", side_effect=get_all):
            self.assertEqual(len(intune.leggi_dispositivi()), 1)
        self.assertIn("totalStorageSpaceInBytes", chiamate[0])
        self.assertNotIn("totalStorageSpaceInBytes", chiamate[1])
