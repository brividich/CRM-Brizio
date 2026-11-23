"""SLA in orario di lavoro e promemoria con memoria (audit P10/P11)."""
from datetime import datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tickets.models import CategoriaTicket, StatoTicket, Ticket, TipoTicket
from tickets.sla import orario_sla, salva_orario_sla, scadenza_lavorativa


def _ora(*args):
    return timezone.make_aware(datetime(*args))


class ScadenzaLavorativaTests(TestCase):
    ORARIO = (8, 17)

    def setUp(self):
        cache.clear()

    def test_dentro_la_giornata(self):
        # Lunedì 2 marzo 2026, 9:00 + 4 ore = 13:00 dello stesso giorno.
        self.assertEqual(scadenza_lavorativa(_ora(2026, 3, 2, 9), 4, orario=self.ORARIO), _ora(2026, 3, 2, 13))

    def test_venerdi_sera_passa_a_lunedi(self):
        # Venerdì 6 marzo 16:00 + 3 ore: un'ora venerdì, due lunedì 9 marzo dalle 8.
        self.assertEqual(scadenza_lavorativa(_ora(2026, 3, 6, 16), 3, orario=self.ORARIO), _ora(2026, 3, 9, 10))

    def test_aperto_nel_fine_settimana_parte_lunedi(self):
        self.assertEqual(scadenza_lavorativa(_ora(2026, 3, 7, 11), 2, orario=self.ORARIO), _ora(2026, 3, 9, 10))

    def test_festivo_saltato(self):
        # Giovedì 24 dicembre 16:00 + 3 ore: venerdì 25 è Natale, poi il fine settimana.
        self.assertEqual(scadenza_lavorativa(_ora(2026, 12, 24, 16), 3, orario=self.ORARIO), _ora(2026, 12, 28, 10))

    def test_ore_su_piu_giorni(self):
        # 20 ore lavorative da lunedì 8:00 = 9 + 9 + 2: mercoledì 10:00.
        self.assertEqual(scadenza_lavorativa(_ora(2026, 3, 2, 8), 20, orario=self.ORARIO), _ora(2026, 3, 4, 10))

    def test_orario_salvato_e_validato(self):
        self.assertEqual(orario_sla(), (8, 17))
        self.assertFalse(salva_orario_sla(17, 8))
        self.assertTrue(salva_orario_sla(7, 16))
        self.assertEqual(orario_sla(), (7, 16))


class PromemoriaSlaTests(TestCase):
    def setUp(self):
        cache.clear()
        CategoriaTicket.objects.create(tipo=TipoTicket.IT, codice="SLA_TEST", etichetta="Prova SLA",
                                       sla_ore_risoluzione=1)
        self.ticket = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Stampante ferma", descrizione="x", categoria="SLA_TEST",
            richiedente_nome="Prova", stato=StatoTicket.IN_CARICO, assegnato_email="tecnico@example.com",
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(created_at=timezone.now() - timedelta(days=30))

    def _esegui(self):
        with mock.patch("core.email_utils.send_hub_mail") as mail, \
                mock.patch("tickets.management.commands.send_sla_reminders.invia_notifica_email"):
            call_command("send_sla_reminders", verbosity=0)
        return mail.call_count

    def test_un_promemoria_poi_richiamo_dopo_tre_giorni(self):
        self.assertEqual(self._esegui(), 1)
        self.assertEqual(self._esegui(), 0)  # il giorno dopo non si ripete
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_promemoria_tipo, "risoluzione")
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_promemoria_il=timezone.now() - timedelta(days=3))
        self.assertEqual(self._esegui(), 1)

    def test_categoria_letta_senza_query_per_ticket(self):
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.sla_risoluzione_scaduto)
        with self.assertNumQueries(0):
            self.assertTrue(self.ticket.sla_risoluzione_scaduto)
            self.ticket.sla_scadenza_risposta
