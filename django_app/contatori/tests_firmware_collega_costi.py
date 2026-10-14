"""Firmware SNMP (storico + inventario SOC), collegamento guidato all'asset, costi per asset.

Dati sintetici: IP 192.0.2.x, nomi e matricole inventati.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import firmware
from .models import DispositivoSNMP, FirmwareSNMP, Macchina, SondaSNMP
from .tests import _AuthedClientMixin


class EstraiFirmwareTests(TestCase):
    def test_da_sys_description(self):
        self.assertEqual(firmware.da_sys_description(
            "Cisco IOS Software, C2960 Software, Version 15.2(4)E10, RELEASE SOFTWARE"), "15.2(4)E10")
        self.assertEqual(firmware.da_sys_description("Demo printer MX-500 Firmware: 2.5.1"), "2.5.1")
        self.assertEqual(firmware.da_sys_description("Switch demo senza numeri utili"), "")

    def test_sonda_firmware_ha_la_precedenza(self):
        disp = DispositivoSNMP.objects.create(nome="Demo", host="192.0.2.60")
        sonda = SondaSNMP.objects.create(dispositivo=disp, nome="Firmware", oid="1.3.6.1.4.1.99999.1.0",
                                         tipo_valore=SondaSNMP.TipoValore.TESTO)
        versione, fonte = firmware.estrai("Demo Version 1.0", [{"sonda": sonda, "testo": " 3.1.4 "}])
        self.assertEqual((versione, fonte), ("3.1.4", "sonda «Firmware»"))


class StoricoFirmwareTests(TestCase):
    def setUp(self):
        self.disp = DispositivoSNMP.objects.create(nome="Switch demo", host="192.0.2.61",
                                                   produttore="Demo Networks", modello="SW-24")

    def test_storico_una_riga_per_versione(self):
        t0 = timezone.now() - timedelta(days=10)
        firmware.registra(self.disp, "1.0", "sysDescr", t0)
        firmware.registra(self.disp, "1.0", "sysDescr", t0 + timedelta(days=1))
        firmware.registra(self.disp, "1.1", "sysDescr", t0 + timedelta(days=2))
        self.assertEqual(list(FirmwareSNMP.objects.filter(dispositivo=self.disp).values_list("versione", flat=True)),
                         ["1.1", "1.0"])
        self.assertEqual(self.disp.firmware, "1.1")
        riga = FirmwareSNMP.objects.get(dispositivo=self.disp, versione="1.0")
        self.assertEqual(riga.ultimo_rilevamento, t0 + timedelta(days=1))

    def test_inventario_soc_sostituisce_la_versione(self):
        from security.models import SoftwareInstallation
        from security.services.firmware_inventory import sincronizza_dispositivo

        self.disp.firmware = "1.0"
        sincronizza_dispositivo(self.disp)
        self.disp.firmware = "1.1"
        nuova = sincronizza_dispositivo(self.disp)
        righe = SoftwareInstallation.objects.filter(source_kind="snmp_firmware", host="192.0.2.61")
        self.assertEqual(righe.count(), 2)
        self.assertEqual(nuova.product, "sw-24 firmware")
        self.assertEqual(nuova.version_raw, "1.1")
        self.assertEqual(list(righe.filter(still_detected=True).values_list("version_raw", flat=True)), ["1.1"])

    def test_senza_modello_niente_inventario(self):
        from security.models import SoftwareInstallation
        from security.services.firmware_inventory import sincronizza_dispositivo

        self.disp.modello = ""
        self.disp.firmware = "1.0"
        self.assertIsNone(sincronizza_dispositivo(self.disp))
        self.assertFalse(SoftwareInstallation.objects.filter(source_kind="snmp_firmware").exists())

    def test_scheda_mostra_firmware_e_storico(self):
        self.client.force_login(_superuser())
        t0 = timezone.now() - timedelta(days=5)
        firmware.registra(self.disp, "1.0", "sysDescr", t0)
        fields = firmware.registra(self.disp, "1.1", "sysDescr", t0 + timedelta(days=1))
        self.disp.save(update_fields=fields)
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.disp.pk]))
        self.assertContains(r, "1.1")
        self.assertContains(r, "2 versioni viste")


def _superuser():
    from django.contrib.auth import get_user_model

    u, _ = get_user_model().objects.get_or_create(
        username="fw_test_admin", defaults={"is_staff": True, "is_superuser": True})
    return u


class CollegaAssetGuidatoTests(_AuthedClientMixin, TestCase):
    def test_proposta_e_collegamento(self):
        from assets.models import Asset

        asset = Asset.objects.create(asset_tag="DEMO-MFC-9", name="MFC demo 9", serial_number="SYNMFC009")
        m = Macchina.objects.create(reparto="Reparto demo", matricola="SYNMFC009")
        r = self.client.get(reverse("contatori:macchina", args=[m.pk]))
        self.assertContains(r, "Asset trovato per seriale")
        url = reverse("contatori:apparato_collega_asset", args=["mfc", m.pk])
        self.client.post(url, {"asset": "999999"})
        m.refresh_from_db()
        self.assertIsNone(m.asset_id)  # proposta diversa da quella mostrata: niente collegamento
        self.client.post(url, {"asset": str(asset.pk)})
        m.refresh_from_db()
        self.assertEqual(m.asset_id, asset.pk)

    def test_senza_corrispondenza_resta_la_scelta_manuale(self):
        m = Macchina.objects.create(reparto="Reparto demo", matricola="SYNMFC010")
        r = self.client.get(reverse("contatori:macchina", args=[m.pk]))
        self.assertNotContains(r, "Asset trovato per")
        self.assertContains(r, "Collega un asset")


class CostiAssetTests(_AuthedClientMixin, TestCase):
    def test_somma_licenze_interventi_e_pagine(self):
        from assets.models import Asset, SoftwareLicense, SoftwareLicenseRenewal, WorkOrder
        from assets.services.costi_asset import costi_asset

        from .models import Fattura, RigaFattura

        oggi = timezone.localdate()
        asset = Asset.objects.create(asset_tag="DEMO-COST-1", name="MFC costi")
        lic = SoftwareLicense.objects.create(product_name="Modulo demo", asset=asset)
        SoftwareLicenseRenewal.objects.create(license=lic, renewed_on=oggi - timedelta(days=30), cost_eur=Decimal("120.00"))
        SoftwareLicenseRenewal.objects.create(license=lic, renewed_on=oggi - timedelta(days=400), cost_eur=Decimal("99.00"))
        WorkOrder.objects.create(asset=asset, title="Riparazione demo", status=WorkOrder.STATUS_DONE,
                                 closed_at=timezone.now() - timedelta(days=10), labor_cost_eur=Decimal("50"),
                                 materials_cost_eur=Decimal("30.50"))
        m = Macchina.objects.create(reparto="Reparto demo", matricola="SYNCOST01", contratto="CTR-DEMO", asset=asset)
        f = Fattura.objects.create(numero="1", data=oggi - timedelta(days=20), trimestre="2026-Q3", periodo_al=oggi)
        RigaFattura.objects.create(fattura=f, contratto="CTR-DEMO", a4_bn=1000, a4_col=200)
        costi = costi_asset(asset)
        self.assertEqual(costi["totale"], Decimal("200.50"))
        self.assertEqual(costi["pagine_fatturate"]["totale"], 1200)
        r = self.client.get(reverse("assets:asset_view", args=[asset.pk]))
        self.assertContains(r, "Costi registrati")
        r = self.client.get(reverse("contatori:macchina", args=[m.pk]))
        self.assertContains(r, "costi registrati negli ultimi 12 mesi")
