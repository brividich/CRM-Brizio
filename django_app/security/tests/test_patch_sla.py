"""Tempi di installazione delle patch WatchGuard (services/patch_sla.py). Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from security.models import SecurityAlert, SecurityCveRecord, WatchGuardDispositivo, WatchGuardPatch, WatchGuardPatchGiorno
from security.services import iso27001, patch_sla, periodic_report, soc_settings
from security.services.rule_engine import evaluate_security_rules


def _patch(device, patch_id, *, pubblicata=30, chiusa=None, criticita=None, cve="", esito=None, asset=None, nome=None):
    """``pubblicata`` e ``chiusa`` in giorni fa; senza ``chiusa`` la patch manca ancora."""
    oggi = timezone.localdate()
    return WatchGuardPatch.objects.create(
        device_id=device, patch_id=patch_id, host=f"pc-{device}", host_display=f"PC-{device}".upper(), hub_asset=asset,
        nome=nome or f"Acme Patch {patch_id}", programma="Acme Viewer", cve=cve, criticita=criticita, esito=esito,
        rilasciata_il=oggi - timedelta(days=pubblicata) if pubblicata is not None else None,
        presente=chiusa is None, chiusa_il=timezone.now() - timedelta(days=chiusa) if chiusa is not None else None,
    )


class PatchSlaTests(TestCase):
    def setUp(self):
        for d in ("d1", "d2"):
            WatchGuardDispositivo.objects.create(device_id=d, host=f"pc-{d}", presente=True)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0401", kev=True)
        # mancanti: KEV pubblicata 10 gg fa (termine 7 → 3 gg di ritardo), critica nel termine, importante con errore
        _patch("d1", "kev", pubblicata=10, cve="|CVE-2099-0401|", criticita=203)
        _patch("d2", "kev", pubblicata=10, cve="|CVE-2099-0401|", criticita=203)
        _patch("d1", "crit", pubblicata=5, criticita=201)
        _patch("d2", "imp", pubblicata=5, criticita=202, esito=4)
        _patch("d1", "senzadata", pubblicata=None)
        # installate: critica in 10 gg (nel termine 14), importante in 40 gg (oltre 30), una sparita col PC uscito
        _patch("d1", "c-ok", pubblicata=15, chiusa=5, criticita=201)
        _patch("d2", "i-late", pubblicata=45, chiusa=5, criticita=202)
        _patch("dx", "uscito", pubblicata=50, chiusa=5, criticita=201)

    def test_classi_termini_e_ferme(self):
        voci = {v["p"].patch_id: v for v in patch_sla.mancanti() if v["p"].device_id == "d1"}
        self.assertEqual(voci["kev"]["classe"], patch_sla.KEV)
        self.assertEqual(voci["kev"]["giorni_ritardo"], 3)
        self.assertFalse(voci["crit"]["scaduta"])
        self.assertIsNone(voci["senzadata"]["scadenza"])
        f = patch_sla.ferme()
        self.assertEqual([g["nome"] for g in f["righe"]], ["Acme Patch kev", "Acme Patch imp"])
        self.assertEqual(len(f["righe"][0]["pc"]), 2)
        self.assertEqual((f["kpi"]["patch"], f["kpi"]["pc"], f["kpi"]["scadute"], f["kpi"]["errori"], f["kpi"]["kev"]), (2, 2, 2, 1, 1))
        self.assertEqual([g["nome"] for g in patch_sla.ferme(stato_filtro="errori")["righe"]], ["Acme Patch imp"])
        self.assertEqual(patch_sla.ferme(classe_filtro="critica")["righe"], [])
        self.assertEqual(len(patch_sla.ferme(q="pc-d2")["righe"]), 2)
        soc_settings.save({"patch.sla.kev_giorni": 30}, None)
        self.assertEqual([g["nome"] for g in patch_sla.ferme()["righe"]], ["Acme Patch imp"])

    def test_tempi_escludono_pc_uscito(self):
        oggi = timezone.localdate()
        t = patch_sla.tempi(oggi - timedelta(days=30), oggi)
        classi = {c["classe"]: c for c in t["classi"]}
        self.assertEqual((t["installate"], t["in_tempo"], t["in_ritardo"], t["in_tempo_pct"], t["giorni_medi"]), (2, 1, 1, 50, 25))
        self.assertEqual((classi["critica"]["installate"], classi["critica"]["giorni_medi"], classi["critica"]["in_tempo"]), (1, 10, 1))
        self.assertEqual((classi["importante"]["in_ritardo"], classi["importante"]["mancanti"]), (1, 1))
        self.assertEqual((classi["kev"]["mancanti"], classi["kev"]["oltre_termine"]), (2, 2))
        self.assertEqual((t["mancanti"], t["oltre_termine"], t["oltre_termine_gravi"], t["errori"]), (5, 2, 2, 1))
        self.assertEqual(patch_sla.tempi(oggi - timedelta(days=2), oggi)["installate"], 0)

    def test_fotografia_e_andamento(self):
        foto = patch_sla.registra_giorno()
        self.assertEqual((foto.mancanti, foto.pc, foto.critiche, foto.kev, foto.oltre_termine), (5, 2, 1, 2, 2))
        patch_sla.registra_giorno()
        self.assertEqual(WatchGuardPatchGiorno.objects.count(), 1)
        a = patch_sla.andamento(settimane=4)
        self.assertEqual(len(a["settimane"]), 4)
        self.assertEqual(a["settimane"][-1]["mancanti"], 5)
        self.assertIsNone(a["settimane"][0]["mancanti"])
        self.assertEqual(a["installate_totale"], len(patch_sla.installazioni(a["settimane"][0]["inizio"], timezone.localdate())))
        self.assertTrue(a["settimane"][-1]["etichetta"])

    def test_alert_spento_di_default_poi_aperto_e_chiuso(self):
        self.assertEqual(patch_sla.segnala_scadute(), (0, 0))
        soc_settings.save({"patch.sla.attivo": True}, None)
        self.assertEqual(patch_sla.segnala_scadute(), (1, 0))
        self.assertEqual(patch_sla.segnala_scadute(), (0, 0))
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(event__event_type=patch_sla.EVENT_SLA)
        self.assertIn("Acme Patch kev", alert.title)
        self.assertIn("2 PC", alert.title)
        WatchGuardPatch.objects.filter(patch_id="kev").update(presente=False, chiusa_il=timezone.now())
        self.assertEqual(patch_sla.segnala_scadute(), (0, 1))
        alert.refresh_from_db()
        self.assertNotIn(alert.status, ("new", "open", "in_progress"))

    def test_report_e_iso(self):
        oggi = timezone.localdate()
        r = periodic_report.build_report(oggi - timedelta(days=30), oggi)
        self.assertEqual(r["patch"]["installate"], 2)
        esito = iso27001._v_8_8(oggi - timedelta(days=30), oggi)
        self.assertEqual(esito["numeri"]["patch_oltre_termine_kev_o_critiche"], 2)
        self.assertEqual(len(esito["numeri"]["patch_classi"]), 4)
        self.assertNotEqual(esito["stato"], iso27001.OK)


class PatchSlaPagineTests(TestCase):
    def setUp(self):
        WatchGuardDispositivo.objects.create(device_id="d1", host="pc-d1", presente=True)
        self.hub = Asset.objects.create(asset_tag="WGP-DEMO", name="PC-D1", asset_type="PC")
        _patch("d1", "late", pubblicata=200, criticita=201, asset=self.hub)
        _patch("d1", "done", pubblicata=40, chiusa=3, criticita=202, asset=self.hub, cve="|CVE-2099-0402|")
        self.admin = get_user_model().objects.create(username="wgp_tempi", is_staff=True, is_superuser=True)

    def test_pagina_csv_e_accesso(self):
        url = reverse("security:watchguard_patch_tempi")
        self.client.force_login(get_user_model().objects.create(username="wgp_tempi_no"))
        self.assertNotEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.admin)
        page = self.client.get(url)
        self.assertContains(page, "Acme Patch late")
        self.assertContains(page, "Patch ferme")
        self.assertContains(page, "186 giorni")
        csv = self.client.get(url, {"formato": "csv"})
        testo = b"".join(csv).decode("utf-8-sig")
        self.assertIn("Acme Patch late", testo)
        self.assertNotIn("Acme Patch done", testo)
        self.assertContains(self.client.get(reverse("security:watchguard_pc")), url)
        self.assertContains(self.client.get(reverse("security:report") + "?period=last_30"), "Patch (WatchGuard)")
        self.assertEqual(self.client.get(reverse("security:report_pdf") + "?period=last_30").status_code, 200)

    def test_scheda_asset(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("assets:asset_view", args=[self.hub.pk]))
        self.assertContains(page, 'id="asset-patch"')
        self.assertContains(page, "Acme Patch late")
        self.assertContains(page, "scaduto da 186 gg")
        self.assertContains(page, "Acme Patch done")
        altro = Asset.objects.create(asset_tag="WGP-ALTRO", name="ALTRO", asset_type="PC")
        self.assertNotContains(self.client.get(reverse("assets:asset_view", args=[altro.pk])), 'id="asset-patch"')
