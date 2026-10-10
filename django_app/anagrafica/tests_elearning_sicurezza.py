"""E-learning, rilascio 1: accesso, avanzamento, quiz e completamento verificati lato server.

Discenti e corsi **sintetici**. Ogni test chiude una falla trovata nella
ricognizione del prompt 05.
"""
from __future__ import annotations

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica, Profile

from .models_formazione import (
    ElearningConfig, TrainingAssignment, TrainingCourse, TrainingElearningEnrollment, TrainingEmployeeRecord,
    TrainingPlan, TrainingQuizOption, TrainingQuizQuestion, TrainingSlide,
)

User = get_user_model()


def _discente(username: str):
    utente = UtenteLegacy.objects.create(nome=username, email=f"{username}@example.invalid", password="x")
    user = User.objects.create_user(username, f"{username}@example.invalid", "x")
    Profile.objects.create(user=user, legacy_user_id=utente.id)
    # Onboarding del portale completato: evita il redirect del middleware.
    from django.utils import timezone
    from core.models import UserOnboarding
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
    dip = AnagraficaDipendente.objects.create(nome="Nome", cognome=username, aliasusername=username, utente=utente)
    return user, dip.id, utente.id


class _Base(TestCase):
    def setUp(self):
        piano = TrainingPlan.objects.create(codice="PEL", nome="Piano e-learning")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="EL1", titolo="Sicurezza online", durata_ore_teorica=1,
            is_elearning=True, is_active=True, stato="ATTIVO", obbligatorio=True, quiz_punteggio_minimo=100,
        )
        # Online solo con le regole FAD confermate dall'RSPP.
        from django.utils import timezone
        from .models_formazione import TrainingCompletionRule
        TrainingCompletionRule.objects.create(corso=self.corso, confermata_rspp_il=timezone.now())
        for i in (1, 2, 3):
            TrainingSlide.objects.create(corso=self.corso, ordine=i, titolo=f"Slide {i}", contenuto=f"Testo {i}")
        self.q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="Domanda?")
        self.giusta = TrainingQuizOption.objects.create(domanda=self.q, testo="Giusta", corretta=True, ordine=1)
        self.sbagliata = TrainingQuizOption.objects.create(domanda=self.q, testo="Sbagliata", corretta=False, ordine=2)
        self.user, self.lid, self.uid = _discente("discente.el")
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=self.lid, stato="ASSEGNATO")
        self.client.force_login(self.user)

    def _slide(self, ordine):
        return self.client.get(reverse("anagrafica:formazione_online_slide", args=[self.corso.pk, ordine]),
                               HTTP_HX_REQUEST="true")

    def _vedi_tutte(self):
        self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        for o in (1, 2, 3):
            self.assertEqual(self._slide(o).status_code, 200)

    def _quiz(self, opzione):
        """Apre il quiz (GET: token del tentativo servito) e invia la risposta."""
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        g = self.client.get(url)
        token = (g.context or {}).get("token", "") if g.status_code == 200 else ""
        return self.client.post(url, {"token": token, f"q_{self.q.pk}": [opzione.pk]})


class AccessoTests(_Base):
    def test_bozza_non_accessibile_e_nessun_record(self):
        self.corso.stato = "BOZZA"
        self.corso.save()
        r = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(r.status_code, 302)
        self._quiz(self.giusta)
        self.assertFalse(TrainingEmployeeRecord.objects.exists())
        self.assertEqual(self._slide(1).status_code, 403)

    def test_obbligatorio_non_assegnato_negato(self):
        altro, _lid, _uid = _discente("altro.el")
        self.client.force_login(altro)
        self.assertEqual(self._slide(1).status_code, 403)
        r = self.client.get(reverse("anagrafica:formazione_online_catalog"))
        self.assertNotContains(r, "Sicurezza online")

    def test_facoltativo_in_self_service(self):
        self.corso.elearning_self_service = True
        self.corso.save()
        altro, _lid, _uid = _discente("facoltativo.el")
        self.client.force_login(altro)
        self.assertContains(self.client.get(reverse("anagrafica:formazione_online_catalog")), "Sicurezza online")
        self.assertEqual(self._slide(1).status_code, 200)

    def test_immagine_slide_negata_a_chi_non_ha_accesso(self):
        altro, _lid, _uid = _discente("img.el")
        self.client.force_login(altro)
        slide = self.corso.slides.first()
        self.assertEqual(self.client.get(reverse("anagrafica:formazione_slide_image", args=[slide.pk])).status_code, 403)


