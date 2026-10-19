"""Abbonamenti Microsoft 365 nel modulo Licenze (assets.services.m365_licenze). Graph simulato."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from assets.models import SoftwareLicense
from assets.services import m365_licenze as svc


def _sku(part="SPB", enabled=25, consumed=22, sku_id="sku-1", stato="Enabled"):
    return {"skuId": sku_id, "skuPartNumber": part, "prepaidUnits": {"enabled": enabled},
            "consumedUnits": consumed, "capabilityStatus": stato}


class SincronizzazioneTests(TestCase):
    def test_crea_e_aggiorna_solo_le_righe_m365(self):
        manuale = SoftwareLicense.objects.create(product_name="AutoCAD", vendor="Autodesk", seats_total=3, seats_used=2)
        esito = svc.sincronizza(skus=[_sku()], scadenze={"sku-1": date(2027, 3, 31)})
        self.assertEqual(esito["creati"], 1)
        lic = SoftwareLicense.objects.get(license_reference="m365:SPB")
        self.assertEqual(lic.product_name, "Microsoft 365 Business Premium")
        self.assertEqual((lic.seats_total, lic.seats_used), (25, 22))
        self.assertEqual(lic.expiry_date, date(2027, 3, 31))
        self.assertEqual(lic.category, SoftwareLicense.CATEGORY_OFFICE)

        lic.notes = "nota interna"
        lic.product_name = "Business Premium (contratto 2026)"
        lic.save()
        svc.sincronizza(skus=[_sku(consumed=24)], scadenze={})
        lic.refresh_from_db()
        self.assertEqual(lic.seats_used, 24)
        self.assertEqual(lic.product_name, "Business Premium (contratto 2026)")  # nome scelto a mano: resta
        self.assertEqual(lic.expiry_date, date(2027, 3, 31))  # senza data nuova: resta quella vecchia
        manuale.refresh_from_db()
        self.assertEqual((manuale.seats_total, manuale.seats_used), (3, 2))

    def test_piani_gratuiti_scartati_e_abbonamento_sparito_disattivato(self):
        svc.sincronizza(skus=[_sku(), _sku("FLOW_FREE", enabled=10000, consumed=4, sku_id="x")], scadenze={})
        self.assertFalse(SoftwareLicense.objects.filter(license_reference="m365:FLOW_FREE").exists())
        esito = svc.sincronizza(skus=[], scadenze={})
        self.assertEqual(esito["non_piu_presenti"], 1)
        self.assertFalse(SoftwareLicense.objects.get(license_reference="m365:SPB").is_active)

    def test_abbonamento_sospeso_non_attivo(self):
        svc.sincronizza(skus=[_sku(stato="Suspended")], scadenze={})
        self.assertFalse(SoftwareLicense.objects.get(license_reference="m365:SPB").is_active)

    def test_nome_sconosciuto_leggibile(self):
        self.assertEqual(svc.nome_leggibile("NUOVO_PIANO_X"), "Nuovo Piano X")


class DateTests(TestCase):
    def test_permesso_date_mancante_non_blocca(self):
        from core.m365_graph import GraphError

        with patch("core.m365_graph.get_all", side_effect=GraphError("403", 403)):
            self.assertEqual(svc._scadenze({"sku-1"}), {})

    def test_prima_scadenza_tra_piu_abbonamenti(self):
        dati = [{"skuId": "sku-1", "nextLifecycleDateTime": "2027-05-01T00:00:00Z"},
                {"skuId": "sku-1", "nextLifecycleDateTime": "2027-02-01T00:00:00Z"},
                {"skuId": "altro", "nextLifecycleDateTime": "2027-01-01T00:00:00Z"}]
        with patch("core.m365_graph.get_all", return_value=dati):
            self.assertEqual(svc._scadenze({"sku-1"}), {"sku-1": date(2027, 2, 1)})


class TaskTests(TestCase):
    def test_permesso_mancante_non_fa_fallire_il_task(self):
        from assets.tasks import run_m365_licenze_sync
        from core.m365_graph import GraphError

        with patch("core.m365_graph.configurato", return_value=True), \
             patch("core.m365_graph.get_all", side_effect=GraphError("manca il permesso", 403)):
            self.assertFalse(run_m365_licenze_sync()["ok"])



class SegnalazioniTests(TestCase):
    def test_abbonamenti_m365_trattati_come_le_altre_licenze(self):
        """Sono licenze software: compaiono tra quelle da collegare all'inventario (es. Office sui PC)."""
        from assets.services.software_licenze import coverage_report

        svc.sincronizza(skus=[_sku()], scadenze={})
        nomi = [r["license"].product_name for r in coverage_report()["unlinked"]]
        self.assertIn("Microsoft 365 Business Premium", nomi)

    def test_collegamento_all_inventario_non_perso_alla_sincronizzazione(self):
        svc.sincronizza(skus=[_sku()], scadenze={})
        SoftwareLicense.objects.filter(license_reference="m365:SPB").update(inventory_key="microsoft|microsoft 365 apps")
        svc.sincronizza(skus=[_sku(consumed=23)], scadenze={})
        self.assertEqual(SoftwareLicense.objects.get(license_reference="m365:SPB").inventory_key, "microsoft|microsoft 365 apps")
