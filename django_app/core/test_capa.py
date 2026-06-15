"""Test CAPA — modello core.ActionItem, service, view e integrazioni."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ActionItem, Notifica, Profile, UserOnboarding
from core.services import capa as capa_service

User = get_user_model()


def _complete_onboarding(user):
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "completed_at": timezone.now()}
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CapaServiceTests(TestCase):
    def setUp(self):
        self.resp = User.objects.create_user("mario", password="x")
        Profile.objects.create(user=self.resp, legacy_user_id=4242)

    def test_crea_action_item_notifica_responsabile(self):
        action = capa_service.crea_action_item(
            titolo="Sostituire protezione tornio",
            source_code="rilevazione_incidenti",
            source_pk="77",
            responsabile=self.resp,
            data_scadenza=timezone.localdate() + timedelta(days=10),
        )
        self.assertEqual(action.stato, ActionItem.STATO_APERTA)
        self.assertEqual(action.source_code, "rilevazione_incidenti")
        self.assertEqual(action.source_pk, "77")
        # Notifica creata per il legacy_user_id del responsabile.
        notif = Notifica.objects.filter(legacy_user_id=4242).first()
        self.assertIsNotNone(notif)
        self.assertIn("Sostituire protezione tornio", notif.messaggio)

    def test_chiudi_richiede_evidenza(self):
        action = capa_service.crea_action_item(titolo="x", responsabile=self.resp, notify=False)
        # Senza evidenza → rifiutata, stato invariato.
        self.assertFalse(capa_service.chiudi_azione(action, utente=self.resp, evidenza="   "))
        action.refresh_from_db()
        self.assertEqual(action.stato, ActionItem.STATO_APERTA)
        # Con evidenza → CHIUSA.
        self.assertTrue(capa_service.chiudi_azione(action, utente=self.resp, evidenza="Sostituita"))
        action.refresh_from_db()
        self.assertEqual(action.stato, ActionItem.STATO_CHIUSA)
        self.assertEqual(action.chiusa_da_id, self.resp.id)
        self.assertIsNotNone(action.data_chiusura)

    def test_verifica_marca_verificata(self):
        action = capa_service.crea_action_item(titolo="x", responsabile=self.resp, notify=False)
        capa_service.chiudi_azione(action, utente=self.resp, evidenza="ok")
        verifier = User.objects.create_user("luigi", password="x")
        capa_service.verifica_azione(action, utente=verifier, note="verificato")
        action.refresh_from_db()
        self.assertEqual(action.stato, ActionItem.STATO_VERIFICATA)
        self.assertEqual(action.verificata_da_id, verifier.id)

    def test_azioni_collegate(self):
        capa_service.crea_action_item(titolo="a", source_code="anomalie", source_pk="5", notify=False)
        capa_service.crea_action_item(titolo="b", source_code="anomalie", source_pk="5", notify=False)
        capa_service.crea_action_item(titolo="c", source_code="anomalie", source_pk="9", notify=False)
        self.assertEqual(capa_service.azioni_collegate("anomalie", "5").count(), 2)
        self.assertEqual(capa_service.azioni_collegate("anomalie", 9).count(), 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CapaViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@x.it", "x")
        self.user = User.objects.create_user("dipendente", password="x")
        _complete_onboarding(self.user)
        self.mine = capa_service.crea_action_item(titolo="La mia azione", responsabile=self.user, notify=False)
        self.other = capa_service.crea_action_item(titolo="Azione altrui", notify=False)

    def test_list_non_manager_sees_only_own(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("capa_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "La mia azione")
        self.assertNotContains(resp, "Azione altrui")

    def test_list_manager_sees_all(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("capa_list"))
        self.assertContains(resp, "La mia azione")
        self.assertContains(resp, "Azione altrui")

    def test_create_forbidden_for_non_manager(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("capa_create"))
        self.assertEqual(resp.status_code, 403)

    def test_create_by_manager(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("capa_create"), {
            "titolo": "Nuova azione test",
            "descrizione": "",
            "tipo": ActionItem.TIPO_CORRETTIVA,
            "responsabile": "",
            "reparto": "",
            "data_scadenza": "",
            "source_code": "manuale",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ActionItem.objects.filter(titolo="Nuova azione test").exists())

    def test_close_requires_evidence_then_verify_four_eyes(self):
        # Chiusura da parte del responsabile (non manager).
        self.client.force_login(self.user)
        url_close = reverse("capa_close", args=[self.mine.pk])
        # Senza evidenza → resta aperta.
        self.client.post(url_close, {"evidenza_chiusura": ""})
        self.mine.refresh_from_db()
        self.assertNotEqual(self.mine.stato, ActionItem.STATO_CHIUSA)
        # Con evidenza → CHIUSA.
        self.client.post(url_close, {"evidenza_chiusura": "Fatto"})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.stato, ActionItem.STATO_CHIUSA)

        # 4 occhi: chi ha chiuso non può verificare (manager non-superuser via patch).
        url_verify = reverse("capa_verify", args=[self.mine.pk])
        with mock.patch("core.views_capa._can_manage_capa", return_value=True):
            self.client.post(url_verify, {"note_verifica": ""})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.stato, ActionItem.STATO_CHIUSA)  # ancora chiusa, non verificata

        # Una persona diversa (admin/superuser) può verificare.
        self.client.force_login(self.admin)
        self.client.post(url_verify, {"note_verifica": "verificato"})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.stato, ActionItem.STATO_VERIFICATA)

    def test_detail_forbidden_for_unrelated_non_manager(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("capa_detail", args=[self.other.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_safety_actor_can_create_from_incident_origin(self):
        # acl_preposti vuoto = creazione segnalazioni aperta → l'attore sicurezza crea.
        self.client.force_login(self.user)
        resp = self.client.get(reverse("capa_create") + "?source=rilevazione_incidenti&pk=68")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse("capa_create"), {
            "titolo": "Azione da incidente",
            "descrizione": "",
            "tipo": ActionItem.TIPO_CORRETTIVA,
            "responsabile": "",
            "reparto": "",
            "data_scadenza": "",
            "source_code": "rilevazione_incidenti",
            "source_pk": "68",
        })
        self.assertEqual(resp.status_code, 302)
        action = ActionItem.objects.get(titolo="Azione da incidente")
        self.assertEqual(action.created_by_id, self.user.id)
        # Il creatore (non gestore) può vedere e ritrova l'azione nella lista.
        self.assertEqual(self.client.get(reverse("capa_detail", args=[action.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse("capa_list")), "Azione da incidente")

    def test_manual_create_still_managers_only(self):
        # Senza origine sicurezza i non-gestori restano esclusi (inserimento manuale).
        self.client.force_login(self.user)
        resp = self.client.post(reverse("capa_create"), {
            "titolo": "Manuale", "tipo": ActionItem.TIPO_CORRETTIVA, "source_code": "manuale",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ActionItem.objects.filter(titolo="Manuale").exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CapaScadenzeProviderTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser("admin", "admin@x.it", "x")
        self.resp = User.objects.create_user("resp", password="x")
        self.other = User.objects.create_user("other", password="x")
        oggi = timezone.localdate()
        self.a = capa_service.crea_action_item(
            titolo="Con scadenza", responsabile=self.resp,
            data_scadenza=oggi + timedelta(days=5), notify=False,
        )
        # Conclusa → non deve comparire.
        concl = capa_service.crea_action_item(
            titolo="Conclusa", responsabile=self.resp,
            data_scadenza=oggi + timedelta(days=3), notify=False,
        )
        concl.stato = ActionItem.STATO_VERIFICATA
        concl.save(update_fields=["stato"])

    def _collect(self, user):
        from dashboard.scadenze_providers import ScadenzeContext, collect_capa

        request = self.factory.get("/scadenze")
        request.user = user
        return collect_capa(ScadenzeContext.build(request))

    def test_manager_vede_tutte(self):
        items = self._collect(self.admin)
        titoli = {i.titolo for i in items}
        self.assertIn("Con scadenza", titoli)
        self.assertNotIn("Conclusa", titoli)

    def test_responsabile_vede_le_proprie(self):
        items = self._collect(self.resp)
        self.assertEqual([i.titolo for i in items], ["Con scadenza"])

    def test_estraneo_non_vede_nulla(self):
        self.assertEqual(self._collect(self.other), [])


class CapaIntegrationRegistryTests(TestCase):
    def test_source_registrata_in_automazioni(self):
        from automazioni.source_registry import get_source_choices

        codes = {code for code, _label in get_source_choices()}
        self.assertIn("core_actionitem", codes)

    def test_trigger_sql_presente(self):
        from pathlib import Path

        import automazioni

        trg = Path(automazioni.__file__).resolve().parent / "migrations" / "trg_core_actionitem_automation.sql"
        self.assertTrue(trg.exists())
        content = trg.read_text(encoding="utf-8")
        self.assertIn("core_actionitem", content)
        self.assertIn("automation_event_queue", content)
