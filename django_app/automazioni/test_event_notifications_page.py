"""Pagina 'Notifiche di sistema' nell'area automazioni: catalogo di sola
lettura delle email scatenate da un evento nel codice (view/comando manuale),
fuori dal motore regole e dai task pianificati.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from automazioni.event_notifications import EVENT_NOTIFICATIONS, get_event_notifications

User = get_user_model()


class EventNotificationsCatalogTests(TestCase):
    def test_get_event_notifications_e_copia_difensiva(self):
        rows = get_event_notifications()
        self.assertEqual(len(rows), len(EVENT_NOTIFICATIONS))
        rows[0]["label"] = "manomesso"
        self.assertNotEqual(EVENT_NOTIFICATIONS[0]["label"], "manomesso")

    def test_ogni_voce_ha_i_campi_richiesti(self):
        for item in EVENT_NOTIFICATIONS:
            for campo in ("code", "label", "module", "trigger", "destinatari", "source", "func"):
                self.assertTrue(str(item.get(campo) or "").strip(), f"{campo} mancante in {item}")

    def test_code_univoci(self):
        codes = [item["code"] for item in EVENT_NOTIFICATIONS]
        self.assertEqual(len(codes), len(set(codes)))


class EventNotificationsPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("evn_admin", "evn@x.local", "x")
        self.client.force_login(self.admin)

    def test_pagina_elenca_tutte_le_notifiche_censite(self):
        r = self.client.get(reverse("admin_portale:automazioni_event_notifications"))
        self.assertEqual(r.status_code, 200)
        for item in EVENT_NOTIFICATIONS:
            self.assertContains(r, item["label"])
            self.assertContains(r, item["func"])

    def test_richiede_login(self):
        self.client.logout()
        r = self.client.get(reverse("admin_portale:automazioni_event_notifications"))
        self.assertNotEqual(r.status_code, 200)
