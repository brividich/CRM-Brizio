"""Synthetic credentials/network/broker; never contacts a real SNMP endpoint."""
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import discovery_jobs as jobs, services
from .credential_crypto import cifra, decifra
from .forms import CommunitySNMPForm, DiscoveryBackgroundForm
from .models import CommunitySNMP, DiscoverySNMP, DispositivoSNMP, ImpostazioniSNMP
from .snmp import EsitoDiscovery
from .tests import _AuthedClientMixin


class DiscoveryBackgroundTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.get(username="contatori_test_admin")
        self.community = CommunitySNMP.objects.create(nome="Laboratorio", segreto_cifrato=cifra("synthetic-secret"))
        self.url = reverse("contatori:discovery")
        self.enqueue = mock.patch.object(jobs, "async_task", return_value="synthetic-task").start()
        self.network = mock.patch.object(jobs, "scansiona_hosts", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)

    def scan(self, **overrides):
        data = dict(richiesta_da=self.user, rete="192.0.2.0/30", hosts=["192.0.2.1", "192.0.2.2"],
                    community_ids=[self.community.pk], versione="v2c", timeout=2)
        data.update(overrides)
        return DiscoverySNMP.objects.create(**data)

    def post_start(self, **overrides):
        data = dict(azione="avvia", richiesta=str(uuid.uuid4()), rete="192.0.2.0/30",
                    communities=[str(self.community.pk)], versione="v2c", timeout=2)
        data.update(overrides)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, data)
        return response

    def test_post_queues_only_identifiers_without_network_or_secrets(self):
        response = self.post_start()
        self.assertEqual(response.status_code, 302)
        scan = DiscoverySNMP.objects.get()
        self.enqueue.assert_called_once_with("contatori.discovery_jobs.esegui_batch", str(scan.pk), 0,
                                             q_options={"timeout": 60, "ack_failure": True})
        self.network.assert_not_called()
        self.assertNotIn("synthetic-secret", repr(scan.__dict__))

    def test_repeated_submission_queues_once(self):
        request_id = str(uuid.uuid4())
        self.post_start(richiesta=request_id)
        self.post_start(richiesta=request_id)
        self.assertEqual(DiscoverySNMP.objects.count(), 1)
        self.enqueue.assert_called_once()

    def test_hostile_request_id_cannot_read_or_reuse_another_owners_scan(self):
        other = get_user_model().objects.create(username="other-owner")
        scan = self.scan(richiesta_da=other)
        self.assertEqual(self.post_start(richiesta=str(scan.pk)).status_code, 404)
        for query in (f"?scan={scan.pk}", f"?scan={scan.pk}&partial=1", "?scan=not-a-uuid"):
            self.assertEqual(self.client.get(self.url + query).status_code, 404)
        for action in ("interrompi", "riprendi"):
            self.assertEqual(self.client.post(self.url, {"azione": action, "scan": scan.pk}).status_code, 404)
        self.enqueue.assert_not_called()

    def test_invalid_network_or_disabled_community_does_not_queue(self):
        self.post_start(rete="0.0.0.0/0")
        self.community.attiva = False
        self.community.save()
        self.post_start()
        self.assertFalse(DiscoverySNMP.objects.exists())
        self.enqueue.assert_not_called()

    def test_form_enforces_eight_candidates_and_catalog_order(self):
        more = [CommunitySNMP.objects.create(nome=f"Community {i}", segreto_cifrato=cifra("synthetic")) for i in range(8)]
        response = self.post_start(communities=["0", *[str(c.pk) for c in more]])
        self.assertContains(response, "al massimo otto")
        self.enqueue.assert_not_called()

    def test_completed_job_is_not_replayed(self):
        scan = self.scan()
        jobs.esegui_batch(str(scan.pk), 0)
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)
        self.assertEqual(scan.completati, 2)
        self.assertEqual(self.network.call_count, 1)

    def test_next_community_only_probes_unresolved_hosts(self):
        second = CommunitySNMP.objects.create(nome="Seconda", segreto_cifrato=cifra("synthetic-second"), versione="v1", porta=1161)
        scan = self.scan(community_ids=[self.community.pk, second.pk])
        self.network.return_value = [{"host": scan.hosts[0], "descr": "printer"}]
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual((scan.completati, scan.candidata), (1, 1))
        self.network.return_value = [{"host": scan.hosts[1], "descr": "switch"}]
        jobs.esegui_batch(str(scan.pk), 1)
        self.assertEqual(self.network.call_args.args[0], [scan.hosts[1]])
        self.assertEqual(self.network.call_args.kwargs["community"], "synthetic-second")
        self.assertEqual(self.network.call_args.kwargs["version"], "v1")
        self.assertEqual(self.network.call_args.kwargs["port"], 1161)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)
        self.assertEqual([r["community_nome"] for r in scan.risultati], ["Laboratorio", "Seconda"])
        self.assertNotIn("synthetic", repr(scan.risultati))

    def test_batches_cover_every_host_including_internal_subnet_boundaries(self):
        hosts = [f"192.0.2.{i}" for i in range(1, 35)]
        scan = self.scan(hosts=hosts)
        for revision in range(3):
            jobs.esegui_batch(str(scan.pk), revision)
        probed = [h for call in self.network.call_args_list for h in call.args[0]]
        self.assertEqual(probed, hosts)
        scan.refresh_from_db()
        self.assertEqual(scan.completati, 34)
        self.assertEqual(scan.percentuale, 100)
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)

    def test_next_candidate_skipped_when_all_hosts_found(self):
        scan = self.scan(community_ids=[self.community.pk, 0])
        self.network.return_value = [{"host": host} for host in scan.hosts]
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)
        self.enqueue.assert_not_called()

    def test_timeout_preserves_results_and_resume_skips_found_hosts(self):
        scan = self.scan()
        rows = EsitoDiscovery()
        rows.incompleta = True
        rows.append({"host": scan.hosts[0], "descr": "partial"})
        self.network.return_value = rows
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.ERRORE)
        self.assertEqual(scan.cursore, 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(jobs.riprendi(scan))
        self.network.return_value = []
        jobs.esegui_batch(str(scan.pk), scan.revisione)
        self.assertEqual(self.network.call_args.args[0], [scan.hosts[1]])
        scan.refresh_from_db()
        self.assertEqual(len(scan.risultati), 1)
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)

    def test_cancel_during_network_prevents_late_worker_from_overwriting_state(self):
        scan = self.scan()
        def cancel(*args, **kwargs):
            scan.refresh_from_db()
            jobs.interrompi(scan)
            return [{"host": scan.hosts[0]}]
        self.network.side_effect = cancel
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.ANNULLATA)
        self.assertEqual(scan.risultati, [])
        self.enqueue.assert_not_called()

    def test_stale_worker_resume_fences_old_generation(self):
        scan = self.scan(stato=DiscoverySNMP.Stato.CORSO)
        self.assertFalse(jobs.riprendi(scan))
        DiscoverySNMP.objects.filter(pk=scan.pk).update(aggiornata_il=timezone.now() - timedelta(minutes=3))
        scan.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(jobs.riprendi(scan))
        jobs.esegui_batch(str(scan.pk), 0)
        self.network.assert_not_called()
        jobs.esegui_batch(str(scan.pk), 1)
        self.network.assert_called_once()

    def test_enqueue_failure_keeps_resumable_scan_and_redacts_error(self):
        self.enqueue.side_effect = RuntimeError("synthetic-secret")
        self.post_start()
        scan = DiscoverySNMP.objects.get()
        self.assertEqual(scan.stato, scan.Stato.ERRORE)
        self.assertNotIn("synthetic-secret", scan.errore)
        self.assertTrue(scan.riprendibile)

    def test_network_error_does_not_leak_credentials_or_erase_previous_results(self):
        scan = self.scan(risultati=[{"host": "192.0.2.1", "descr": "earlier"}])
        self.network.side_effect = RuntimeError("synthetic-secret")
        jobs.esegui_batch(str(scan.pk), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.ERRORE)
        self.assertEqual(len(scan.risultati), 1)
        self.assertNotIn("synthetic-secret", scan.errore)

    def test_disabled_or_unreadable_credential_stops_before_network(self):
        for update in ({"attiva": False}, {"attiva": True, "segreto_cifrato": "unreadable"}):
            CommunitySNMP.objects.filter(pk=self.community.pk).update(**update)
            scan = self.scan()
            jobs.esegui_batch(str(scan.pk), 0)
            scan.refresh_from_db()
            self.assertEqual(scan.stato, scan.Stato.ERRORE)
        self.network.assert_not_called()

    def test_partial_view_has_progress_controls_and_no_secrets(self):
        scan = self.scan(risultati=[{"host": "192.0.2.1", "descr": "fixture", "community_nome": self.community.nome}])
        response = self.client.get(self.url, {"scan": scan.pk, "partial": "1"})
        self.assertContains(response, "every 4s")
        self.assertContains(response, "Interrompi")
        self.assertContains(response, "Laboratorio")
        self.assertNotContains(response, "synthetic-secret")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.network.assert_not_called()

    def test_catalog_encrypts_and_blank_edit_preserves_secret(self):
        form = CommunitySNMPForm({"nome": "Nuova", "valore": "synthetic-new", "ordine": 0, "attiva": True})
        self.assertTrue(form.is_valid(), form.errors)
        community = form.save()
        self.assertNotIn("synthetic-new", community.segreto_cifrato)
        self.assertEqual(decifra(community.segreto_cifrato), "synthetic-new")
        ciphertext = community.segreto_cifrato
        form = CommunitySNMPForm({"nome": "Rinominata", "valore": "", "ordine": 1, "attiva": True}, instance=community)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().segreto_cifrato, ciphertext)
        response = self.client.get(self.url, {"community": community.pk})
        self.assertNotContains(response, "synthetic-new")
        self.assertNotContains(response, ciphertext)

    def test_invalid_catalog_post_does_not_echo_secret(self):
        response = self.client.post(self.url, {"azione": "salva_community", "nome": "", "valore": "synthetic-new", "ordine": 0})
        self.assertNotContains(response, "synthetic-new")
        self.assertEqual(CommunitySNMP.objects.count(), 1)

    def test_catalog_post_audit_does_not_contain_value(self):
        with mock.patch("contatori.discovery_views.log_action") as audit:
            response = self.client.post(self.url, {"azione": "salva_community", "nome": "Creata", "valore": "synthetic-new", "ordine": 0, "attiva": True})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("synthetic-new", repr(audit.call_args))

    def test_saved_community_is_reused_by_polling_and_disabled_fails_closed(self):
        cfg = ImpostazioniSNMP.get_solo()
        device = DispositivoSNMP(nome="fixture", host="192.0.2.1", community_salvata=self.community)
        self.assertEqual(services._community_snmp(device, cfg), "synthetic-secret")
        self.community.attiva = False
        from .snmp import SNMPError
        with self.assertRaises(SNMPError):
            services._community_snmp(device, cfg)

    def test_rotation_can_decrypt_with_fallback(self):
        with override_settings(SECRET_KEY="synthetic-old-key"):
            token = cifra("synthetic-value")
        with override_settings(SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=["synthetic-old-key"]):
            self.assertEqual(decifra(token), "synthetic-value")
        with override_settings(SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=[]):
            with self.assertRaises(ValueError):
                decifra(token)

    def test_catalog_version_and_port_used_unless_device_overrides_them(self):
        cfg = ImpostazioniSNMP.get_solo()
        self.community.versione, self.community.porta = "v2c", 1161
        device = DispositivoSNMP(nome="fixture", host="192.0.2.1", community_salvata=self.community)
        self.assertEqual(services._parametri_snmp(device, cfg), (1161, cfg.timeout, "v2c"))
        device.porta, device.versione = 2161, "v1"
        self.assertEqual(services._parametri_snmp(device, cfg), (2161, cfg.timeout, "v1"))

    def test_csrf_required_to_start_or_modify_catalog(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get(self.url)  # Cookie presente, ma nessun token inviato nel POST.
        for action in ("avvia", "salva_community", "interrompi", "riprendi"):
            self.assertEqual(client.post(self.url, {"azione": action}).status_code, 403)
        self.enqueue.assert_not_called()

    def test_guest_cannot_see_catalog_or_progress(self):
        scan = self.scan()
        self.client.logout()
        for query in ("", f"?scan={scan.pk}&partial=1"):
            response = self.client.get(self.url + query)
            self.assertIn(response.status_code, (302, 401, 403))
            self.assertNotIn(b"Laboratorio", response.content)

    def test_completed_scan_stops_polling_and_cannot_resume(self):
        scan = self.scan(stato=DiscoverySNMP.Stato.COMPLETA, completati=2, cursore=2)
        response = self.client.get(self.url, {"scan": scan.pk, "partial": "1"})
        self.assertNotContains(response, "every 4s")
        self.assertNotContains(response, ">Riprendi<")
        self.assertFalse(jobs.riprendi(scan))

    def test_all_silent_hosts_receive_every_candidate(self):
        scan = self.scan(community_ids=[0, self.community.pk])
        for revision in range(2):
            jobs.esegui_batch(str(scan.pk), revision)
        scan.refresh_from_db()
        self.assertEqual(scan.stato, scan.Stato.COMPLETA)
        self.assertEqual(self.network.call_count, 2)
        self.assertEqual(scan.completati, 2)
        self.assertEqual(scan.risultati, [])

    def test_discovered_connection_settings_prefill_new_device(self):
        response = self.client.get(reverse("contatori:snmp_dispositivo_nuovo"), {
            "host": "192.0.2.5", "community_id": self.community.pk,
            "versione": "v2c", "porta": "1161"})
        self.assertEqual(str(response.context["form"]["community_salvata"].value()), str(self.community.pk))
        self.assertEqual(response.context["form"]["versione"].value(), "v2c")
        self.assertEqual(response.context["form"]["porta"].value(), "1161")
