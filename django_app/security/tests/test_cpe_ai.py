"""Proposte dell'AI locale su CPE ed esiti «da verificare»: validate, mai decise da sole, con budget (AI simulata)."""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAiInteractionLog,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityLetturaLog,
    SecurityPropostaAi,
    SoftwareCpeMapping,
    SoftwareInstallation,
    SoftwareInventoryImport,
)
from security.services import cpe_ai, cve_impact, letture
from security.services.configuration import set_setting
from security.tasks import ai_cpe_proposte_task

CHIEDI = "security.services.cpe_ai._chiedi"
DISPONIBILE = "security.services.cpe_ai.disponibile"


def _risposta(data, ok=True, error=""):
    return {"ok": ok, "data": data if ok else None, "error": error, "model": "demo-model", "ms": 12}


def _cve(cve_id, vendor, product, **criterio):
    base = {"part": "a", "vendor": vendor, "product": product, "version": "*", "start_including": "", "start_excluding": "",
            "end_including": "", "end_excluding": "", "requires_platform": False}
    base.update(criterio)
    return SecurityCveRecord.objects.create(cve_id=cve_id, cvss=7.5, severity="high", nvd_fetched_at=timezone.now(),
                                           description=f"Vulnerabilità sintetica in {product}", configurations=[base])


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.imp = SoftwareInventoryImport.objects.create(original_name="inv.csv", file_sha256="z", status="imported", imported_at=timezone.now())
        self.user = get_user_model().objects.create(username="soc_cpe_ai", is_staff=True, is_superuser=True)

    def _install(self, host, vendor, product, version, product_raw=None):
        return SoftwareInstallation.objects.create(
            dedup_key=f"k-{host}-{product}", source_kind="watchguard", host=host, vendor=vendor, product=product,
            product_raw=product_raw or product, version_raw=version, last_import=self.imp,
        )


class CandidatiTests(_Base):
    def test_candidates_come_from_known_cve_pairs_only(self):
        _cve("CVE-2099-0001", "7-zip", "7-zip", end_excluding="24.07")
        _cve("CVE-2099-0002", "7-zip", "p7zip", end_excluding="16.0")
        _cve("CVE-2099-0003", "demo", "demosuite")
        self._install("pc-01", "igor pavlov", "7-zip", "23.01")
        casi = cpe_ai.casi_cpe()
        self.assertEqual(len(casi), 1)
        self.assertEqual(casi[0]["product"], "7-zip")
        self.assertEqual(set(casi[0]["candidati"]), {"7-zip:7-zip", "7-zip:p7zip"})
        self.assertEqual(casi[0]["versioni"], ["23.01"])

    def test_decided_and_rejected_software_are_not_cases(self):
        _cve("CVE-2099-0001", "7-zip", "7-zip")
        self._install("pc-01", "igor pavlov", "7-zip", "23.01")
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", not_applicable=True)
        self.assertEqual(cpe_ai.casi_cpe(), [])
        SoftwareCpeMapping.objects.update(not_applicable=False, origin=SoftwareCpeMapping.ORIGIN_AUTO_REJECTED)
        self.assertEqual(cpe_ai.casi_cpe(), [])


