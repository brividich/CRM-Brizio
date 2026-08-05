from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica, UserOnboarding

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce
from .services import (
    ChecklistStatoError,
    chiudi_evento,
    decidi_proposta,
    genera_voci_da_template,
)

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReminderEmailTests(TestCase):
    """Il canale email: una sola mail per responsabile, non una per voce."""

    def setUp(self):
        self.user, self.dipendente = _crea_utente_con_dipendente("co-mail", "Rita", "Gialli")
        self.dipendente.email_notifica = "rita.gialli@example.local"
        self.dipendente.save(update_fields=["email_notifica"])
        self.evento = ChiusuraEvento.objects.create(
            nome="Chiusura con mail", data_inizio=timezone.localdate() + timedelta(days=3),
        )
        for i in range(3):
            ChiusuraVoce.objects.create(
                evento=self.evento, ordine=i, descrizione=f"Task {i}", responsabile=self.dipendente,
            )

    def test_una_sola_email_con_tutte_le_voci(self):
        call_command("send_checklist_chiusura_reminders", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1, "Una mail per riga sarebbe il modo piu' rapido per farsi ignorare.")
        messaggio = mail.outbox[0]
        self.assertEqual(messaggio.to, ["rita.gialli@example.local"])
        for i in range(3):
            self.assertIn(f"Task {i}", messaggio.body)
        # Le notifiche in-app restano invece una per voce.
        self.assertEqual(Notifica.objects.filter(legacy_user_id=self.user.id).count(), 3)

    def test_senza_email_notifica_resta_solo_la_notifica(self):
        """In anagrafica_dipendenti `email` e' il login legacy: si usa `email_notifica`."""
        self.dipendente.email_notifica = ""
        self.dipendente.save(update_fields=["email_notifica"])

        call_command("send_checklist_chiusura_reminders", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=self.user.id).count(), 3)

    def test_solo_notifiche_salta_le_email(self):
        call_command("send_checklist_chiusura_reminders", "--solo-notifiche", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=self.user.id).count(), 3)

    def test_dry_run_non_invia_nulla(self):
        call_command("send_checklist_chiusura_reminders", "--dry-run", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=self.user.id).count(), 0)


