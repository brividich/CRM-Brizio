"""Storico campi asset (PROMPT 06 - C): ogni via di scrittura produce storico. Dati sintetici."""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from core.models import UserOnboarding

from .models import Asset, AssetEndpoint, AssetFieldHistory
from .services import storico_asset
from .services.storico_asset import traccia

User = get_user_model()


def _user(username, *, superuser=False):
    user = User.objects.create_user(username=username, password="x", is_superuser=superuser, is_staff=superuser)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


def _campi(asset, **filtro):
    return list(AssetFieldHistory.objects.filter(asset=asset, **filtro).order_by("id").values_list(
        "campo", "valore_prima", "valore_dopo", "fonte"))


class ServizioTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="ST-1", name="PC storico", reparto="CED",
                                          status=Asset.STATUS_IN_USE)

    def test_nessuna_voce_se_il_valore_non_cambia(self):
        with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM):
            self.asset.reparto = "CED"
            self.asset.name = "Cambia solo il nome (non tracciato)"
            self.asset.save()
        self.assertEqual(_campi(self.asset), [])

    def test_voce_per_campo_cambiato_con_autore(self):
        user = _user("storico.autore")
        with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=user, dettaglio="prova"):
            Asset.objects.filter(pk=self.asset.pk).update(status=Asset.STATUS_IN_REPAIR, assignment_to="Rossi Mario")
        self.assertEqual(_campi(self.asset), [
            ("status", "IN_USE", "IN_REPAIR", "form"),
            ("assignment_to", "", "Rossi Mario", "form"),
        ])
        voce = AssetFieldHistory.objects.filter(asset=self.asset).first()
        self.assertEqual(voce.autore, user)
        self.assertEqual(voce.dettaglio, "prova")

    def test_endpoint_aggiunto_modificato_eliminato(self):
        with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM):
            ep = AssetEndpoint.objects.create(asset=self.asset, ip="192.0.2.10", switch_port="Gi1/0/1")
        self.assertIn(("endpoint", "", "aggiunto", "form"), _campi(self.asset))
        self.assertIn(("endpoint.ip", "", "192.0.2.10", "form"), _campi(self.asset))
        AssetFieldHistory.objects.all().delete()
        with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM):
            ep.ip = "192.0.2.11"
            ep.save()
        self.assertEqual(_campi(self.asset), [("endpoint.ip", "192.0.2.10", "192.0.2.11", "form")])
        AssetFieldHistory.objects.all().delete()
        storico_asset.registra_eliminazione_endpoint(ep, fonte=AssetFieldHistory.FONTE_ADMIN)
        self.assertEqual(_campi(self.asset), [("endpoint", "presente", "eliminato", "admin")])

    def test_rollback_insieme_alla_modifica(self):
        with self.assertRaises(RuntimeError):
            with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM):
                Asset.objects.filter(pk=self.asset.pk).update(status=Asset.STATUS_RETIRED)
                raise RuntimeError("errore sintetico")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.STATUS_IN_USE)
        self.assertEqual(_campi(self.asset), [])

    def test_asset_creato_nel_blocco(self):
        with traccia(fonte=AssetFieldHistory.FONTE_IMPORT) as storico:
            nuovo = Asset.objects.create(asset_tag="ST-NEW", name="Nuovo", reparto="Officina")
            storico.aggiungi(nuovo.pk)
        self.assertIn(("reparto", "", "Officina", "import"), _campi(nuovo))

    def test_query_costanti_e_blocchi_per_2100_parametri(self):
        ids = [self.asset.pk] + [Asset.objects.create(asset_tag=f"ST-B{i}", name="b").pk for i in range(5)]
        # 2 query per fotografia (asset + endpoint) x 2 + savepoint: non crescono con gli asset.
        with self.assertNumQueries(6):
            with traccia(ids, fonte=AssetFieldHistory.FONTE_BULK):
                pass
        self.assertEqual(storico_asset.CHUNK, 1000)

    def test_com_era_alla_data(self):
        AssetFieldHistory.objects.create(asset=self.asset, campo="reparto", valore_dopo="CED",
                                         fonte="baseline", cambiato_il=timezone.now() - timedelta(days=10))
        AssetFieldHistory.objects.create(asset=self.asset, campo="reparto", valore_prima="CED", valore_dopo="Officina",
                                         fonte="form", cambiato_il=timezone.now() - timedelta(days=2))
        prima = storico_asset.stato_alla_data(self.asset, timezone.now() - timedelta(days=5))
        dopo = storico_asset.stato_alla_data(self.asset, timezone.now())
        valore = lambda s: next(c["valore"] for c in s["campi"] if c["campo"] == "reparto")
        self.assertEqual(valore(prima), "CED")
        self.assertEqual(valore(dopo), "Officina")
        mai = storico_asset.stato_alla_data(self.asset, timezone.now() - timedelta(days=30))
        self.assertFalse(mai["tracciato"])

    @override_settings(ASSETS_STORICO_RETENTION_GIORNI=30)
    def test_retention_conserva_l_ultima_voce_di_ogni_campo(self):
        vecchio = timezone.now() - timedelta(days=90)
        AssetFieldHistory.objects.create(asset=self.asset, campo="reparto", valore_dopo="A", fonte="form", cambiato_il=vecchio)
        ultima = AssetFieldHistory.objects.create(asset=self.asset, campo="reparto", valore_dopo="B", fonte="form",
                                                  cambiato_il=vecchio + timedelta(days=1))
        self.assertEqual(storico_asset.applica_retention(), 1)
        self.assertEqual(list(AssetFieldHistory.objects.values_list("pk", flat=True)), [ultima.pk])

    def test_retention_spenta_di_default(self):
        AssetFieldHistory.objects.create(asset=self.asset, campo="reparto", valore_dopo="A", fonte="form",
                                         cambiato_il=timezone.now() - timedelta(days=999))
        self.assertEqual(storico_asset.applica_retention(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class VieDiScritturaTests(TestCase):
    def setUp(self):
        self.admin = _user("storico.admin", superuser=True)
        self.client.force_login(self.admin)
        self.asset = Asset.objects.create(asset_tag="ST-V1", name="Firewall", asset_type=Asset.TYPE_FIREWALL,
                                          reparto="CED", status=Asset.STATUS_IN_USE, source_key="st-v1")

    def test_form_modifica_asset_con_rete(self):
        response = self.client.post(reverse("assets:asset_edit", args=[self.asset.id]), {
            "asset_tag": self.asset.asset_tag, "name": self.asset.name, "asset_type": self.asset.asset_type,
            "reparto": "Rete", "manufacturer": "", "model": "", "serial_number": "",
            "status": Asset.STATUS_IN_REPAIR, "assignment_to": "",
            "assignment_reparto": "", "assignment_location": "", "notes": "",
            "network_ip": "192.0.2.20", "network_switch_name": "SW-CORE", "network_switch_port": "Gi1/0/5",
            "network_patch_panel_port": "PP-12",
        })
        self.assertEqual(response.status_code, 302)
        righe = _campi(self.asset)
        self.assertIn(("status", "IN_USE", "IN_REPAIR", "form"), righe)
        self.assertIn(("reparto", "CED", "Rete", "form"), righe)
        self.assertIn(("endpoint.ip", "", "192.0.2.20", "form"), righe)
        self.assertIn(("endpoint.punto", "", "PP-12", "form"), righe)
        self.assertTrue(all(r.autore_id == self.admin.pk for r in AssetFieldHistory.objects.filter(asset=self.asset)))

    def test_modifica_in_blocco(self):
        altro = Asset.objects.create(asset_tag="ST-V2", name="Switch", status=Asset.STATUS_IN_USE)
        response = self.client.post(reverse("assets:asset_bulk_update"), data=json.dumps(
            {"ids": [self.asset.pk, altro.pk], "fields": {"status": Asset.STATUS_RETIRED}}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        for asset in (self.asset, altro):
            self.assertEqual(_campi(asset), [("status", "IN_USE", "RETIRED", "bulk")])

    def test_assegnazione(self):
        response = self.client.post(reverse("assets:asset_assign", args=[self.asset.pk]), {
            "assigned_user_id": "", "assignment_to": "Verdi Anna", "assignment_reparto": "CED",
            "assignment_location": "Sala server",
        })
        self.assertIn(response.status_code, (200, 302))
        campi = [c[0] for c in _campi(self.asset)]
        self.assertIn("assignment_location", campi)

    def test_admin_django(self):
        # /admin/ risponde 410 in questo portale: si esercitano direttamente i ModelAdmin.
        from django.contrib.admin.sites import site
        from django.test import RequestFactory

        request = RequestFactory().post("/admin/")
        request.user = self.admin
        endpoint_admin = site._registry[AssetEndpoint]
        ep = AssetEndpoint(asset=self.asset, endpoint_name="eth0", ip="192.0.2.30")
        endpoint_admin.save_model(request, ep, form=None, change=False)
        self.assertIn(("endpoint.ip", "", "192.0.2.30", "admin"), _campi(self.asset))
        AssetFieldHistory.objects.all().delete()
        endpoint_admin.delete_model(request, ep)
        self.assertEqual(_campi(self.asset), [("endpoint", "presente", "eliminato", "admin")])
    def test_import_excel(self):
        root = Path.cwd() / "django_app" / ".tmp_tests"
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / f"storico-import-{uuid4().hex}"
        tmp.mkdir()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "inventario.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "PC"
        ws.append(["Nome", "Reparto", "IP", "Seriale"])
        ws.append(["PC-IMPORT-1", "Officina", "192.0.2.40", "SER-IMP-1"])
        wb.save(path)
        call_command("import_assets_excel", file=str(path), sheets="PC", utente_id=self.admin.pk, stdout=open(tmp / "out.txt", "w"))
        asset = Asset.objects.get(name="PC-IMPORT-1")
        righe = _campi(asset)
        self.assertIn(("reparto", "", "Officina", "import"), righe)
        self.assertIn(("endpoint.ip", "", "192.0.2.40", "import"), righe)
        self.assertEqual(AssetFieldHistory.objects.filter(asset=asset).first().autore, self.admin)
        # Reimport identico: nessuna nuova voce.
        prima = AssetFieldHistory.objects.count()
        call_command("import_assets_excel", file=str(path), sheets="PC", stdout=open(tmp / "out2.txt", "w"))
        self.assertEqual(AssetFieldHistory.objects.count(), prima)

    def test_api_assegnazioni_admin_portale(self):
        from core.legacy_models import UtenteLegacy

        legacy = UtenteLegacy.objects.create(nome="Utente Storico", email="storico@example.local", password="x", attivo=True)
        url = reverse("admin_portale:api_user_asset_assignments", args=[legacy.id])
        response = self.client.post(url, data=json.dumps({"asset_ids": [self.asset.pk]}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        righe = _campi(self.asset)
        self.assertIn(("assigned_legacy_user_id", "", str(legacy.id), "api"), righe)

    def test_vista_storico_filtri_e_alla_data(self):
        with traccia([self.asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=self.admin):
            Asset.objects.filter(pk=self.asset.pk).update(status=Asset.STATUS_IN_REPAIR, reparto="Rete")
        url = reverse("assets:asset_field_history", args=[self.asset.pk])
        body = self.client.get(url).content.decode()
        self.assertIn("In riparazione", body)
        self.assertIn("Rete", body)
        solo_rete = self.client.get(url + "?gruppo=rete").content.decode()
        self.assertNotIn("In riparazione", solo_rete)
        alla_data = self.client.get(url + f"?alla_data={date.today().isoformat()}").content.decode()
        self.assertIn("Com'era il", alla_data)
        detail = self.client.get(reverse("assets:asset_view", args=[self.asset.pk])).content.decode()
        self.assertIn(url, detail)

    def test_vista_storico_anonimo_json_401(self):
        self.client.logout()
        response = self.client.get(reverse("assets:asset_field_history", args=[self.asset.pk]),
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 401)
