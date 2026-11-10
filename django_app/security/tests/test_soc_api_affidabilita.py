"""Affidabilità dei collegamenti esterni del SOC: WatchGuard, NVD/EPSS, MSRC, OSV, SearXNG, webhook Teams.

Dati sintetici, nessuna chiamata di rete (sessioni e funzioni HTTP sostituite da finti).
"""
import io
import urllib.error
from datetime import timedelta
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    MicrosoftCvrfMese,
    SecurityCenterSetting,
    SecurityCveRecord,
    SecurityExternalFeedCache,
    SecurityVulnerabilityFinding,
    WatchGuardDispositivo,
    WatchGuardPatch,
)
from security.services import cve_feeds, notifications, patch_kb, ricerca_web, watchguard_api
from security.services import dipendenze_portale as dp

CFG = {"url_api": "https://api.deu.cloud.watchguard.com", "account_id": "ACC-1234567", "access_id": "id-sintetico",
       "password": "pw-sintetica", "api_key": "chiave-sintetica"}


class _Resp:
    def __init__(self, status=200, body=None, headers=None, testo=False):
        self.status_code, self._body, self.testo = status, body, testo
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}

    def json(self):
        if self.testo:
            raise ValueError("non JSON")
        return self._body


# --- WatchGuard ----------------------------------------------------------------------------------

class WatchGuardClientTests(TestCase):
    def setUp(self):
        watchguard_api._TOKEN.clear()
        self.client_wg = watchguard_api.Client(dict(CFG))
        self.http = mock.Mock()
        self.client_wg.http = self.http

    def test_401_un_solo_rinnovo_del_token_e_un_nuovo_tentativo(self):
        self.http.post.side_effect = [_Resp(body={"access_token": "t1", "expires_in": 3600}),
                                      _Resp(body={"access_token": "t2", "expires_in": 3600})]
        self.http.get.side_effect = [_Resp(401, {}), _Resp(body={"data": [], "total_items": 0})]
        self.assertEqual(self.client_wg.get("/devices"), {"data": [], "total_items": 0})
        self.assertEqual(self.http.post.call_count, 2)
        self.assertEqual(self.http.get.call_args.kwargs["headers"]["Authorization"], "Bearer t2")

    def test_401_anche_col_token_nuovo_si_ferma(self):
        self.http.post.return_value = _Resp(body={"access_token": "t1"})
        self.http.get.return_value = _Resp(401, {})
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "anche con un token nuovo"):
            self.client_wg.get("/devices")
        self.assertEqual(self.http.get.call_count, 2)

    def test_token_riusato_nello_stesso_giro(self):
        self.http.post.return_value = _Resp(body={"access_token": "t1", "expires_in": 3600})
        self.http.get.return_value = _Resp(body={"data": []})
        self.client_wg.get("/devices")
        self.client_wg.get("/patchavailability")
        self.assertEqual(self.http.post.call_count, 1)

    def test_errori_attribuiti_alla_causa_giusta(self):
        self.http.post.side_effect = requests.exceptions.ProxyError("proxy giù")
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "proxy del server"):
            self.client_wg.get("/devices")
        self.http.post.side_effect = requests.exceptions.SSLError("cert")
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "certificato HTTPS"):
            self.client_wg.get("/devices")
        self.http.post.side_effect = None
        self.http.post.return_value = _Resp(407, headers={"Content-Type": "text/html"})
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "407"):
            self.client_wg.get("/devices")
        # 403 di un proxy (HTML) non è «password non valida»
        self.http.post.return_value = _Resp(403, headers={"Content-Type": "text/html", "Server": "squid"})
        with self.assertRaises(watchguard_api.WatchGuardError) as ctx:
            self.client_wg.get("/devices")
        self.assertIn("squid", str(ctx.exception))
        self.assertNotIn("password non validi", str(ctx.exception))

    def test_risposta_non_json_dice_chi_risponde(self):
        self.http.post.return_value = _Resp(body={"access_token": "t1"})
        self.http.get.return_value = _Resp(200, testo=True, headers={"Content-Type": "text/html", "Server": "proxy-x"})
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "proxy-x"):
            self.client_wg.get("/devices")
        self.http.get.side_effect = requests.exceptions.ConnectionError("giù")
        with self.assertRaisesRegex(watchguard_api.WatchGuardError, "non raggiungibile"):
            self.client_wg.get("/devices")