# ---------------------------------------------------------------------------
# Regole di stato: un evento chiuso e' un registro storico, non si tocca piu'
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DateEventoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-date", password="pass12345")
        self.client.force_login(self.admin)

    def test_data_fine_precedente_a_inizio_rifiutata_dal_form(self):
        response = self.client.post(
            reverse("checklist_operativa:evento_nuovo"),
            {"nome": "Date al contrario", "data_inizio": "2026-08-20", "data_fine": "2026-08-10", "note": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ChiusuraEvento.objects.filter(nome="Date al contrario").exists())
        self.assertContains(response, "non può precedere", status_code=200)

    def test_data_fine_vuota_resta_ammessa(self):
        response = self.client.post(
            reverse("checklist_operativa:evento_nuovo"),
            {"nome": "Solo inizio", "data_inizio": "2026-08-20", "data_fine": "", "note": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ChiusuraEvento.objects.filter(nome="Solo inizio").exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class EventoChiusoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-chiuso", password="pass12345")
        self.user, self.dipendente = _crea_utente_con_dipendente("co-chi-resp", "Luca", "Bianchi")
        self.evento = ChiusuraEvento.objects.create(
            nome="Chiusura archiviata", data_inizio=timezone.localdate(),
        )
        self.voce = ChiusuraVoce.objects.create(
            evento=self.evento, ordine=1, descrizione="Spegnere quadro", responsabile=self.dipendente,
        )

    def _chiudi(self):
        self.evento.stato = ChiusuraEvento.STATO_CHIUSA
        self.evento.save(update_fields=["stato"])

    def test_voce_di_evento_chiuso_non_confermabile(self):
        self._chiudi()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma"},
        )
        self.assertEqual(response.status_code, 302)
        self.voce.refresh_from_db()
        self.assertFalse(self.voce.confermato)

    def test_conferma_non_annullabile_dopo_la_chiusura(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma"},
        )
        self.voce.refresh_from_db()
        self.assertTrue(self.voce.confermato)

        self._chiudi()
        response = self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "annulla"},
        )
        self.assertEqual(response.status_code, 302)
        self.voce.refresh_from_db()
        self.assertTrue(self.voce.confermato, "La conferma storicizzata non deve poter essere annullata.")

    def test_evento_chiuso_non_riceve_nuove_voci(self):
        self._chiudi()
        self.client.force_login(self.admin)
        url = reverse("checklist_operativa:voce_nuova", args=[self.evento.pk])

        self.assertEqual(self.client.get(url).status_code, 302)
        response = self.client.post(url, {"descrizione": "Voce tardiva", "ordine": 5, "note": ""})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.evento.voci.filter(descrizione="Voce tardiva").exists())

    def test_evento_gia_chiuso_non_si_richiude(self):
        self.assertTrue(chiudi_evento(self.evento.pk))
        self.assertFalse(chiudi_evento(self.evento.pk))
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.stato, ChiusuraEvento.STATO_CHIUSA)

    def test_riapertura_riporta_l_evento_modificabile(self):
        """Contropartita della chiusura: un evento archiviato per sbaglio si recupera."""
        self.client.force_login(self.admin)
        self.client.post(reverse("checklist_operativa:evento_chiudi", args=[self.evento.pk]))

        response = self.client.post(reverse("checklist_operativa:evento_riapri", args=[self.evento.pk]))
        self.assertEqual(response.status_code, 302)
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.stato, ChiusuraEvento.STATO_APERTA)

        # E torna davvero utilizzabile: il responsabile riesce a confermare.
        self.client.force_login(self.user)
        self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma"},
        )
        self.voce.refresh_from_db()
        self.assertTrue(self.voce.confermato)

    def test_riapertura_non_azzera_le_conferme(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("checklist_operativa:conferma", args=[self.voce.pk]), {"azione": "conferma"},
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("checklist_operativa:evento_chiudi", args=[self.evento.pk]))
        self.client.post(reverse("checklist_operativa:evento_riapri", args=[self.evento.pk]))

        self.voce.refresh_from_db()
        self.assertTrue(self.voce.confermato, "Si riapre il registro, non lo si azzera.")

    def test_riapertura_di_evento_gia_aperto_non_scrive(self):
        from .services import riapri_evento

        self.assertFalse(riapri_evento(self.evento.pk))

    def test_riapertura_tracciata_nell_audit(self):
        from core.audit import storico_oggetto

        self.client.force_login(self.admin)
        self.client.post(reverse("checklist_operativa:evento_chiudi", args=[self.evento.pk]))
        self.client.post(reverse("checklist_operativa:evento_riapri", args=[self.evento.pk]))

        azioni = [v.azione for v in storico_oggetto(self.evento)]
        self.assertIn("riapri_evento_chiusura", azioni)

    def test_chiusura_dalla_view_e_idempotente(self):
        self.client.force_login(self.admin)
        url = reverse("checklist_operativa:evento_chiudi", args=[self.evento.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.stato, ChiusuraEvento.STATO_CHIUSA)


# ---------------------------------------------------------------------------
# Proposte: la decisione si prende una volta sola
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PropostaIdempotenzaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-idem", password="pass12345")
        self.proponente = _crea_utente("co-idem-prop")
        self.evento = ChiusuraEvento.objects.create(
            nome="Ferie idempotenti", data_inizio=timezone.localdate(),
        )
        self.proposta = ChiusuraProposta.objects.create(
            evento=self.evento, descrizione="Chiudere valvola gas", proposto_da=self.proponente,
        )
        self.template_iniziali = ChecklistTaskTemplate.objects.count()

    def _payload(self):
        return {"decisione": "approva", "aggiungi_al_template": "on", "note_admin": "ok"}

    def test_doppia_approvazione_non_duplica_voce_ne_template(self):
        self.client.force_login(self.admin)
        url = reverse("checklist_operativa:proposta_decidi", args=[self.proposta.pk])

        prima = self.client.post(url, self._payload())
        seconda = self.client.post(url, self._payload())

        self.assertEqual(prima.status_code, 302)
        self.assertEqual(seconda.status_code, 302, "La seconda decisione non deve produrre un 500.")
        self.assertEqual(self.evento.voci.count(), 1)
        self.assertEqual(ChecklistTaskTemplate.objects.count(), self.template_iniziali + 1)
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_APPROVATA)

    def test_rifiuto_dopo_approvazione_non_cambia_lo_stato(self):
        self.client.force_login(self.admin)
        url = reverse("checklist_operativa:proposta_decidi", args=[self.proposta.pk])
        self.client.post(url, self._payload())
        self.client.post(url, {"decisione": "rifiuta", "note_admin": "ripensamento"})

        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_APPROVATA)
        self.assertEqual(self.evento.voci.count(), 1)

    def test_approvazione_concorrente_simulata_la_seconda_e_un_errore_di_stato(self):
        """Due richieste che leggono la stessa proposta «in attesa».

        Il lock di riga le mette in fila: la seconda rilegge lo stato dentro la
        transazione e trova la proposta già gestita — errore di dominio, non un
        secondo template.
        """
        decidi_proposta(self.proposta.pk, approva=True, aggiungi_al_template=True, user=self.admin)
        with self.assertRaises(ChecklistStatoError):
            decidi_proposta(self.proposta.pk, approva=True, aggiungi_al_template=True, user=self.admin)

        self.assertEqual(self.evento.voci.count(), 1)
        self.assertEqual(ChecklistTaskTemplate.objects.count(), self.template_iniziali + 1)

    def test_errore_durante_approvazione_annulla_tutto(self):
        with mock.patch.object(ChiusuraVoce.objects, "create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                decidi_proposta(
                    self.proposta.pk, approva=True, aggiungi_al_template=True, user=self.admin,
                )

        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_IN_ATTESA)
        self.assertIsNone(self.proposta.template_generato_id)
        self.assertEqual(ChecklistTaskTemplate.objects.count(), self.template_iniziali)
        self.assertEqual(self.evento.voci.count(), 0)

    def test_proposta_su_evento_chiuso_non_genera_voce(self):
        chiudi_evento(self.evento.pk)
        with self.assertRaises(ChecklistStatoError):
            decidi_proposta(self.proposta.pk, approva=True, user=self.admin)

        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_IN_ATTESA)
        self.assertEqual(self.evento.voci.count(), 0)

    def test_rifiuto_resta_possibile_anche_su_evento_chiuso(self):
        chiudi_evento(self.evento.pk)
        decidi_proposta(self.proposta.pk, approva=False, note_admin="non serve", user=self.admin)
        self.proposta.refresh_from_db()
        self.assertEqual(self.proposta.stato, ChiusuraProposta.STATO_RIFIUTATA)


