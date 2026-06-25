"""Test F7 — API ninja, archivio/storico consultabile, export, azioni SSR."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import MOD133, Specifica

User = get_user_model()
API = "/gestione-specifiche/api"


class _Base(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("f7_su", "s@x.it", "x")
        self.appr = User.objects.create_superuser("f7_appr", "a@x.it", "x")
        self.client.force_login(self.su)

    def _csrf(self):
        self.client.get(reverse("gestione_specifiche:lista"))
        return self.client.cookies["csrftoken"].value

    def _in_validita(self, codice):
        spec = Specifica.objects.create(codice=codice, titolo="T", cliente="ACME")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        mod = spec.mod133
        mod.compilatore = self.su
        mod.approvatore = self.appr
        mod.esito = C.ESITO_APPROVATO
        mod.save()
        spec.approva_flow_down(attore=self.appr)
        spec.save()
        return spec


class ApiTests(_Base):
    def test_lista_e_filtri(self):
        Specifica.objects.create(codice="SP-API-1", titolo="Alpha", cliente="ACME")
        Specifica.objects.create(codice="SP-API-9", titolo="Beta", cliente="OTHER")
        r = self.client.get(f"{API}/specifiche")
        self.assertEqual(r.status_code, 200)
        codes = [d["codice"] for d in r.json()]
        self.assertIn("SP-API-1", codes)
        r2 = self.client.get(f"{API}/specifiche", {"cliente": "ACME"})
        codes2 = [d["codice"] for d in r2.json()]
        self.assertIn("SP-API-1", codes2)
        self.assertNotIn("SP-API-9", codes2)

    def test_dettaglio_ed_eventi(self):
        spec = Specifica.objects.create(codice="SP-API-2", titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        r = self.client.get(f"{API}/specifiche/{spec.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["codice"], "SP-API-2")
        r2 = self.client.get(f"{API}/specifiche/{spec.pk}/eventi")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(any(e["trigger"] == "avvia_flow_down" for e in r2.json()))

    def test_transizione_ok(self):
        spec = Specifica.objects.create(codice="SP-API-3", titolo="T")
        token = self._csrf()
        r = self.client.post(
            f"{API}/specifiche/{spec.pk}/transizione",
            data=json.dumps({"azione": "avvia_flow_down"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["stato"], C.STATO_FLOW_DOWN)

    def test_transizione_illegale_400(self):
        spec = Specifica.objects.create(codice="SP-API-4", titolo="T")
        token = self._csrf()
        r = self.client.post(
            f"{API}/specifiche/{spec.pk}/transizione",
            data=json.dumps({"azione": "approva_flow_down"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_auth_required(self):
        self.client.logout()
        r = self.client.get(f"{API}/specifiche")
        self.assertIn(r.status_code, (401, 403))


class ArchivioStoricoTests(_Base):
    def test_archivio_include_storico(self):
        Specifica.objects.create(codice="SP-ATT", titolo="T")  # bozza = attiva
        sup = Specifica.objects.create(codice="SP-TERM", titolo="T")
        sup.annulla(attore=self.su, motivo="non valida")
        sup.save()  # ANNULLATO (terminale)
        r = self.client.get(reverse("gestione_specifiche:lista"))
        self.assertNotContains(r, "SP-TERM")
        r2 = self.client.get(reverse("gestione_specifiche:lista") + "?storico=1")
        self.assertContains(r2, "SP-TERM")

    def test_filtro_per_stato_mostra_terminale(self):
        sup = Specifica.objects.create(codice="SP-TERM2", titolo="T")
        sup.annulla(attore=self.su, motivo="x")
        sup.save()
        r = self.client.get(reverse("gestione_specifiche:lista"), {"stato": C.STATO_ANNULLATO})
        self.assertContains(r, "SP-TERM2")


class SchedaStoricoTests(_Base):
    def test_scheda_render_ed_eventi(self):
        spec = Specifica.objects.create(codice="SP-ST", titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        r = self.client.get(reverse("gestione_specifiche:scheda_storico", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cronologia eventi")
        self.assertContains(r, "avvia_flow_down")

    def test_ricostruzione_punto_nel_tempo(self):
        spec = self._in_validita("SP-PIT")
        r = self.client.get(reverse("gestione_specifiche:scheda_storico", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ricostruzione punto-nel-tempo")
        self.assertContains(r, "SP-PIT")

    def test_catena_revisioni(self):
        prev = self._in_validita("SP-CAT")
        new = Specifica.objects.create(codice="SP-CAT", revisione="1", titolo="T",
                                       revisione_precedente=prev)
        r = self.client.get(reverse("gestione_specifiche:scheda_storico", args=[new.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Timeline revisioni")
        self.assertContains(r, "r.1")


class ExportTests(_Base):
    def test_export_csv(self):
        spec = Specifica.objects.create(codice="SP-CSV", titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        r = self.client.get(reverse("gestione_specifiche:storico_export_csv", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        self.assertIn("avvia_flow_down", r.content.decode("utf-8"))

    def test_export_pdf(self):
        spec = Specifica.objects.create(codice="SP-PDF", titolo="T")
        r = self.client.get(reverse("gestione_specifiche:storico_export_pdf", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        content = b"".join(r.streaming_content)
        self.assertTrue(content.startswith(b"%PDF"))


class AzioniSSRTests(_Base):
    def _flow_down(self, codice):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        return spec

    def test_sospendi_e_ripristina(self):
        spec = self._flow_down("SP-SOSP")
        self.client.post(reverse("gestione_specifiche:sospendi", args=[spec.pk]), {"motivo": "riesame"})
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_SOSPESO)
        self.client.post(reverse("gestione_specifiche:ripristina", args=[spec.pk]), {"motivo": "ok"})
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_FLOW_DOWN)

    def test_sospendi_senza_motivo_non_cambia_stato(self):
        spec = self._flow_down("SP-SOSP2")
        self.client.post(reverse("gestione_specifiche:sospendi", args=[spec.pk]), {"motivo": ""})
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_FLOW_DOWN)

    def test_annulla(self):
        spec = Specifica.objects.create(codice="SP-ANN", titolo="T")
        self.client.post(reverse("gestione_specifiche:annulla", args=[spec.pk]), {"motivo": "errata"})
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_ANNULLATO)


class KpiDashboardTests(_Base):
    def test_kpi_render_vuoto(self):
        """La dashboard KPI rende anche senza dati (nessuna divisione per zero)."""
        r = self.client.get(reverse("gestione_specifiche:kpi"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Dashboard direzionale KPI")
        self.assertContains(r, "Distribuzione per stato")

    def test_kpi_con_dati(self):
        self._in_validita("SP-KPI-1")
        self._in_validita("SP-KPI-2")
        Specifica.objects.create(codice="SP-KPI-3", titolo="T", cliente="ACME")
        r = self.client.get(reverse("gestione_specifiche:kpi"))
        self.assertEqual(r.status_code, 200)
        # 2 specifiche in validità → compare nella distribuzione per stato
        self.assertContains(r, "In validità")
        self.assertContains(r, "OFI aperti per cliente")