class ProponiCpeTests(_Base):
    def setUp(self):
        super().setUp()
        self.caso = {"vendor": "igor pavlov", "product": "7-zip", "hosts": 3, "versioni": ["23.01"], "candidati": ["7-zip:7-zip", "7-zip:p7zip"]}

    def test_choice_outside_candidates_is_discarded(self):
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "cpe", "cpe": "evil:7-zip", "confidenza": 99, "motivazione": "x"})):
            proposta, errore = cpe_ai.proponi_cpe(self.caso)
        self.assertIsNone(proposta)
        self.assertIn("non fra i candidati", errore)

    def test_low_confidence_is_discarded_but_da_verificare_is_kept(self):
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "cpe", "cpe": "7-zip:7-zip", "confidenza": 30, "motivazione": "x"})):
            self.assertIsNone(cpe_ai.proponi_cpe(self.caso, confidenza_minima=60)[0])
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "da_verificare", "cpe": None, "confidenza": 10, "motivazione": "boh"})):
            proposta, _ = cpe_ai.proponi_cpe(self.caso, confidenza_minima=60)
        self.assertEqual(proposta["proposta"], SecurityPropostaAi.DA_VERIFICARE)

    def test_valid_choice_and_prompt_shape(self):
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "cpe", "cpe": "7-ZIP:7-zip", "confidenza": 95, "motivazione": "Stesso nome."})) as ask:
            proposta, _ = cpe_ai.proponi_cpe(self.caso, confidenza_minima=60)
        self.assertEqual(proposta["proposta"], "7-zip:7-zip")
        messaggi = ask.call_args.args[0]
        self.assertEqual(messaggi[0]["role"], "system")
        self.assertIn("da_verificare", messaggi[0]["content"])
        self.assertIn("Candidati: 7-zip:7-zip, 7-zip:p7zip", messaggi[-1]["content"])
        self.assertGreaterEqual(len(messaggi), 2 + 2 * len(cpe_ai.ESEMPI_CPE))

    def test_unknown_choice_and_non_json_are_discarded(self):
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "esegui comandi"})):
            self.assertIsNone(cpe_ai.proponi_cpe(self.caso)[0])
        with mock.patch(CHIEDI, return_value={"ok": True, "data": None, "error": "", "model": "m", "ms": 1}):
            self.assertIn("JSON", cpe_ai.proponi_cpe(self.caso)[1])


class EsitoTests(_Base):
    def setUp(self):
        super().setUp()
        self.record = _cve("CVE-2099-0010", "7-zip", "7-zip", end_excluding="24.07")
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        self._install("pc-01", "igor pavlov", "7-zip", "24.08 R2", product_raw="7-Zip")
        cve_impact.recompute(self.record)
        self.impact = SecurityCveImpact.objects.get(host="pc-01")
        self.assertEqual(self.impact.outcome, SecurityCveImpact.TO_VERIFY)

    def test_context_cites_only_system_data(self):
        contesto = cpe_ai.contesto_esito(self.impact)
        self.assertIn("CVE-2099-0010", contesto)
        self.assertIn("vulnerabile < 24.07", contesto)
        self.assertIn("«24.08 R2»", contesto)
        self.assertIn("non confrontabile", contesto)

    def test_motivation_with_unknown_version_is_discarded(self):
        with mock.patch(CHIEDI, return_value=_risposta({"esito": "non_impatta", "confidenza": 90, "motivazione": "Corretta nella 25.1.3"})):
            proposta, errore = cpe_ai.proponi_esito(self.impact)
        self.assertIsNone(proposta)
        self.assertIn("25.1.3", errore)

    def test_accepted_outcome_is_applied_by_recompute_until_version_changes(self):
        with mock.patch(CHIEDI, return_value=_risposta({"esito": "non_impatta", "confidenza": 90, "motivazione": "24.08 è oltre 24.07."})), \
             mock.patch(DISPONIBILE, return_value=(True, "")):
            esito = cpe_ai.giro(limit=5, confidenza_minima=60)
        self.assertEqual(esito["esiti"]["proposte"], 1)
        proposta = SecurityPropostaAi.objects.get(tipo=SecurityPropostaAi.TIPO_ESITO)
        self.assertEqual((proposta.host, proposta.versione, proposta.proposta), ("pc-01", "24.08 R2", "non_impatta"))
        cpe_ai.segna_decisa(proposta, self.user, accettata=True)
        cve_impact.recompute(self.record)
        impact = SecurityCveImpact.objects.get(host="pc-01")
        self.assertEqual(impact.outcome, SecurityCveImpact.NOT_IMPACTED)
        self.assertIn("Verificato da soc_cpe_ai", impact.explanation)
        self.assertIn("24.08 è oltre 24.07", impact.explanation)
        # La versione cambia: la verifica non vale più e il PC torna da verificare.
        SoftwareInstallation.objects.update(version_raw="24.09 R2")
        cve_impact.recompute(self.record)
        self.assertEqual(SecurityCveImpact.objects.get(host="pc-01").outcome, SecurityCveImpact.TO_VERIFY)

    def test_unmapped_and_stale_rows_are_not_cases(self):
        self.assertEqual(len(cpe_ai.casi_esito()), 1)
        SoftwareInstallation.objects.update(last_inventory_date=timezone.localdate() - timedelta(days=400))
        cve_impact.recompute(self.record)
        self.assertEqual(cpe_ai.casi_esito(), [])