# ---------------------------------------------------------------------------
# Generazione voci: idempotente e protetta dal vincolo di database
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GenerazioneIdempotenteTests(TestCase):
    def setUp(self):
        self.evento = ChiusuraEvento.objects.create(
            nome="Generazione", data_inizio=timezone.localdate(),
        )
        self.template = ChecklistTaskTemplate.objects.create(
            ordine=1, descrizione="Chiudere aria compressa", attivo=True,
        )

    def test_rigenerazione_non_duplica_le_voci(self):
        prima = genera_voci_da_template(self.evento)
        seconda = genera_voci_da_template(self.evento)

        self.assertGreater(prima, 0)
        self.assertEqual(seconda, 0)
        self.assertEqual(self.evento.voci.filter(template=self.template).count(), 1)

    def test_vincolo_db_rifiuta_lo_stesso_template_due_volte(self):
        genera_voci_da_template(self.evento)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChiusuraVoce.objects.create(
                    evento=self.evento, template=self.template, descrizione="Doppione",
                )

    def test_voci_manuali_senza_template_restano_ripetibili(self):
        ChiusuraVoce.objects.create(evento=self.evento, descrizione="Manuale 1")
        ChiusuraVoce.objects.create(evento=self.evento, descrizione="Manuale 2")
        self.assertEqual(self.evento.voci.filter(template__isnull=True).count(), 2)

    def test_generazione_rifiutata_su_evento_chiuso(self):
        chiudi_evento(self.evento.pk)
        with self.assertRaises(ChecklistStatoError):
            genera_voci_da_template(self.evento)


