"""E-learning professionale (prompt 05, rilascio 2): tempo lato server, quiz con token,
completamento univoco, regole FAD con conferma RSPP, assegnazioni automatiche,
cruscotto e registro, video. Dati sintetici.
"""
from __future__ import annotations

import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_elearning import TrainingElearningCompletamento, TrainingElearningSessione
from .models_formazione import (
    TrainingAssignment, TrainingCompletionRule, TrainingElearningEnrollment, TrainingEmployeeRecord,
    TrainingQuizAttempt, TrainingQuizOption, TrainingQuizQuestion, TrainingSlide,
)
from .services import elearning_assegnazioni, elearning_completamento, elearning_quiz, elearning_tracciamento
from .services.elearning_regole import regola_corso
from .tests_elearning_sicurezza import _Base, _discente

User = get_user_model()


def _indietro(enr, secondi):
    TrainingElearningSessione.objects.filter(enrollment=enr, chiusa=False).update(
        ultimo_beat_il=timezone.now() - timedelta(seconds=secondi))


class _Pro(_Base):
    def _regola(self, **campi):
        regola, _ = TrainingCompletionRule.objects.get_or_create(corso=self.corso)
        for k, v in campi.items():
            setattr(regola, k, v)
        regola.save()
        return regola

    def _enr(self):
        return TrainingElearningEnrollment.objects.get(corso=self.corso, legacy_anagrafica_id=self.lid)

    def _beat(self, slide, **extra):
        import json
        corpo = {"slide_id": slide.pk, "visibile": True, "inattivo_ms": 1000, **extra}
        return self.client.post(reverse("anagrafica:formazione_online_beat", args=[self.corso.pk]),
                                json.dumps(corpo), content_type="application/json")


class HeartbeatTests(_Pro):
    def setUp(self):
        super().setUp()
        self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        self.s1 = self.corso.slides.get(ordine=1)
        self._slide(1)

    def test_troppo_presto_nessun_credito(self):
        r = self._beat(self.s1).json()
        self.assertEqual(r["motivo"], "troppo_presto")
        self.assertEqual(self._enr().secondi_accreditati, 0)

    def test_credito_limitato_e_misurato_dal_server(self):
        _indietro(self._enr(), 45)
        r = self._beat(self.s1).json()
        self.assertTrue(r["ok"])
        self.assertTrue(40 <= r["credito"] <= 60)
        self.assertEqual(self._enr().secondi_accreditati, r["credito"])

    def test_inattivo_o_slide_non_corrente_o_nascosto_nessun_credito(self):
        s2 = self.corso.slides.get(ordine=2)
        for extra, slide, motivo in (({"inattivo_ms": 999999}, self.s1, "inattivo"),
                                     ({}, s2, "slide_non_corrente"),
                                     ({"visibile": False}, self.s1, "pagina_non_visibile")):
            _indietro(self._enr(), 45)
            self.assertEqual(self._beat(slide, **extra).json()["motivo"], motivo)
        self.assertEqual(self._enr().secondi_accreditati, 0)

    def test_una_sola_sessione_attiva(self):
        self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        self.assertEqual(TrainingElearningSessione.objects.filter(enrollment=self._enr(), chiusa=False).count(), 1)
        self.assertEqual(TrainingElearningSessione.objects.filter(enrollment=self._enr()).count(), 2)


class RegoleFruizioneTests(_Pro):
    def test_permanenza_minima_per_slide(self):
        self._regola(el_secondi_minimi_slide=60)
        self.client.get(reverse("anagrafica:formazione_online_player", args=[self.corso.pk]))
        self.assertEqual(self._slide(1).status_code, 200)
        self.assertEqual(self._slide(2).status_code, 409)  # slide 1 non ancora completata
        s1 = self.corso.slides.get(ordine=1)
        for _ in range(2):
            _indietro(self._enr(), 45)
            self._beat(s1)
        self.assertEqual(self._slide(2).status_code, 200)

    def test_tempo_minimo_prima_del_quiz(self):
        self._regola(el_tempo_minimo_minuti=1)
        self._vedi_tutte()
        r = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TrainingQuizAttempt.objects.exists())


