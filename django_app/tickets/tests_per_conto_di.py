"""Ticket di manutenzione aperto per conto di un collega (solo squadra manutenzione).
Solo dati sintetici."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.services import squadra_manutenzione
from core.models import AccessGroup, AccessGroupMembership, Profile, UserOnboarding
from tickets.models import Ticket

User = get_user_model()


def _onboarding(user):
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PerContoDiTests(TestCase):
    def setUp(self):
        self.manut = User.objects.create_user(username="syn.pcd.manut", first_name="Manu", last_name="Tentore")
        self.collega = User.objects.create_user(username="syn.pcd.collega", first_name="Col", last_name="Lega",
                                                email="collega@example.com")
        self.estraneo = User.objects.create_user(username="syn.pcd.altro")
        for user, legacy in ((self.manut, 991001), (self.collega, 991002), (self.estraneo, 991003)):
            Profile.objects.create(user=user, legacy_user_id=legacy)
            _onboarding(user)
        gruppo = AccessGroup.objects.create(code="syn-pcd-squadra", label="Squadra sintetica", priority=300)
        AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=991001)
        squadra_manutenzione.salva_impostazioni(gruppo="syn-pcd-squadra", assegnatario="")

    def _payload(self, **extra):
        data = {
            "tipo": "MAN", "incide_sicurezza": "0", "categoria": "CNC", "priorita": "MEDIA",
            "titolo": "Perdita sintetica", "descrizione": "Descrizione sintetica",
            "asset_descrizione_libera": "Macchina sintetica",
        }
        data.update(extra)
        return data

    def _patches(self):
        return (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._can_manage_tickets", return_value=False),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        )

    def test_manutentore_vede_il_campo_e_apre_per_il_collega(self):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            self.assertContains(page, "Per conto di")
            response = self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                                        self._payload(per_conto_di=str(self.collega.pk)))
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.collega.pk)
        self.assertEqual(ticket.aperto_da_user_id, self.manut.pk)
        self.assertTrue(ticket.aperto_da_nome)
        # Chi l'ha compilato continua a vederlo
        with p1, p2, p3, p4:
            detail = self.client.get(reverse("tickets:detail", args=[ticket.pk]))
        self.assertEqual(detail.status_code, 200)

    def test_chi_non_e_della_squadra_non_puo(self):
        self.client.force_login(self.estraneo)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            self.assertNotContains(page, "Per conto di")
            self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                             self._payload(per_conto_di=str(self.collega.pk)))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.estraneo.pk)
        self.assertIsNone(ticket.aperto_da_user_id)

    def test_errore_conserva_la_scelta(self):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            response = self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                                        self._payload(per_conto_di=str(self.collega.pk), titolo=""))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-hub-form-error")
        self.assertContains(response, f'value="{self.collega.pk}" selected')
        self.assertContains(response, "Descrizione sintetica")
        self.assertEqual(Ticket.objects.count(), 0)