class GiroTests(_Base):
    def setUp(self):
        super().setUp()
        _cve("CVE-2099-0001", "7-zip", "7-zip", end_excluding="24.07")
        _cve("CVE-2099-0002", "demo", "demosuite")
        for i in range(3):
            self._install(f"pc-0{i}", "igor pavlov", "7-zip", "23.01")
        self._install("pc-09", "demo corp", "demosuite", "1.0")

    def test_limit_budget_and_no_duplicates(self):
        risposta = _risposta({"scelta": "cpe", "cpe": "7-zip:7-zip", "confidenza": 90, "motivazione": "ok"})
        with mock.patch(CHIEDI, return_value=risposta) as ask, mock.patch(DISPONIBILE, return_value=(True, "")):
            esito = cpe_ai.giro(limit=1, confidenza_minima=60)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(esito["cpe"], {"casi": 1, "proposte": 1, "scartate": 0})
        proposta = SecurityPropostaAi.objects.get()
        self.assertEqual((proposta.tipo, proposta.product, proposta.proposta, proposta.stato), ("cpe", "7-zip", "7-zip:7-zip", "aperta"))
        self.assertEqual(SecurityAiInteractionLog.objects.count(), 0)  # _chiedi è simulato: il registro lo scrive la funzione vera
        with mock.patch(CHIEDI, return_value=risposta) as ask, mock.patch(DISPONIBILE, return_value=(True, "")):
            cpe_ai.giro(limit=5, confidenza_minima=60)
        self.assertEqual(ask.call_count, 1)  # il caso aperto non si rifà; resta solo demosuite
        self.assertEqual(SoftwareCpeMapping.objects.filter(confirmed=True).count(), 0)  # nessuna decisione da sola

    def test_rejected_is_not_asked_again_until_data_change(self):
        risposta = _risposta({"scelta": "non_applicabile", "cpe": None, "confidenza": 80, "motivazione": "driver"})
        with mock.patch(CHIEDI, return_value=risposta), mock.patch(DISPONIBILE, return_value=(True, "")):
            cpe_ai.giro(limit=5, confidenza_minima=60)
        proposta = SecurityPropostaAi.objects.get(product="7-zip")
        cpe_ai.segna_decisa(proposta, self.user, accettata=False)
        with mock.patch(CHIEDI, return_value=risposta) as ask, mock.patch(DISPONIBILE, return_value=(True, "")):
            cpe_ai.giro(limit=5, confidenza_minima=60)
        self.assertNotIn("7-zip", [c.args[0][-1]["content"].split("prodotto «")[1][:5] for c in ask.call_args_list])
        _cve("CVE-2099-0003", "7-zip", "p7zip")  # nuovo candidato: i dati del caso cambiano
        with mock.patch(CHIEDI, return_value=risposta), mock.patch(DISPONIBILE, return_value=(True, "")):
            cpe_ai.giro(limit=5, confidenza_minima=60)
        proposta.refresh_from_db()
        self.assertEqual(proposta.stato, SecurityPropostaAi.APERTA)

    def test_ai_unreachable_makes_no_request(self):
        with mock.patch(CHIEDI) as ask, mock.patch(DISPONIBILE, return_value=(False, "AI locale non raggiungibile: timeout")):
            esito = cpe_ai.giro(limit=5)
        ask.assert_not_called()
        self.assertFalse(esito["ok"])
        self.assertEqual(letture.esito(esito)[0], SecurityLetturaLog.ERRORE)

    def test_connection_error_mid_round_stops_the_round(self):
        with mock.patch(CHIEDI, return_value=_risposta(None, ok=False, error="Ollama non raggiungibile: timeout")) as ask, \
             mock.patch(DISPONIBILE, return_value=(True, "")):
            esito = cpe_ai.giro(limit=5)
        self.assertEqual(ask.call_count, 1)
        self.assertIn("non ha risposto", esito["errore"])

    def test_superseded_when_decided_elsewhere(self):
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "cpe", "cpe": "7-zip:7-zip", "confidenza": 90, "motivazione": "ok"})), \
             mock.patch(DISPONIBILE, return_value=(True, "")):
            cpe_ai.giro(limit=1, confidenza_minima=60)
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        self.assertEqual(cpe_ai.aggiorna_superate(), 1)
        self.assertEqual(SecurityPropostaAi.objects.get().stato, SecurityPropostaAi.SUPERATA)

    def test_task_is_off_by_default_and_registered_as_lettura(self):
        self.assertIn("cpe_ai", letture.PER_CODICE)
        self.assertEqual(ai_cpe_proposte_task(), {"skipped": "proposte AI su CPE ed esiti spente"})
        self.assertEqual(SecurityLetturaLog.objects.count(), 0)  # giro spento non registrato
        set_setting("ai.cpe.attivo", True, category="avvisi")
        with mock.patch(CHIEDI, return_value=_risposta({"scelta": "da_verificare", "cpe": None, "confidenza": 20, "motivazione": "?"})), \
             mock.patch(DISPONIBILE, return_value=(True, "")):
            esito = ai_cpe_proposte_task()
        self.assertEqual(esito["cpe"]["proposte"], 2)
        log = SecurityLetturaLog.objects.get(codice="cpe_ai")
        self.assertEqual(log.stato, SecurityLetturaLog.OK)
        self.assertEqual(log.riepilogo["cpe"]["proposte"], 2)

    def test_schedule_is_in_the_catalog(self):
        from automazioni.managed_flows import catalog

        entry = catalog()["security_ai_cpe"]
        self.assertEqual(entry["func"], "security.tasks.ai_cpe_proposte_task")