class QuizTokenTests(_Pro):
    def setUp(self):
        super().setUp()
        for i in range(2, 6):
            q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=i, testo=f"D{i}")
            TrainingQuizOption.objects.create(domanda=q, testo="ok", corretta=True, ordine=1)
            TrainingQuizOption.objects.create(domanda=q, testo="no", corretta=False, ordine=2)

    def test_estrazione_casuale_e_set_servito(self):
        self._regola(el_domande_estratte=2)
        self._vedi_tutte()
        r = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(len(r.context["domande"]), 2)
        t = TrainingQuizAttempt.objects.get(token=r.context["token"])
        self.assertEqual((t.stato, len(t.domande_servite_json)), ("APERTO", 2))
        # Ricaricare non apre un altro tentativo.
        r2 = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(r2.context["token"], t.token)

    def test_token_usato_o_scaduto_rifiutato(self):
        self._vedi_tutte()
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        token = self.client.get(url).context["token"]
        self.client.post(url, {"token": token})
        self.client.post(url, {"token": token})  # già inviato
        self.assertEqual(self._enr().n_tentativi, 1)
        enr = self._enr()
        regola = regola_corso(self.corso)
        t = elearning_quiz.apri_tentativo(enr, regola, [1, 2, 3])
        TrainingQuizAttempt.objects.filter(pk=t.pk).update(scade_il=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(elearning_quiz.QuizNonDisponibile):
            elearning_quiz.correggi(enr, t.token, {}, regola)
        self.assertEqual(TrainingQuizAttempt.objects.get(pk=t.pk).stato, "SCADUTO")

    def test_opzioni_estranee_ignorate(self):
        self._vedi_tutte()
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        token = self.client.get(url).context["token"]
        altra = TrainingQuizOption.objects.exclude(domanda=self.q).first()
        self.client.post(url, {"token": token, f"q_{self.q.pk}": [self.giusta.pk, altra.pk]})
        t = TrainingQuizAttempt.objects.get(token=token)
        voce = next(x for x in t.risposte_json["risposte"] if x["domanda_id"] == self.q.pk)
        self.assertEqual(voce["scelte"], [self.giusta.pk])

    def test_attesa_tra_tentativi(self):
        self._regola(el_attesa_minuti_tra_tentativi=10, confermata_rspp_il=None)
        self._vedi_tutte()
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        token = self.client.get(url).context["token"]
        self.client.post(url, {"token": token})  # tutto sbagliato
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)


class CompletamentoTests(_Pro):
    def test_una_sola_riga_di_registro_con_impronta(self):
        self._vedi_tutte()
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        token = self.client.get(url).context["token"]
        with self.captureOnCommitCallbacks(execute=False):
            self.client.post(url, {"token": token, f"q_{self.q.pk}": [self.giusta.pk]})
        enr = self._enr()
        t = TrainingQuizAttempt.objects.get(token=token)
        elearning_completamento.completa(enr, tentativo=t)  # ripetuto: idempotente
        self.assertEqual(TrainingElearningCompletamento.objects.filter(enrollment=enr).count(), 1)
        self.assertEqual(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=self.lid).count(), 1)
        c = TrainingElearningCompletamento.objects.get(enrollment=enr)
        self.assertEqual(len(c.sha256), 64)
        self.assertEqual(c.verifica_json["slide_completate"], 3)

    def test_requisiti_mancanti_niente_record(self):
        self._regola(el_tempo_minimo_minuti=5)
        enr = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=self.lid,
                                                         ultima_slide_ordine=3)
        with self.assertRaises(elearning_completamento.RequisitiNonSoddisfatti):
            elearning_completamento.completa(enr, tentativo=None)
        self.assertFalse(TrainingEmployeeRecord.objects.exists())


class RegoleFadEPubblicazioneTests(_Pro):
    def setUp(self):
        super().setUp()
        self.hr = User.objects.create_user("hr.fad", "hr@example.invalid", "x")
        self.admin = User.objects.create_superuser("rspp.fad", "rspp@example.invalid", "x")

    def test_pubblicazione_bloccata_senza_conferma_rspp(self):
        self.corso.stato = "BOZZA"
        self.corso.save()
        self.client.force_login(self.admin)
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "BOZZA")
        url = reverse("anagrafica:elearning_regola_corso", args=[self.corso.pk])
        self.client.post(url, {"azione": "conferma"})
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "ATTIVO")

    def test_modifica_annulla_la_conferma(self):
        self.client.force_login(self.admin)
        url = reverse("anagrafica:elearning_regola_corso", args=[self.corso.pk])
        self.client.post(url, {"azione": "conferma"})
        self.assertTrue(regola_corso(self.corso).confermata_rspp)
        dati = {"el_tempo_minimo_minuti": 30, "el_richiede_tutte_slide": "on", "el_secondi_minimi_slide": 0,
                "el_inattivita_secondi": 120, "el_richiede_quiz": "on", "el_max_tentativi": 0,
                "el_attesa_minuti_tra_tentativi": 0, "el_domande_estratte": 0, "el_mescola": "on",
                "el_tempo_quiz_minuti": 0, "rspp_note": ""}
        self.client.post(url, dati)
        self.assertFalse(regola_corso(self.corso).confermata_rspp)
        self.assertEqual(regola_corso(self.corso).tempo_minimo_minuti, 30)