# ---------------------------------------------------------------------------
# Prestazioni: la lista di riepilogo non cresce col numero di eventi
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiepilogoQueryCountTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-perf", password="pass12345")
        self.client.force_login(self.admin)

    def _crea_eventi(self, quanti: int, prefisso: str):
        oggi = timezone.localdate()
        for i in range(quanti):
            evento = ChiusuraEvento.objects.create(
                nome=f"{prefisso}-{i}", data_inizio=oggi + timedelta(days=i),
            )
            for j in range(3):
                ChiusuraVoce.objects.create(
                    evento=evento, ordine=j, descrizione=f"Task {j}", confermato=bool(j % 2),
                )

    def _query_riepilogo(self) -> int:
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("checklist_operativa:riepilogo"))
            self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_query_costanti_al_crescere_degli_eventi(self):
        self._crea_eventi(2, "A")
        self._query_riepilogo()  # giro a vuoto: scalda sessione e cache ACL
        con_due = self._query_riepilogo()
        self._crea_eventi(6, "B")
        con_otto = self._query_riepilogo()

        self.assertEqual(
            con_due, con_otto,
            "Il riepilogo deve annotare i conteggi: nessuna query per evento.",
        )
        # Cintura: la pagina resta comunque su una manciata di query (sessione,
        # utente, ACL, elenco eventi).
        self.assertLess(con_otto, 15)

    def test_percentuale_coerente_con_l_annotazione(self):
        self._crea_eventi(1, "C")
        from .services import eventi_con_progresso

        evento = eventi_con_progresso().get(nome="C-0")
        self.assertEqual(evento.voci_totali, 3)
        self.assertEqual(evento.voci_confermate, 1)
        self.assertEqual(evento.percentuale_completamento, 33)

        # Senza annotazione le proprieta' restano valide per gli altri chiamanti.
        semplice = ChiusuraEvento.objects.get(nome="C-0")
        self.assertEqual(semplice.voci_totali, 3)
        self.assertEqual(semplice.voci_confermate, 1)
        self.assertEqual(semplice.percentuale_completamento, 33)


# ---------------------------------------------------------------------------
# Export PDF del riepilogo: il modulo ha sostituito un Excel che si archiviava
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RiepilogoPdfTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="co-pdf", password="pass12345")
        _, self.dipendente = _crea_utente_con_dipendente("co-pdf-resp", "Ada", "Neri")
        self.evento = ChiusuraEvento.objects.create(
            nome="Ferie da archiviare", data_inizio=timezone.localdate(),
            data_fine=timezone.localdate() + timedelta(days=10),
        )
        ChiusuraVoce.objects.create(
            evento=self.evento, ordine=1, descrizione="Chiudere il gas",
            responsabile=self.dipendente, confermato=True,
            confermato_da=self.dipendente, confermato_il=timezone.now(), note="fatto alle 18",
        )
        ChiusuraVoce.objects.create(evento=self.evento, ordine=2, descrizione="Spegnere le luci")

    def test_pdf_scaricabile_da_chi_configura(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("checklist_operativa:riepilogo_detail_pdf", args=[self.evento.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("Ferie", response["Content-Disposition"])

    def test_pdf_negato_senza_permesso(self):
        self.client.force_login(_crea_utente("co-pdf-nope"))
        response = self.client.get(
            reverse("checklist_operativa:riepilogo_detail_pdf", args=[self.evento.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_nome_file_normalizzato(self):
        self.evento.nome = 'Ferie "estive"/2026'
        self.evento.save(update_fields=["nome"])
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("checklist_operativa:riepilogo_detail_pdf", args=[self.evento.pk])
        )
        disposition = response["Content-Disposition"]
        for pericoloso in ('"/', "\\"):
            self.assertNotIn(pericoloso, disposition.split("filename=", 1)[1].strip('"'))