class AvanzamentoEQuizTests(_Base):
    def test_slide_saltate_non_servite(self):
        self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        self.assertEqual(self._slide(3).status_code, 409)
        self.assertEqual(self._slide(1).status_code, 200)
        self.assertEqual(self._slide(3).status_code, 409)

    def test_quiz_chiuso_senza_tutte_le_slide(self):
        self._slide(1)
        self._quiz(self.giusta)
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_risposte_corrette_mai_nell_html_del_quiz(self):
        self._vedi_tutte()
        r = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertContains(r, "Giusta")
        self.assertNotContains(r, "corretta")
        self.assertNotContains(r, "fm-quiz-q is-ok")

    def test_feedback_per_domanda_solo_a_quiz_superato(self):
        self._vedi_tutte()
        r = self._quiz(self.sbagliata)
        self.assertContains(r, "Quiz non superato")
        self.assertNotContains(r, "fm-quiz-q is-ko")

    def test_completamento_una_volta_sola(self):
        self._vedi_tutte()
        with self.captureOnCommitCallbacks(execute=True):
            self._quiz(self.giusta)
        self._quiz(self.giusta)  # ripetuto: il corso è già completato
        self.assertEqual(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=self.lid).count(), 1)
        enr = TrainingElearningEnrollment.objects.get(corso=self.corso, legacy_anagrafica_id=self.lid)
        self.assertEqual((enr.stato, enr.n_tentativi), ("COMPLETATO", 1))
        self.assertEqual(TrainingAssignment.objects.get(corso=self.corso).stato, "COMPLETATO")

    def test_tentativi_esauriti_e_sblocco_hr(self):
        cfg = ElearningConfig.get_instance()
        cfg.max_tentativi_quiz = 1
        cfg.save()
        self._vedi_tutte()
        self._quiz(self.sbagliata)
        self._quiz(self.giusta)  # bloccato: tentativi esauriti
        self.assertFalse(TrainingEmployeeRecord.objects.exists())
        enr = TrainingElearningEnrollment.objects.get(corso=self.corso, legacy_anagrafica_id=self.lid)
        hr = User.objects.create_superuser("hr.el", "hr@example.invalid", "x")
        self.client.force_login(hr)
        self.client.post(reverse("anagrafica:formazione_elearning_sblocca", args=[self.corso.pk, enr.pk]), {"motivo": ""})
        enr.refresh_from_db()
        self.assertEqual(enr.tentativi_extra, 0)  # motivo obbligatorio
        self.client.post(reverse("anagrafica:formazione_elearning_sblocca", args=[self.corso.pk, enr.pk]),
                         {"motivo": "Problema tecnico in aula"})
        enr.refresh_from_db()
        self.assertEqual(enr.tentativi_extra, 1)
        self.client.force_login(self.user)
        self._quiz(self.giusta)
        self.assertTrue(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=self.lid).exists())

    def test_attestato_dopo_il_commit(self):
        from .models_formazione import AttestatoFormazioneConfig
        cfg = AttestatoFormazioneConfig.get_instance()
        cfg.auto_salva_attestato = True
        cfg.save()
        self._vedi_tutte()
        with mock.patch("anagrafica.services.attestato_pdf.archivia_attestato") as archivia:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self._quiz(self.giusta)
            archivia.assert_not_called()  # non dentro la transazione del quiz
            for cb in callbacks:
                cb()
            archivia.assert_called_once()

    def test_anteprima_editor_non_registra(self):
        self.corso.stato = "BOZZA"
        self.corso.save()
        editor = User.objects.create_superuser("editor.el", "ed@example.invalid", "x")
        self.client.force_login(editor)
        r = self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        self.assertContains(r, "Anteprima editor")
        self.client.post(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]),
                         {f"q_{self.q.pk}": [self.giusta.pk]})
        self.assertFalse(TrainingEmployeeRecord.objects.exists())


class PromemoriaTests(_Base):
    def test_notifica_all_utente_del_portale_con_link_al_corso(self):
        # Fase 2: il promemoria al discente lo manda la scaletta, sulle assegnazioni con scadenza.
        from datetime import timedelta
        from django.utils import timezone
        TrainingAssignment.objects.filter(corso=self.corso, legacy_anagrafica_id=self.lid).update(
            due_date=timezone.localdate() + timedelta(days=1))
        out = StringIO()
        call_command("send_elearning_reminders", recipients=["hr@example.invalid"], stdout=out)
        n = Notifica.objects.get(legacy_user_id=self.uid)  # assegnato, mai aperto: ricordato
        self.assertIn(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]), n.url_azione)
        self.assertFalse(Notifica.objects.filter(legacy_user_id=self.lid).exclude(legacy_user_id=self.uid).exists())

    def test_completato_non_ricordato(self):
        TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=self.lid, stato="COMPLETATO")
        call_command("send_elearning_reminders", recipients=["hr@example.invalid"], stdout=StringIO())
        self.assertFalse(Notifica.objects.filter(legacy_user_id=self.uid).exists())

    def test_notifica_all_assegnazione(self):
        from .services.elearning_notifications import notify_corso_assegnato
        notify_corso_assegnato(self.corso.pk, self.lid)
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.uid, tipo="elearning_assegnato").exists())
