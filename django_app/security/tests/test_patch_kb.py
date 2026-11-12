"""Patch comprese in una più recente: build di Windows nel nome e sostituzioni del Security Update Guide. Dati sintetici."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from security.models import MicrosoftCvrfMese, MicrosoftKbSostituzione, SecurityCveRecord, WatchGuardPatch
from security.services import patch_kb, patch_sla, soc_settings, watchguard_api

VECCHIA = "October 13, 2099-KB9127648 (OS Builds 26200.9711 and 26100.9711)"
NUOVA = "October 26, 2099-KB9134133 (OS Builds 26200.9725 and 26100.9725) Out-of-band"


def _patch(host, nome, pid, cve="", kb=None, giorno=None, **kw):
    return WatchGuardPatch.objects.create(device_id=f"d-{host}", patch_id=pid, host=host, nome=nome, cve=cve,
                                          kb=patch_kb.kb_da_testo(nome) if kb is None else kb,
                                          rilasciata_il=giorno, **kw)


def _cvrf(*coppie):
    return {"Vulnerability": [{"Remediations": [
        {"Type": 2, "Description": {"Value": kb}, "Supercedence": sost} for kb, sost in coppie
    ] + [{"Type": 2, "Description": {"Value": "Release Notes"}}, {"Type": 3, "URL": "https://example.invalid"}]}]}


class LetturaNomeTests(TestCase):
    def test_kb_da_nome_o_file(self):
        self.assertEqual(patch_kb.kb_da_testo(NUOVA), "KB9134133")
        self.assertEqual(patch_kb.kb_da_testo("", "windows11.0-kb9134133-x64_0e59.msu"), "KB9134133")
        self.assertEqual(patch_kb.kb_da_testo("KB9126649: Servicing stack update"), "KB9126649")
        self.assertEqual(patch_kb.kb_da_testo("Google Chrome 156.0.8078.74", "chrome.msi"), "")

    def test_build_da_nome(self):
        self.assertEqual(patch_kb.build_da_nome(NUOVA), {26200: 9725, 26100: 9725})
        self.assertEqual(patch_kb.build_da_nome("October 13, 2099-KB9126868 (OS Build 14393.9612)"), {14393: 9612})
        self.assertEqual(patch_kb.build_da_nome("26H2"), {})


class ComprenseTests(TestCase):
    def test_cumulativo_con_build_piu_alto_comprende_il_vecchio(self):
        vecchia = _patch("pc-kb-01", VECCHIA, "p1", cve="|CVE-2099-0001|", giorno=date(2099, 10, 13))
        nuova = _patch("pc-kb-01", NUOVA, "p2", giorno=date(2099, 10, 26))
        altro_ramo = _patch("pc-kb-01", "October 13, 2099-KB9126868 (OS Build 14393.9612)", "p3")
        out = patch_kb.comprese(WatchGuardPatch.objects.all())
        self.assertEqual(out[vecchia.pk]["in"].pk, nuova.pk)
        self.assertIn("build", out[vecchia.pk]["perche"])
        self.assertNotIn(nuova.pk, out)
        self.assertNotIn(altro_ramo.pk, out)

    def test_un_anteprima_non_si_propone_al_posto_di_un_altra(self):
        vecchia = _patch("pc-kb-01", VECCHIA, "p1")
        nuova = _patch("pc-kb-01", NUOVA, "p2")
        preview = _patch("pc-kb-01", "October 28, 2099-KB9127936 (OS Builds 26200.9818) Preview", "p3")
        out = patch_kb.comprese(WatchGuardPatch.objects.all())
        self.assertEqual(out[vecchia.pk]["in"].pk, nuova.pk)
        self.assertNotIn(nuova.pk, out)
        self.assertNotIn(preview.pk, out)

    def test_solo_sullo_stesso_pc(self):
        vecchia = _patch("pc-kb-01", VECCHIA, "p1")
        _patch("pc-kb-02", NUOVA, "p2")
        self.assertNotIn(vecchia.pk, patch_kb.comprese(WatchGuardPatch.objects.all()))

    def test_sostituzioni_microsoft_anche_a_catena(self):
        MicrosoftKbSostituzione.objects.create(kb="KB9200003", sostituita="KB9200002", mese="2099-Oct")
        MicrosoftKbSostituzione.objects.create(kb="KB9200002", sostituita="KB9200001", mese="2099-Sep")
        vecchia = _patch("pc-kb-01", "KB9200001 - Security update for SQL Server 2099", "p1", cve="|CVE-2099-0002|")
        nuova = _patch("pc-kb-01", "KB9200003 - Security update for SQL Server 2099", "p2")
        out = patch_kb.comprese(WatchGuardPatch.objects.all())
        self.assertEqual(out[vecchia.pk]["in"].pk, nuova.pk)
        self.assertIn("Microsoft", out[vecchia.pk]["perche"])

    def test_la_catena_porta_alla_piu_recente(self):
        a = _patch("pc-kb-01", "October 1, 2099-KB9000001 (OS Build 26100.100)", "p1")
        _patch("pc-kb-01", "October 2, 2099-KB9000002 (OS Build 26100.200)", "p2", giorno=date(2099, 10, 2))
        c = _patch("pc-kb-01", "October 3, 2099-KB9000003 (OS Build 26100.300)", "p3", giorno=date(2099, 10, 3))
        self.assertEqual(patch_kb.comprese(WatchGuardPatch.objects.all())[a.pk]["in"].pk, c.pk)


class MsrcSyncTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.chiamate = []

    def _scarica(self, documenti, aggiornato):
        def scarica(url):
            self.chiamate.append(url)
            if url.endswith("/updates"):
                return {"value": [
                    {"ID": "2099-Oct", "InitialReleaseDate": (self.now - timedelta(days=20)).isoformat(),
                     "CurrentReleaseDate": aggiornato.isoformat()},
                    {"ID": "2001-Jan", "InitialReleaseDate": "2001-01-09T00:00:00Z", "CurrentReleaseDate": "2001-01-09T00:00:00Z"},
                    {"ID": "1999-Sep", "DocumentTitle": "Mariner Release Notes", "InitialReleaseDate": "1999-09-02T00:00:00Z"},
                ]}
            return documenti[url.rsplit("/", 1)[1]]
        return scarica

    def test_legge_solo_i_documenti_recenti_e_aggiornati(self):
        doc = _cvrf(("9134001", "9124001"), ("9134001", "9124001"), ("9134002", "9124002, 9114002"))
        aggiornato = self.now - timedelta(days=1)
        out = patch_kb.sincronizza_msrc(self.now, scarica=self._scarica({"2099-Oct": doc}, aggiornato))
        self.assertEqual(out["documenti_letti"], ["2099-Oct"])
        self.assertEqual(out["sostituzioni_nuove"], 3)
        self.assertTrue(MicrosoftKbSostituzione.objects.filter(kb="KB9134002", sostituita="KB9114002").exists())
        self.assertEqual(MicrosoftCvrfMese.objects.get().sostituzioni, 3)
        # stesso CurrentReleaseDate: non si riscarica
        self.chiamate.clear()
        out = patch_kb.sincronizza_msrc(self.now + timedelta(days=2), scarica=self._scarica({"2099-Oct": doc}, aggiornato))
        self.assertEqual((out["documenti_letti"], self.chiamate[-1].endswith("/updates")), ([], True))
        # aggiornato da Microsoft ma letto da poco: al massimo una volta al giorno
        out = patch_kb.sincronizza_msrc(self.now + timedelta(hours=2), scarica=self._scarica({"2099-Oct": doc}, self.now))
        self.assertEqual(out["documenti_letti"], [])

    def test_scarica_solo_dall_api_microsoft(self):
        with self.assertRaises(ValueError):
            patch_kb._scarica("https://example.com/cvrf/v3.0/updates")


class SincronizzazioneEPagineTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="KB-1", name="pc-kb-01")
        admin = get_user_model().objects.create(username="kb_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)

    def test_sync_salva_kb_link_e_riavvio(self):
        watchguard_api.sincronizza_patch(righe=[
            {"device_id": "d1", "patch_id": "p1", "host_name": "PC-KB-01", "patch_name": "Aggiornamento senza KB nel nome",
             "local_filename": "windows11.0-kb9134133-x64.msu", "automatic_reboot": True,
             "download_url": "https://catalog.example.invalid/windows11.0-kb9134133-x64.msu"},
            {"device_id": "d1", "patch_id": "p2", "host_name": "PC-KB-01", "patch_name": "Acme Viewer 2.0",
             "download_url": "javascript:alert(1)"}])
        p1, p2 = WatchGuardPatch.objects.order_by("patch_id")
        self.assertEqual((p1.kb, p1.nome_file, p1.riavvio_automatico), ("KB9134133", "windows11.0-kb9134133-x64.msu", True))
        self.assertTrue(p1.download_url.startswith("https://"))
        self.assertEqual((p2.kb, p2.download_url, p2.riavvio_automatico), ("", "", None))

    def test_run_legge_microsoft_solo_con_l_interruttore(self):
        soc_settings.save({"watchguard.api.patch": True}, None)
        self.assertNotIn("msrc", watchguard_api.run())  # senza credenziali si ferma prima

    def test_pagina_patch_comprese_e_ricerca(self):
        _patch("pc-kb-01", VECCHIA, "p1", cve="|CVE-2099-0001|", giorno=date(2099, 10, 13), hub_asset=self.pc)
        _patch("pc-kb-01", NUOVA, "p2", giorno=date(2099, 10, 26), hub_asset=self.pc,
               download_url="https://catalog.example.invalid/x.msu", nome_file="x.msu")
        _patch("pc-kb-01", "Acme Viewer 2.0", "p3", cve="|CVE-2099-0003|", hub_asset=self.pc)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", kev=True)
        url = reverse("security:watchguard_pc")
        page = self.client.get(url)
        self.assertContains(page, "+1 CVE delle precedenti")
        self.assertContains(page, "Compresa in KB9134133")
        # la nuova eredita la CVE sfruttata della vecchia: è la prima da installare
        nomi = [g["nome"] for g in page.context["patch"]]
        self.assertEqual(nomi[0], NUOVA)
        self.assertEqual(nomi[-1], VECCHIA)
        # il dettaglio è nel pannello laterale
        pannello = reverse("security:preview_patch")
        vecchia, nuova = page.context["patch"][-1], page.context["patch"][0]
        self.assertContains(page, f'{pannello}?id={nuova["id"]}')
        dettaglio = self.client.get(pannello, {"id": vecchia["id"]})
        self.assertContains(dettaglio, "Già compresa in <a href=\"?q=KB9134133\">KB9134133</a> (1 PC)")
        dettaglio = self.client.get(pannello, {"id": nuova["id"]})
        self.assertContains(dettaglio, "Comprende anche: <a href=\"?q=KB9127648\">KB9127648</a> (1 PC)")
        self.assertContains(dettaglio, "Scarica a mano (x.msu)")
        self.assertContains(dettaglio, "Apri un ticket per 1 PC")
        self.assertEqual(self.client.get(pannello, {"id": "inesistente"}).status_code, 404)
        # filtri: solo CVE sfruttate, nascondi le già comprese
        self.assertEqual({g["nome"] for g in self.client.get(url, {"kev": "1"}).context["patch"]}, {NUOVA, VECCHIA})
        self.assertEqual([g["nome"] for g in self.client.get(url, {"criticita": "204"}).context["patch"]], [])
        self.assertNotIn(VECCHIA, [g["nome"] for g in self.client.get(url, {"comprese": "0"}).context["patch"]])
        # ricerca per CVE: trova la patch che la corregge e quella che la comprende
        page = self.client.get(url, {"q": "cve-2099-0001"})
        self.assertEqual({g["nome"] for g in page.context["patch"]}, {VECCHIA, NUOVA})
        page = self.client.get(url, {"q": "KB9127648"})
        self.assertEqual({g["nome"] for g in page.context["patch"]}, {VECCHIA, NUOVA})
        page = self.client.get(url, {"q": "nessuna"})
        self.assertContains(page, "Nessun risultato per «nessuna».")

    def test_scheda_asset_e_pannello_cve(self):
        vecchia = _patch("pc-kb-01", VECCHIA, "p1", cve="|CVE-2099-0001|", hub_asset=self.pc, disponibilita=1)
        _patch("pc-kb-01", NUOVA, "p2", hub_asset=self.pc)
        aperte = patch_sla.per_asset(self.pc)["aperte"]
        self.assertEqual(aperte[-1]["p"].pk, vecchia.pk)
        self.assertEqual(aperte[-1]["compresa"]["in"].kb, "KB9134133")
        p = watchguard_api.patch_aperte_per_cve({"CVE-2099-0001"})[("CVE-2099-0001", "pc-kb-01")]
        self.assertEqual(p.compresa["in"].kb, "KB9134133")
