from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica, UserOnboarding

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce

User = get_user_model()


def _crea_utente(username: str) -> User:
    """Crea uno User non-superuser con onboarding gia' completato (altrimenti il
    middleware di primo accesso redireziona qualunque richiesta prima della view)."""
    user = User.objects.create_user(username=username, password="pass12345")
    UserOnboarding.objects.create(user=user, completed=True)
    return user


def _crea_utente_con_dipendente(username: str, nome: str, cognome: str) -> tuple[User, AnagraficaDipendente]:
    """Crea uno User + AnagraficaDipendente collegati, come richiede la FK legacy utenti.id."""
    user = _crea_utente(username)
    UtenteLegacy.objects.create(id=user.id, nome=username, email=f"{username}@example.local", password="x")
    dipendente = AnagraficaDipendente.objects.create(nome=nome, cognome=cognome, utente_id=user.id)
    return user, dipendente


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GenerazioneChecklistTests(TestCase):
    def test_creazione_evento_genera_voci_da_template_attivi(self):
        admin = User.objects.create_superuser(username="co-admin", password="pass12345")
        ChecklistTaskTemplate.objects.create(ordine=1, descrizione="Spegnere compressore", attivo=True)
        ChecklistTaskTemplate.objects.create(ordine=2, descrizione="Chiudere acqua", attivo=True)
        ChecklistTaskTemplate.objects.create(ordine=3, descrizione="Mansione disattivata", attivo=False)

        self.client.force_login(admin)
        response = self.client.post(
            reverse("checklist_operativa:evento_nuovo"),
            {"nome": "Ferie estive 2026", "data_inizio": "2026-08-10", "data_fine": "2026-08-24", "note": ""},
        )

        self.assertEqual(response.status_code, 302)
        evento = ChiusuraEvento.objects.get(nome="Ferie estive 2026")
        # Non assumo isolamento totale del template: la migration di seed
        # popola gia' mansioni attive in ogni ambiente (anche nei test).
        self.assertTrue(evento.voci.filter(descrizione="Spegnere compressore").exists())
        self.assertTrue(evento.voci.filter(descrizione="Chiudere acqua").exists())
        self.assertFalse(evento.voci.filter(descrizione="Mansione disattivata").exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ConfermaTaskTests(TestCase):
    def setUp(self):
        self.responsabile_user, self.dipendente = _crea_utente_con_dipendente("co-resp", "Mario", "Rossi")
        self.altro_user = _crea_utente("co-altro")

        self.evento = ChiusuraEvento.objects.create(nome="Natale 2026", data_inizio=date(2026, 12, 24))
        self.voce = ChiusuraVoce.objects.create(
            evento=self.evento, ordine=1, descrizione="Spegnere caldaia", responsabile=self.dipendente,
        )

    def test_responsabile_puo_confermare_il_proprio_task(self):
        self.client.force_login(self.responsabile_user)
        response = self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma", "note": "ok"},
        )
        self.assertEqual(response.status_code, 302)
        self.voce.refresh_from_db()
        self.assertTrue(self.voce.confermato)
        self.assertEqual(self.voce.confermato_da, self.dipendente)

    def test_altro_utente_non_puo_confermare_task_non_suo(self):
        self.client.force_login(self.altro_user)
        response = self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma"},
        )
        self.assertEqual(response.status_code, 403)
        self.voce.refresh_from_db()
        self.assertFalse(self.voce.confermato)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ConfigurazioneAclTests(TestCase):
    def test_utente_senza_permesso_riceve_403(self):
        user = _crea_utente("co-noperm")
        self.client.force_login(user)
        response = self.client.get(reverse("checklist_operativa:configurazione"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_accede_alla_configurazione(self):
        admin = User.objects.create_superuser(username="co-admin2", password="pass12345")
        self.client.force_login(admin)
        response = self.client.get(reverse("checklist_operativa:configurazione"))
        self.assertEqual(response.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PropostaApprovazioneTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-admin3", password="pass12345")
        self.proponente = _crea_utente("co-prop")
        self.evento = ChiusuraEvento.objects.create(nome="Ferie 2027", data_inizio=date(2027, 8, 1))
        self.proposta = ChiusuraProposta.objects.create(
            evento=self.evento, descrizione="Spegnere insegna esterna", proposto_da=self.proponente,
        )
        self.template_count_iniziale = ChecklistTaskTemplate.objects.count()

    def test_approvazione_crea_voce_e_facoltativamente_template(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("checklist_operativa:proposta_decidi", args=[self.proposta.pk]),
            {"decisione": "approva", "aggiungi_al_template": "on", "note_admin": "ok, buona idea"},
        )
        self.assertEqual(response.status_code, 302)
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_APPROVATA)
        self.assertIsNotNone(self.proposta.voce_generata)
        self.assertIsNotNone(self.proposta.template_generato)
        self.assertEqual(self.evento.voci.count(), 1)
        self.assertEqual(ChecklistTaskTemplate.objects.count(), self.template_count_iniziale + 1)

    def test_rifiuto_non_crea_voce(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("checklist_operativa:proposta_decidi", args=[self.proposta.pk]),
            {"decisione": "rifiuta", "note_admin": "non necessario"},
        )
        self.assertEqual(response.status_code, 302)
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_RIFIUTATA)
        self.assertEqual(self.evento.voci.count(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReminderCommandTests(TestCase):
    def test_notifica_solo_alle_soglie_di_preavviso(self):
        user, dipendente = _crea_utente_con_dipendente("co-remind", "Anna", "Verdi")
        oggi = date.today()

        evento_a_3_giorni = ChiusuraEvento.objects.create(
            nome="Chiusura a 3gg", data_inizio=oggi + timedelta(days=3),
        )
        ChiusuraVoce.objects.create(
            evento=evento_a_3_giorni, descrizione="Task non confermato", responsabile=dipendente,
        )

        evento_a_5_giorni = ChiusuraEvento.objects.create(
            nome="Chiusura a 5gg", data_inizio=oggi + timedelta(days=5),
        )
        ChiusuraVoce.objects.create(
            evento=evento_a_5_giorni, descrizione="Task fuori soglia", responsabile=dipendente,
        )

        out = StringIO()
        call_command("send_checklist_chiusura_reminders", stdout=out)

        self.assertEqual(Notifica.objects.filter(legacy_user_id=user.id).count(), 1)