class ChiediTests(TestCase):
    def test_request_goes_to_local_ollama_with_json_format_and_is_logged(self):
        risposta = json.dumps({"message": {"role": "assistant", "content": json.dumps({"scelta": "da_verificare", "confidenza": 10})}, "model": "qwen-demo"}).encode()
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = risposta
        with self.settings(OLLAMA_BASE_URL="http://ollama.lan:11434", OLLAMA_CHAT_MODEL="qwen-demo", OLLAMA_API_PROVIDER="ollama"), \
             mock.patch("security.services.cpe_ai.urllib.request.urlopen", return_value=fake) as urlopen:
            out = cpe_ai._chiedi(cpe_ai._messaggi(cpe_ai.SISTEMA_CPE, cpe_ai.ESEMPI_CPE, "Programma: x"), action="cpe_proposta")
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["scelta"], "da_verificare")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ollama.lan:11434/api/chat")
        payload = json.loads(request.data)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["temperature"], cpe_ai.TEMPERATURA)
        log = SecurityAiInteractionLog.objects.get()
        self.assertEqual((log.action, log.status, log.model), ("cpe_proposta", "ok", "qwen-demo"))

    def test_network_error_is_logged_not_raised(self):
        with self.settings(OLLAMA_BASE_URL="http://ollama.lan:11434", OLLAMA_CHAT_MODEL="qwen-demo"), \
             mock.patch("security.services.cpe_ai.urllib.request.urlopen", side_effect=OSError("rete giù")):
            out = cpe_ai._chiedi([{"role": "user", "content": "x"}], action="cpe_proposta")
        self.assertFalse(out["ok"])
        self.assertIn("non raggiungibile", out["error"])
        self.assertEqual(SecurityAiInteractionLog.objects.get().status, "error")


class PagineTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        _cve("CVE-2099-0001", "7-zip", "7-zip", end_excluding="24.07")
        self._install("pc-01", "igor pavlov", "7-zip", "23.01")
        self.proposta = SecurityPropostaAi.objects.create(
            tipo=SecurityPropostaAi.TIPO_CPE, chiave=cpe_ai.chiave_cpe("igor pavlov", "7-zip"), vendor="igor pavlov", product="7-zip",
            proposta="7-zip:7-zip", motivazione="Stesso nome del candidato.", confidenza=92, candidati=["7-zip:7-zip"],
        )

    def test_software_page_shows_proposal_and_accept_applies_mapping_with_audit(self):
        response = self.client.get(reverse("security:software_mapping") + "?stato=ai")
        self.assertContains(response, "Proposta AI:")
        self.assertContains(response, "Stesso nome del candidato.")
        self.assertContains(response, "Proposte AI (1)")
        with mock.patch("security.views_vuln._queue_recompute") as recompute:
            response = self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]),
                                        {"decisione": "accetta", "next": "/soc/admin/config/software/?stato=ai"})
        self.assertEqual(response.status_code, 302)
        recompute.assert_called_once()
        mapping = SoftwareCpeMapping.objects.get(vendor="igor pavlov", product="7-zip")
        self.assertTrue(mapping.confirmed)
        self.assertEqual((mapping.cpe_vendor, mapping.cpe_product, mapping.confirmed_by), ("7-zip", "7-zip", self.user))
        self.proposta.refresh_from_db()
        self.assertEqual((self.proposta.stato, self.proposta.decisa_da), (SecurityPropostaAi.ACCETTATA, self.user))
        from core.models import AuditLog
        from security.models import SecurityConfigurationAuditLog

        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(model_name="SoftwareCpeMapping", new_value__contains="proposta AI").exists())
        self.assertTrue(AuditLog.objects.filter(azione="soc_proposta_ai_accettata").exists())

    def test_reject_keeps_mapping_open(self):
        self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]), {"decisione": "rifiuta"})
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, SecurityPropostaAi.RIFIUTATA)
        self.assertFalse(SoftwareCpeMapping.objects.filter(confirmed=True).exists())

    def test_da_verificare_cannot_be_accepted_and_decided_twice_is_refused(self):
        self.proposta.proposta = SecurityPropostaAi.DA_VERIFICARE
        self.proposta.save()
        self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]), {"decisione": "accetta"})
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, SecurityPropostaAi.APERTA)
        self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]), {"decisione": "rifiuta"})
        self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]), {"decisione": "accetta"})
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, SecurityPropostaAi.RIFIUTATA)

    def test_viewer_without_config_permission_cannot_decide(self):
        viewer = get_user_model().objects.create(username="soc_cpe_viewer")
        self.client.force_login(viewer)
        self.client.post(reverse("security:proposta_ai_decidi", args=[self.proposta.pk]), {"decisione": "accetta"})
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, SecurityPropostaAi.APERTA)

    def test_cve_page_shows_outcome_proposal(self):
        record = SecurityCveRecord.objects.get(cve_id="CVE-2099-0001")
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)
        SoftwareInstallation.objects.update(version_raw="24.08 R2")
        cve_impact.recompute(record)
        SecurityPropostaAi.objects.create(
            tipo=SecurityPropostaAi.TIPO_ESITO, chiave=cpe_ai.chiave_esito("CVE-2099-0001", "pc-01"), cve=record, host="pc-01",
            versione="24.08 R2", proposta="non_impatta", motivazione="La 24.08 è oltre la 24.07.", confidenza=88,
        )
        response = self.client.get(reverse("security:cve_detail", args=["CVE-2099-0001"]))
        self.assertContains(response, "1 proposta AI")
        self.assertContains(response, "La 24.08 è oltre la 24.07.")
        self.assertContains(response, "Accetta")

    def test_proponi_ora_queues_the_lettura(self):
        with mock.patch("security.services.letture.accoda", return_value=(True, "in coda")) as accoda:
            response = self.client.post(reverse("security:software_mapping"), {"action": "ai_proponi"})
        accoda.assert_called_once()
        self.assertEqual(accoda.call_args.args[0], "cpe_ai")
        self.assertEqual(response.status_code, 302)