class WatchGuardLetturaTroncataTests(TestCase):
    def test_pagine_finite_senza_fine_e_errore(self):
        pagina = {"data": [{"device_id": str(i)} for i in range(watchguard_api.PAGINA)]}
        with mock.patch.object(watchguard_api, "get", return_value=pagina), mock.patch.object(watchguard_api, "MAX_PAGINE", 2):
            with self.assertRaisesRegex(watchguard_api.WatchGuardError, "troncata"):
                watchguard_api.get_all("/devices")

    def test_total_items_piu_alto_delle_righe_lette_e_errore(self):
        with mock.patch.object(watchguard_api, "get", return_value={"data": [{"device_id": "1"}], "total_items": 5}):
            with self.assertRaisesRegex(watchguard_api.WatchGuardError, "lette 1 righe su 5"):
                watchguard_api.get_all("/devices")

    def test_lettura_completa(self):
        with mock.patch.object(watchguard_api, "get", return_value={"data": [{"device_id": "1"}], "total_items": 1}):
            self.assertEqual(len(watchguard_api.get_all("/devices")), 1)

    def test_run_troncato_non_segna_spariti(self):
        WatchGuardDispositivo.objects.create(device_id="d1", host="pc-1", presente=True)
        WatchGuardPatch.objects.create(device_id="d1", patch_id="p1", host="pc-1", nome="Patch", presente=True)
        from security.services import soc_settings

        soc_settings.save({"watchguard.api.dispositivi": True, "watchguard.api.patch": True,
                           "watchguard.api.software": False, "watchguard.api.msrc": False}, None)
        finto = mock.Mock()
        finto.get.return_value = {"data": [{"device_id": "x"}], "total_items": 99}
        with mock.patch.object(watchguard_api, "configurato", return_value=True), \
                mock.patch.object(watchguard_api, "Client", return_value=finto) as costruttore:
            out = watchguard_api.run()
        self.assertEqual(costruttore.call_count, 1)  # una sessione per tutto il giro
        finto.close.assert_called_once()
        self.assertFalse(out["ok"])
        self.assertIn("troncata", out["dispositivi"]["errore"])
        self.assertIn("troncata", out["patch"]["errore"])
        self.assertTrue(WatchGuardDispositivo.objects.get().presente)
        self.assertTrue(WatchGuardPatch.objects.get().presente)


class WatchGuardPatchBloccoTests(TestCase):
    def test_rivista_riapre_mantiene_esito_e_crea_le_nuove(self):
        ieri = timezone.now() - timedelta(days=1)
        vecchia = WatchGuardPatch.objects.create(device_id="d1", patch_id="p1", host="pc-1", nome="Vecchio nome",
                                                 presente=False, chiusa_il=ieri, vista_il=ieri, esito=4, esito_il=ieri)
        aperta = WatchGuardPatch.objects.create(device_id="d1", patch_id="p2", host="pc-1", nome="Sparita",
                                                presente=True, vista_il=ieri)
        righe = [{"device_id": "d1", "patch_id": "p1", "host_name": "PC-1", "patch_name": "Nuovo nome",
                  "patch_cve_ids": ["CVE-2099-0001"]}] + [
            {"device_id": f"d{n}", "patch_id": f"q{n}", "host_name": f"PC-{n}", "patch_name": f"Patch {n}"} for n in range(2, 1202)]
        out = watchguard_api.sincronizza_patch(righe=righe)
        self.assertEqual(out, {"patch": 1201, "chiuse": 1})
        vecchia.refresh_from_db()
        self.assertEqual((vecchia.presente, vecchia.chiusa_il, vecchia.nome, vecchia.esito), (True, None, "Nuovo nome", 4))
        self.assertEqual(vecchia.cve, "|CVE-2099-0001|")
        aperta.refresh_from_db()
        self.assertFalse(aperta.presente)
        self.assertIsNotNone(aperta.chiusa_il)
        self.assertEqual(WatchGuardPatch.objects.count(), 1202)

    def test_righe_doppie_nella_risposta_una_sola_patch(self):
        riga = {"device_id": "d1", "patch_id": "p1", "host_name": "PC-1", "patch_name": "Patch"}
        self.assertEqual(watchguard_api.sincronizza_patch(righe=[riga, dict(riga)])["patch"], 1)
        self.assertEqual(WatchGuardPatch.objects.count(), 1)


# --- NVD / EPSS ----------------------------------------------------------------------------------

