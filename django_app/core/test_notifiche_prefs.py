from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.notifiche_meta import notifica_categoria
from core.notifiche_prefs import (
    is_category_enabled_globally,
    set_category_global,
    should_notify,
)

User = get_user_model()


class NotificaCategoriaTests(TestCase):
    def test_mapping(self):
        self.assertEqual(notifica_categoria("dpi_scadenza"), "scadenzari")
        self.assertEqual(notifica_categoria("presa_visione"), "scadenzari")
        self.assertEqual(notifica_categoria("ticket_sla"), "ticket")
        self.assertEqual(notifica_categoria("assenza_approvata"), "assenze")
        self.assertEqual(notifica_categoria("anomalia_segnalata"), "operativita")
        self.assertEqual(notifica_categoria("tipo_ignoto"), "operativita")


class ShouldNotifyTests(TestCase):
    def test_default_tutto_acceso(self):
        self.assertTrue(is_category_enabled_globally("scadenzari"))
        self.assertTrue(should_notify(tipo="dpi_scadenza"))  # fail-open, nessun utente

    def test_admin_spegne_per_tutti(self):
        set_category_global("scadenzari", enabled=False)
        self.assertFalse(is_category_enabled_globally("scadenzari"))
        # admin off → nessuno la riceve, anche con utente
        u = User.objects.create_user("adminoff", password="pw")
        self.assertFalse(should_notify(tipo="dpi_scadenza", django_user=u))
        # altra categoria intatta
        self.assertTrue(should_notify(tipo="ticket_sla", django_user=u))

    def test_admin_riaccende(self):
        set_category_global("scadenzari", enabled=False)
        set_category_global("scadenzari", enabled=True)
        self.assertTrue(is_category_enabled_globally("scadenzari"))

    def test_utente_spegne_solo_per_se(self):
        from core.models import UserOnboarding

        u_off = User.objects.create_user("uoff", password="pw")
        UserOnboarding.objects.create(
            user=u_off, completed=True, notifiche_config={"scadenzari": False}
        )
        u_on = User.objects.create_user("uon", password="pw")  # nessuna pref

        self.assertFalse(should_notify(tipo="dpi_scadenza", django_user=u_off))
        self.assertTrue(should_notify(tipo="dpi_scadenza", django_user=u_on))

    def test_risoluzione_legacy_id(self):
        from core.models import Profile, UserOnboarding

        u = User.objects.create_user("legacyuser", password="pw")
        Profile.objects.create(user=u, legacy_user_id=7777)
        UserOnboarding.objects.create(
            user=u, completed=True, notifiche_config={"ticket": False}
        )
        self.assertFalse(should_notify(tipo="ticket_sla", legacy_user_id=7777))
        self.assertTrue(should_notify(tipo="ticket_sla", legacy_user_id=8888))  # altro utente


class InviaNotificaEnforcementTests(TestCase):
    """invia_notifica (chokepoint in-app) rispetta gli interruttori."""

    def test_saltata_se_categoria_spenta_admin(self):
        from core.models import Notifica
        from core.notifiche import invia_notifica

        set_category_global("scadenzari", enabled=False)
        invia_notifica(1234, "dpi_scadenza", "prova")
        self.assertFalse(
            Notifica.objects.filter(legacy_user_id=1234, tipo="dpi_scadenza").exists()
        )

    def test_creata_se_accesa(self):
        from core.models import Notifica
        from core.notifiche import invia_notifica

        invia_notifica(1234, "dpi_scadenza", "prova")
        self.assertTrue(
            Notifica.objects.filter(legacy_user_id=1234, tipo="dpi_scadenza").exists()
        )


class EmailEnforcementTests(TestCase):
    """I reminder email per-utente rispettano gli interruttori (via should_notify)."""

    def test_reminder_presa_visione_rispetta_switch(self):
        from procedure_refresh.tasks import _send_reminder_mail

        u = User.objects.create_user("prmail", password="pw")
        set_category_global("scadenzari", enabled=False)
        self.assertFalse(_send_reminder_mail(u, "x@y.it", [], subject="s", intro="i"))
        set_category_global("scadenzari", enabled=True)
        self.assertTrue(_send_reminder_mail(u, "x@y.it", [], subject="s", intro="i"))


class NotificheImpostazioniViewTests(TestCase):
    """Pagina utente: modifica le preferenze notifiche dopo l'onboarding, effettive."""

    def test_get_e_salvataggio(self):
        from core.models import UserOnboarding

        u = User.objects.create_user("setuser", password="pw", is_superuser=True)
        UserOnboarding.objects.create(user=u, skipped=True)
        self.client.force_login(u)

        resp = self.client.get(reverse("notifiche_impostazioni"))
        self.assertEqual(resp.status_code, 200)

        # POST con solo 'assenze' acceso → le altre off
        self.client.post(reverse("notifiche_impostazioni"), {"notifiche_assenze": "1"})
        onb = UserOnboarding.objects.get(user=u)
        self.assertEqual(onb.notifiche_config.get("assenze"), True)
        self.assertEqual(onb.notifiche_config.get("scadenzari"), False)
        # ed è effettiva: should_notify per scadenzari (per questo utente) è False
        self.assertFalse(should_notify(tipo="dpi_scadenza", django_user=u))
