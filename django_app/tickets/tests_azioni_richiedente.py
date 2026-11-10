"""Il richiedente annulla, conferma o riapre il suo ticket; il gestore corregge la data di apertura.
Solo dati sintetici."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile, UserOnboarding
from tickets.models import StatoTicket, Ticket, TipoTicket

User = get_user_model()


def _utente(username, legacy):
    u = User.objects.create_user(username=username, first_name="Syn", last_name=username[-4:])
    Profile.objects.create(user=u, legacy_user_id=legacy)
    UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True})
    return u


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AzioniRichiedenteTests(TestCase):
    def setUp(self):
        self.rich = _utente("syn.az.rich", 993001)
        self.altro = _utente("syn.az.altro", 993002)
        self.ticket = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Mouse sintetico", descrizione="x", categoria="PC",
            richiedente_nome="Syn Rich", richiedente_email="", richiedente_user=self.rich,
            richiedente_legacy_user_id=993001,
        )
        self.url = reverse("tickets:azione_richiedente", args=[self.ticket.pk])
        self.detail = reverse("tickets:detail", args=[self.ticket.pk])
        self._p = patch("tickets.views._can_manage_tickets", return_value=False)
        self._p.start()
        self.addCleanup(self._p.stop)

    def _post(self, **data):
        return self.client.post(self.url, data, follow=True)

    def test_scheda_mostra_annulla_solo_se_aperta(self):
        self.client.force_login(self.rich)
        page = self.client.get(self.detail)
        self.assertContains(page, "Annulla la richiesta")
        self.assertNotContains(page, "chiudi il ticket")
        self.ticket.stato = StatoTicket.IN_CARICO
        self.ticket.save(update_fields=["stato"])
        page = self.client.get(self.detail)
        self.assertNotContains(page, "La tua richiesta")

    def test_annulla_da_aperta(self):
        self.client.force_login(self.rich)
        page = self._post(azione="annulla", nota="Si è risolto da solo")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.ANNULLATO)
        self.assertIsNotNone(self.ticket.closed_at)
        self.assertTrue(self.ticket.commenti.filter(is_interno=False, testo__contains="risolto da solo").exists())
        self.assertEqual(self.ticket.stato_log.get().a_stato, StatoTicket.ANNULLATO)
        self.assertContains(page, "annullato")

    def test_non_annulla_se_gia_in_carico(self):
        self.ticket.stato = StatoTicket.IN_CARICO
        self.ticket.save(update_fields=["stato"])
        self.client.force_login(self.rich)
        page = self._post(azione="annulla")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.IN_CARICO)
        self.assertContains(page, "non è più disponibile")

    def test_conferma_risolto_chiude(self):
        self.ticket.stato = StatoTicket.RISOLTO
        self.ticket.risolto_da_nome = "Tecnico Syn"
        self.ticket.save(update_fields=["stato", "risolto_da_nome"])
        self.client.force_login(self.rich)
        page = self.client.get(self.detail)
        self.assertContains(page, "Sì, è risolto: chiudi il ticket")
        self.assertContains(page, "Tecnico Syn")
        self._post(azione="conferma")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.CHIUSO)
        self.assertTrue(self.ticket.commenti.filter(is_interno=False, testo__contains="Confermo").exists())

    def test_riapri_richiede_la_nota_e_torna_al_tecnico(self):
        self.ticket.stato = StatoTicket.RISOLTO
        self.ticket.assegnato_a = "Tecnico Syn"
        self.ticket.closed_at = timezone.now()
        self.ticket.save(update_fields=["stato", "assegnato_a", "closed_at"])
        self.client.force_login(self.rich)
        page = self._post(azione="riapri", nota="")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.RISOLTO)
        self.assertContains(page, "Scrivi cosa non funziona")
        self._post(azione="riapri", nota="Il mouse salta ancora")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.IN_CARICO)
        self.assertIsNone(self.ticket.closed_at)
        self.assertTrue(self.ticket.commenti.filter(is_interno=False, testo__contains="salta ancora").exists())

    def test_riapri_senza_assegnatario_torna_aperta(self):
        self.ticket.stato = StatoTicket.RISOLTO
        self.ticket.save(update_fields=["stato"])
        self.client.force_login(self.rich)
        self._post(azione="riapri", nota="Non va")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.APERTA)

    def test_un_altro_utente_non_puo(self):
        self.client.force_login(self.altro)
        response = self.client.post(self.url, {"azione": "annulla"})
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.stato, StatoTicket.APERTA)

    def test_dashboard_conta_i_risolti_da_confermare(self):
        self.ticket.stato = StatoTicket.RISOLTO
        self.ticket.save(update_fields=["stato"])
        self.client.force_login(self.rich)
        with patch("tickets.views._can_open_tickets", return_value=False):
            page = self.client.get(reverse("tickets:dashboard"))
        self.assertContains(page, "1 ticket risolto da confermare")
        self.assertContains(page, "?stato=RISOLTO")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CorreggiDataAperturaTests(TestCase):
    def setUp(self):
        self.gestore = _utente("syn.az.gest", 993101)
        self.ticket = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Stampante sintetica", descrizione="x", categoria="PC",
            richiedente_nome="Altro", richiedente_email="", richiedente_legacy_user_id=993199,
        )
        self.url = reverse("tickets:gestione_data_apertura", args=[self.ticket.pk])
        self.client.force_login(self.gestore)

    def _post(self, **data):
        with patch("tickets.views._can_manage_tickets", return_value=True):
            return self.client.post(self.url, data, follow=True)

    def test_gestore_sposta_la_data(self):
        passato = (timezone.localtime() - timedelta(days=2)).replace(second=0, microsecond=0)
        page = self._post(aperto_il=passato.strftime("%Y-%m-%dT%H:%M"))
        self.ticket.refresh_from_db()
        self.assertContains(page, "Data di apertura aggiornata")
        self.assertEqual(self.ticket.created_at, passato)
        self.assertTrue(self.ticket.commenti.filter(is_interno=True, testo__contains="Data di apertura corretta").exists())

    def test_futuro_e_dopo_chiusura_rifiutati(self):
        self.ticket.closed_at = timezone.now() - timedelta(days=1)
        self.ticket.stato = StatoTicket.CHIUSO
        self.ticket.save(update_fields=["closed_at", "stato"])
        prima = self.ticket.created_at
        for valore in ((timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                       timezone.localtime().strftime("%Y-%m-%dT%H:%M")):
            with self.subTest(valore=valore):
                self._post(aperto_il=valore)
                self.ticket.refresh_from_db()
                self.assertEqual(self.ticket.created_at, prima)

    def test_chi_non_gestisce_non_puo(self):
        with patch("tickets.views._can_manage_tickets", return_value=False):
            response = self.client.post(self.url, {"aperto_il": "2026-11-01T08:00"})
        self.assertIn(response.status_code, (302, 403))
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.created_at.strftime("%Y-%m-%dT%H:%M"), "2026-11-01T08:00")
