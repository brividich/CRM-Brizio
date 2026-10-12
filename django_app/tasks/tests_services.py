"""Test dei servizi KICK-OFF senza request: assenze, notifiche, calendario."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from core.models import Notifica, Profile

from .services import absences, notify
from .services.calendar_it import _count_working_days, _italian_holidays

User = get_user_model()


class AbsencesFromAnagraficaTests(SimpleTestCase):
    def test_utente_con_anagrafica_usa_il_servizio_assenze(self):
        user = object()
        righe = {
            7: [
                {"data_inizio": date(2026, 10, 14), "data_fine": date(2026, 10, 15),
                 "tipo": "Ferie", "stato": "confermata"},
                {"data_inizio": date(2026, 10, 12), "data_fine": date(2026, 10, 12),
                 "tipo": "Permesso", "stato": "pendente"},
            ]
        }
        with patch.object(absences, "_legacy_anagrafica_id_for_user", return_value=7), \
                patch.object(absences, "disponibilita_per_anagrafica", return_value=righe) as servizio, \
                patch.object(absences, "_load_user_absences_by_name") as per_nome:
            risultato = absences._load_user_absences(
                user, date_start=date(2026, 10, 1), date_end=date(2026, 10, 31)
            )
        servizio.assert_called_once()
        per_nome.assert_not_called()
        self.assertEqual(
            [(r["start_date"], r["tipo"], r["status"]) for r in risultato],
            [(date(2026, 10, 12), "Permesso", "In attesa"), (date(2026, 10, 14), "Ferie", "Approvato")],
        )

    def test_utente_senza_anagrafica_ripiega_sul_nome(self):
        with patch.object(absences, "_legacy_anagrafica_id_for_user", return_value=None), \
                patch.object(absences, "disponibilita_per_anagrafica") as servizio, \
                patch.object(absences, "_load_user_absences_by_name", return_value=[]) as per_nome:
            absences._load_user_absences(object(), date_start=date(2026, 10, 1), date_end=date(2026, 10, 2))
        servizio.assert_not_called()
        per_nome.assert_called_once()

    def test_senza_profilo_legacy_nessuna_anagrafica(self):
        class Utente:
            profile = None

        self.assertIsNone(absences._legacy_anagrafica_id_for_user(Utente()))


class NotifyUserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notificato", password="x")
        Profile.objects.create(user=self.user, legacy_user_id=4242)

    def test_crea_la_notifica_in_app(self):
        notify.notify_user(self.user, "Messaggio", "/tasks/1/")
        notifica = Notifica.objects.get(legacy_user_id=4242)
        self.assertEqual((notifica.tipo, notifica.url_azione), ("task", "/tasks/1/"))

    def test_rispetta_le_preferenze_utente(self):
        with patch("core.notifiche_prefs.should_notify", return_value=False):
            notify.notify_user(self.user, "Messaggio")
        self.assertFalse(Notifica.objects.filter(legacy_user_id=4242).exists())

    def test_utente_senza_id_legacy_ignorato(self):
        altro = User.objects.create_user(username="senza-legacy", password="x")
        notify.notify_user(altro, "Messaggio")
        self.assertEqual(Notifica.objects.count(), 0)


class CalendarioTests(SimpleTestCase):
    def test_festivi_2026_con_pasqua_e_pasquetta(self):
        festivi = _italian_holidays(2026)
        self.assertIn(date(2026, 4, 5), festivi)  # Pasqua
        self.assertIn(date(2026, 4, 6), festivi)  # Lunedi' dell'Angelo
        self.assertEqual(len(festivi), 12)

    def test_giorni_lavorativi_saltano_weekend_e_festivi(self):
        festivi = _italian_holidays(2026)
        # 30/04 gio, 01/05 ven festivo, 02-03 weekend, 04/05 lun
        self.assertEqual(_count_working_days(date(2026, 4, 30), date(2026, 5, 4), festivi), 2)
