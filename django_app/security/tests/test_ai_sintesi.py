"""Sintesi del giorno preparata in anticipo: una richiesta solo se i punti cambiano, mostrata subito (AI simulata)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from security.services.ai_explain import cached_brief, prepare_daily_brief
from security.services.configuration import set_setting
from security.tasks import ai_sintesi_giorno_task

ASK = "security.services.ai_explain._ask"
ITEMS = "security.services.overview.attention_items"
POINT = [{"level_label": "Alta", "area": "Backup", "title": "PC-DEMO senza backup da 4 giorni", "detail": ""}]


def _ok(text="Oggi conta il backup di PC-DEMO."):
    return {"ok": True, "text": text, "error": "", "model": "demo-model", "disclaimer": "Testo generato dall'AI."}


class PreparaSintesiTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_asks_once_while_points_do_not_change(self):
        with mock.patch(ITEMS, return_value=POINT), mock.patch(ASK, return_value=_ok()) as ask:
            self.assertTrue(prepare_daily_brief()["ok"])
            self.assertEqual(prepare_daily_brief(), {"skipped": "sintesi già aggiornata"})
        self.assertEqual(ask.call_count, 1)
        self.assertIsNotNone(cached_brief(POINT)["generated_at"])

    def test_new_points_trigger_a_new_brief(self):
        with mock.patch(ITEMS, return_value=POINT), mock.patch(ASK, return_value=_ok()):
            prepare_daily_brief()
        other = POINT + [{"level_label": "Media", "area": "VPN", "title": "Accessi negati", "detail": ""}]
        with mock.patch(ITEMS, return_value=other), mock.patch(ASK, return_value=_ok()) as ask:
            prepare_daily_brief()
        self.assertEqual(ask.call_count, 1)

    def test_ai_down_is_not_cached(self):
        with mock.patch(ITEMS, return_value=POINT), mock.patch(ASK, return_value={"ok": False, "text": "", "error": "giù", "model": ""}):
            self.assertFalse(prepare_daily_brief()["ok"])
        self.assertIsNone(cached_brief(POINT))

    def test_task_can_be_switched_off(self):
        set_setting("ai.sintesi.attivo", False, category="avvisi")
        with mock.patch(ASK) as ask:
            self.assertEqual(ai_sintesi_giorno_task(), {"skipped": "sintesi automatica spenta"})
        ask.assert_not_called()

    def test_schedule_is_a_designer_flow(self):
        from automazioni.managed_flows import catalog

        self.assertEqual(catalog()["security_ai_sintesi"]["func"], "security.tasks.ai_sintesi_giorno_task")


class PanoramicaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(get_user_model().objects.create(username="soc_sintesi", is_staff=True, is_superuser=True))

    def test_ready_brief_is_shown_without_clicking(self):
        # Punti veri della Panoramica (database vuoto): la pagina usa gli stessi.
        with mock.patch(ASK, return_value=_ok("Parti dal backup di PC-DEMO.")):
            prepare_daily_brief()
            response = self.client.get(reverse("security:dashboard"))
        self.assertContains(response, "Parti dal backup di PC-DEMO.")
        self.assertContains(response, "preparata alle")
        self.assertContains(response, "Rigenera")

    def test_without_brief_the_button_is_there(self):
        with mock.patch(ASK) as ask:
            response = self.client.get(reverse("security:dashboard"))
        ask.assert_not_called()  # aprire la pagina non chiama mai l'AI
        self.assertContains(response, "Chiedi all'AI")
        self.assertNotContains(response, "Rigenera")