class CveFeedsTests(TestCase):
    def test_200_non_json_dice_chi_ha_risposto(self):
        with mock.patch.object(cve_feeds, "http_get", return_value=(200, None, {"Content-Type": "text/html", "Server": "squid"})):
            with self.assertRaisesRegex(cve_feeds.FeedError, "squid"):
                cve_feeds._get_json(cve_feeds.KEV_URL, sleep=lambda s: None)

    def test_retry_after_rispettato(self):
        pause = []
        risposte = iter([(429, None, {"Retry-After": "13"}), (200, {"ok": 1}, {})])
        with mock.patch.object(cve_feeds, "http_get", side_effect=lambda *a, **k: next(risposte)):
            self.assertEqual(cve_feeds._get_json(cve_feeds.EPSS_URL, sleep=pause.append), {"ok": 1})
        self.assertEqual(pause, [13])

    def test_retry_after_troppo_lungo_ferma_il_giro(self):
        with mock.patch.object(cve_feeds, "http_get", return_value=(429, None, {"Retry-After": "3600"})):
            with self.assertRaises(cve_feeds.BudgetExhausted):
                cve_feeds._get_json(cve_feeds.EPSS_URL, sleep=lambda s: None)

    def test_api_key_rifiutata_niente_retry_e_giro_fermo(self):
        cve_feeds.set_nvd_api_key("00000000-0000-4000-8000-000000000000")
        chiamate = []

        def finto(url, params=None, headers=None, timeout=None):
            chiamate.append(url)
            if url == cve_feeds.NVD_CVE_URL:
                return 404, None, {"Content-Type": "application/json"}
            return 200, ({"vulnerabilities": []} if url == cve_feeds.KEV_URL else {"data": []})

        for n in range(1, 4):
            SecurityCveRecord.objects.create(cve_id=f"CVE-2099-03{n:02d}")
        with mock.patch.object(cve_feeds, "http_get", finto), mock.patch.object(cve_feeds, "get_epss_enabled", return_value=False):
            out = cve_feeds.run_enrichment(sleep=lambda s: None, recompute=lambda: "test")
        self.assertEqual(chiamate.count(cve_feeds.NVD_CVE_URL), 1)
        self.assertTrue(any("API key" in e for e in out["errors"]))
        self.assertFalse(SecurityCveRecord.objects.exclude(nvd_error="").exists())  # la colpa non è delle CVE

    def test_cve_in_errore_rimandata_di_un_giorno(self):
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0401")
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0402")
        with mock.patch.object(cve_feeds, "http_get", return_value=(500, None)):
            cve_feeds.enrich_cve("CVE-2099-0401", sleep=lambda s: None)
        self.assertEqual(cve_feeds.stale_cve_ids(10), ["CVE-2099-0402"])
        SecurityExternalFeedCache.objects.filter(feed="nvd_rinvio").update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(cve_feeds.stale_cve_ids(10), ["CVE-2099-0401", "CVE-2099-0402"])

    def test_crea_solo_le_cve_mancanti(self):
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0501", cvss=5.0)
        self.assertEqual(cve_feeds._crea_mancanti(["CVE-2099-0501", "CVE-2099-0502"]), 1)
        self.assertEqual(SecurityCveRecord.objects.get(cve_id="CVE-2099-0501").cvss, 5.0)
        self.assertEqual(cve_feeds._crea_mancanti(["CVE-2099-0501", "CVE-2099-0502"]), 0)

    def test_epss_aggiorna_solo_i_valori_cambiati(self):
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0601", epss=0.5, epss_percentile=0.9)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0602", epss=0.1, epss_percentile=0.2)
        body = {"data": [{"cve": "CVE-2099-0601", "epss": "0.5", "percentile": "0.9"},
                         {"cve": "CVE-2099-0602", "epss": "0.3", "percentile": "0.4"}]}
        with mock.patch.object(cve_feeds, "http_get", return_value=(200, body)):
            n = cve_feeds.refresh_epss(["CVE-2099-0601", "CVE-2099-0602"], sleep=lambda s: None)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(SecurityCveRecord.objects.get(cve_id="CVE-2099-0602").epss, 0.3)

    def test_budget_controllato_anche_fra_i_passi_db(self):
        clock = [0.0]

        def kev(url, params=None, headers=None, timeout=None):
            clock[0] += 100  # il catalogo KEV arriva dopo il budget
            return 200, {"vulnerabilities": []}

        with mock.patch.object(cve_feeds, "http_get", kev):
            out = cve_feeds.run_enrichment(time_budget_seconds=90, clock=lambda: clock[0], sleep=lambda s: None,
                                           recompute=lambda: "test")
        self.assertTrue(any("budget" in e for e in out["errors"]))
        self.assertEqual(out["recompute"], "test")


class NvdKeyViewTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create(username="nvd_admin", is_staff=True, is_superuser=True))

    def test_formato_uuid_obbligatorio(self):
        url = reverse("security:software_mapping")
        self.client.post(url, {"action": "nvd_key", "nvd_key": "chiave incollata male"})
        self.assertFalse(SecurityCenterSetting.objects.filter(key=cve_feeds.NVD_KEY_SETTING).exists())
        self.client.post(url, {"action": "nvd_key", "nvd_key": "  00000000-0000-4000-8000-00000000abcd  "})
        self.assertEqual(cve_feeds.nvd_api_key(), "00000000-0000-4000-8000-00000000abcd")


# --- MSRC ----------------------------------------------------------------------------------------

class MsrcTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.chiamate = []

    def _scarica(self, mesi, aggiornato="2099-01-01T00:00:00Z"):
        def scarica(url):
            self.chiamate.append(url)
            if url.endswith("/updates"):
                return {"value": [{"ID": m, "InitialReleaseDate": (self.now - timedelta(days=i * 30)).isoformat(),
                                   "CurrentReleaseDate": aggiornato} for i, m in enumerate(mesi)]}
            return {"Vulnerability": []}
        return scarica

    def test_al_massimo_due_documenti_per_giro_i_piu_recenti(self):
        out = patch_kb.sincronizza_msrc(self.now, scarica=self._scarica(["2099-Mar", "2099-Feb", "2099-Jan"]))
        self.assertEqual(out["documenti_letti"], ["2099-Mar", "2099-Feb"])
        self.assertEqual(out["documenti_rimandati"], 1)
        out = patch_kb.sincronizza_msrc(self.now, scarica=self._scarica(["2099-Mar", "2099-Feb", "2099-Jan"]))
        self.assertEqual(out["documenti_letti"], ["2099-Jan"])

    def test_tempo_finito_rimanda_i_documenti(self):
        out = patch_kb.sincronizza_msrc(self.now, scarica=self._scarica(["2099-Mar"]),
                                        clock=iter([0, patch_kb.MSRC_TEMPO_MAX + 1]).__next__)
        self.assertEqual((out["documenti_letti"], out["documenti_rimandati"]), ([], 1))

    def test_data_microsoft_non_leggibile_non_blocca_per_sempre(self):
        patch_kb.sincronizza_msrc(self.now, scarica=self._scarica(["2099-Mar"], aggiornato="non-una-data"))
        self.assertIsNone(MicrosoftCvrfMese.objects.get().aggiornato_il)
        out = patch_kb.sincronizza_msrc(self.now + timedelta(days=2), scarica=self._scarica(["2099-Mar"], aggiornato="non-una-data"))
        self.assertEqual(out["documenti_letti"], [])
        out = patch_kb.sincronizza_msrc(self.now + timedelta(days=8), scarica=self._scarica(["2099-Mar"], aggiornato="non-una-data"))
        self.assertEqual(out["documenti_letti"], ["2099-Mar"])

    def test_download_a_blocchi_su_file_temporaneo(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.iter_content.return_value = [b'{"Vulnerability":', b" []}"]
        with mock.patch("requests.get", return_value=resp) as get:
            self.assertEqual(patch_kb._scarica(f"{patch_kb.MSRC_BASE}/cvrf/2099-Mar"), {"Vulnerability": []})
        self.assertTrue(get.call_args.kwargs["stream"])


# --- OSV -----------------------------------------------------------------------------------------

_BOLL = {
    "PYSEC-2099-7": {"id": "PYSEC-2099-7", "aliases": ["GHSA-zzzz-yyyy-xxxx"]},
    "GHSA-zzzz-yyyy-xxxx": {"id": "GHSA-zzzz-yyyy-xxxx", "aliases": ["PYSEC-2099-7"], "database_specific": {"severity": "HIGH"}},
}


class OsvTests(TestCase):
    def _osv(self, rotti=(), pagine=False, chiamate=None):
        def http(metodo, url, **kw):
            if chiamate is not None:
                chiamate.append(url)
            if url == dp.OSV_BATCH_URL:
                q = kw["json"]["queries"][0]
                if pagine and not q.get("page_token"):
                    return {"results": [{"vulns": [{"id": "PYSEC-2099-7"}], "next_page_token": "t2"}]}
                if pagine:
                    return {"results": [{"vulns": [{"id": "GHSA-zzzz-yyyy-xxxx"}]}]}
                return {"results": [{"vulns": [{"id": "PYSEC-2099-7"}, {"id": "GHSA-zzzz-yyyy-xxxx"}]}]}
            vid = url.rsplit("/", 1)[1]
            if vid in rotti:
                raise dp.OsvError("OSV ha risposto 503")
            return _BOLL[vid]
        return http

    def test_next_page_token_seguito(self):
        with mock.patch.object(dp, "_http", self._osv(pagine=True)):
            self.assertEqual(dp.interroga_osv({"beta-lib": "1.0"}), {"beta-lib": ["PYSEC-2099-7", "GHSA-zzzz-yyyy-xxxx"]})

    def test_bollettini_non_letti_non_risolvono_e_non_duplicano(self):
        with mock.patch.object(dp, "_http", self._osv()):
            dp.run({"beta-lib": "1.0"})
        self.assertEqual(dp.aperte().count(), 1)
        SecurityExternalFeedCache.objects.filter(feed=dp.CACHE_FEED).delete()
        with mock.patch.object(dp, "_http", self._osv(rotti=("GHSA-zzzz-yyyy-xxxx", "PYSEC-2099-7"))):
            out = dp.run({"beta-lib": "1.0"})
        self.assertIn("non letti", out["errore"])
        self.assertEqual(out["risolte"], 0)
        self.assertEqual(SecurityVulnerabilityFinding.objects.filter(source=dp.source()).count(), 1)
        self.assertEqual(dp.aperte().count(), 1)

    def test_bollettini_dalla_cache(self):
        chiamate = []
        with mock.patch.object(dp, "_http", self._osv(chiamate=chiamate)):
            dp.run({"beta-lib": "1.0"})
            dp.run({"beta-lib": "1.0"})
        self.assertEqual(sum(1 for u in chiamate if "/vulns/" in u), 2)  # solo al primo giro


# --- SearXNG e webhook ---------------------------------------------------------------------------

class SearxngTests(TestCase):
    def setUp(self):
        from security.services import soc_settings

        soc_settings.save({"ai.web.searxng_url": "http://searx.invalid"}, None)

    def test_stato_diverso_da_200_e_errore_e_niente_proxy(self):
        resp = _Resp(502, headers={"Content-Type": "text/html", "Server": "proxy-lan"})
        sessioni = []
        originale = requests.Session.__init__

        def init(self_s, *a, **k):
            originale(self_s, *a, **k)
            sessioni.append(self_s)

        with mock.patch.object(requests.Session, "__init__", init), \
                mock.patch.object(requests.Session, "get", return_value=resp), \
                mock.patch.object(ricerca_web, "_log") as log:
            self.assertEqual(ricerca_web.cerca("Veeam 0x80070005", scadenza=10**12), [])
        self.assertFalse(sessioni[0].trust_env)
        self.assertEqual(log.call_args.kwargs["status"], "error")
        self.assertIn("502", log.call_args.kwargs["error"])
        self.assertIn("proxy-lan", log.call_args.kwargs["error"])


class TeamsWebhookTests(TestCase):
    def test_solo_https(self):
        with self.assertRaisesRegex(RuntimeError, "https://"):
            notifications._post_teams_webhook("http://hooks.example.test/x", "s", "b", "high")

    def test_redirect_non_seguito(self):
        errore = urllib.error.HTTPError("https://hooks.example.test/x", 302, "Found", {}, io.BytesIO(b""))
        apri = mock.Mock(side_effect=errore)
        with mock.patch("urllib.request.build_opener", return_value=mock.Mock(open=apri)) as costruisci:
            with self.assertRaisesRegex(RuntimeError, "reindirizzamento"):
                notifications._post_teams_webhook("https://hooks.example.test/x", "s", "b", "high")
        self.assertIsInstance(costruisci.call_args.args[0], notifications._NoRedirect)

    def test_gestore_non_segue_redirect(self):
        self.assertIsNone(notifications._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://altro.test/"))