class AssegnazioniAutomaticheTests(_Pro):
    def test_da_regola_mansione_idempotente_e_rinnovo(self):
        from core.legacy_models import AnagraficaDipendente
        from .models import Mansione
        from .models_formazione import TrainingRequirementRule
        mansione = Mansione.objects.create(nome="Addetto EL")
        AnagraficaDipendente.objects.filter(pk=self.lid).update(mansione="Addetto EL")
        TrainingAssignment.objects.all().delete()
        TrainingRequirementRule.objects.create(corso=self.corso, mansione=mansione)
        with self.captureOnCommitCallbacks(execute=True):
            esito = elearning_assegnazioni.sincronizza([self.lid])
        self.assertEqual(esito["assegnate"], 1)
        a = TrainingAssignment.objects.get(corso=self.corso, legacy_anagrafica_id=self.lid)
        self.assertEqual((a.ciclo, a.stato), (1, "ASSEGNATO"))
        self.assertIsNotNone(a.due_date)
        elearning_assegnazioni.sincronizza([self.lid])
        self.assertEqual(TrainingAssignment.objects.filter(corso=self.corso).count(), 1)
        # Ciclo 1 completato e in scadenza entro la finestra: si apre il ciclo 2.
        TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=self.lid, stato="COMPLETATO")
        TrainingEmployeeRecord.objects.create(
            corso=self.corso, legacy_anagrafica_id=self.lid, idoneo=True,
            data_completamento=timezone.localdate() - timedelta(days=700),
            data_scadenza=timezone.localdate() + timedelta(days=20))
        esito = elearning_assegnazioni.sincronizza([self.lid])
        self.assertEqual(esito["rinnovi"], 1)
        self.assertTrue(TrainingAssignment.objects.filter(corso=self.corso, legacy_anagrafica_id=self.lid, ciclo=2).exists())


class CruscottoRegistroTests(_Pro):
    def test_pagine_ed_export(self):
        admin = User.objects.create_superuser("dir.el", "dir@example.invalid", "x")
        self.client.force_login(admin)
        for nome in ("elearning_cruscotto", "elearning_registro", "elearning_impostazioni_corsi"):
            self.assertEqual(self.client.get(reverse(f"anagrafica:{nome}")).status_code, 200, nome)
        for chiave in ("elearning_registro", "elearning_copertura"):
            r = self.client.get(reverse("anagrafica:export", args=[chiave]), {"format": "xlsx", "scope": "full"})
            self.assertEqual(r.status_code, 200, chiave)

    def test_discente_senza_permessi_non_vede_il_cruscotto(self):
        self.assertIn(self.client.get(reverse("anagrafica:elearning_cruscotto")).status_code, (302, 403))


class VideoTests(_Pro):
    def test_video_finto_rifiutato_e_range(self):
        import tempfile
        from django.test import override_settings
        admin = User.objects.create_superuser("vid.el", "v@example.invalid", "x")
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            self.client.force_login(admin)
            finto = SimpleUploadedFile("v.mp4", b"<html>no</html>", content_type="video/mp4")
            self.client.post(reverse("anagrafica:formazione_slide_video_upload", args=[self.corso.pk]),
                             {"titolo": "Finto", "video": finto})
            self.assertFalse(TrainingSlide.objects.filter(tipo="VIDEO").exists())
            slide = TrainingSlide(corso=self.corso, ordine=9, titolo="V", tipo="VIDEO")
            from django.core.files.base import ContentFile
            slide.video.save("v.mp4", ContentFile(b"0123456789" * 10), save=True)
            r = self.client.get(reverse("anagrafica:formazione_slide_video", args=[slide.pk]), HTTP_RANGE="bytes=10-19")
            self.assertEqual(r.status_code, 206)
            self.assertEqual(b"".join(r.streaming_content), b"0123456789")
            self.assertEqual(r["Content-Range"], "bytes 10-19/100")
