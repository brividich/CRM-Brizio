"""Percorso guidato «Prepara la sessione»: dopo la creazione giornate e iscritti
uno dopo l'altro, con ritorno al percorso dopo ogni azione. Dati sintetici.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .models_formazione import TrainingCourse, TrainingEnrollment, TrainingLesson, TrainingPlan, TrainingSession
from .tests import _ensure_anagrafica_table
from .views_sessione_prepara import passi_per, stato_preparazione

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class PreparaSessioneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("sp_admin", "sp@example.invalid", "x")
        self.client.force_login(self.admin)
        self.p = AnagraficaDipendente.objects.create(nome="PIA", cognome="PREPARA", aliasusername="sp.pia.t")
        piano = TrainingPlan.objects.create(codice="P-SP", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-SP", titolo="Corso percorso",
                                                   durata_ore_teorica=8, is_active=True)
        self.lunedi = date.today() + timedelta(days=(7 - date.today().weekday()))  # prossimo lunedì
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="C-SP-26E1", modalita="IN_SEDE",
            data_inizio=self.lunedi, data_fine=self.lunedi + timedelta(days=1),
        )

    def _url(self, sess=None, passo=""):
        u = reverse("anagrafica:formazione_sessione_prepara", args=[(sess or self.sess).pk])
        return f"{u}?passo={passo}" if passo else u

    def _lezione(self):
        return TrainingLesson.objects.create(sessione=self.sess, data=self.lunedi, ora_inizio=time(8),
                                             ora_fine=time(12), argomento="Giornata")

    def test_crea_sessione_in_aula_porta_al_percorso(self):
        r = self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": self.corso.pk, "modalita": "IN_SEDE",
            "data_inizio": self.lunedi.isoformat(), "data_fine": self.lunedi.isoformat(), "sede": "Aula"})
        nuova = TrainingSession.objects.exclude(pk=self.sess.pk).get()
        self.assertRedirects(r, self._url(nuova), fetch_redirect_response=False)

    def test_si_apre_sul_primo_passo_mancante(self):
        r = self.client.get(self._url())
        self.assertContains(r, 'aria-current="step"')
        self.assertContains(r, "Genera le giornate")
        self.assertContains(r, "Salta per ora")
        self._lezione()
        r = self.client.get(self._url())
        self.assertContains(r, "Aggiungi un'altra persona")

    def test_ente_esterno_senza_giornate(self):
        self.sess.modalita = "ESTERNO"
        self.sess.save()
        self.assertEqual(passi_per(self.sess), ["dati", "iscritti", "pronta"])
        r = self.client.get(self._url(passo="giornate"))  # passo non previsto: primo mancante
        self.assertNotContains(r, "Genera le giornate")
        self.assertContains(r, "Iscritti")

    def test_online_va_al_suo_percorso(self):
        self.sess.modalita = "ONLINE"
        self.sess.save()
        r = self.client.get(self._url())
        self.assertRedirects(r, reverse("anagrafica:sessione_online_prepara", args=[self.sess.pk]),
                             fetch_redirect_response=False)

    def test_genera_giornate_torna_al_percorso(self):
        qui = self._url(passo="giornate")
        r = self.client.post(reverse("anagrafica:formazione_lezioni_genera", args=[self.sess.pk]), {
            "ora_inizio": "08:00", "ora_fine": "12:00", "pausa_minuti": "0",
            "giorni_settimana": ["0", "1", "2", "3", "4"], "next": qui})
        self.assertRedirects(r, qui, fetch_redirect_response=False)
        self.assertEqual(self.sess.lezioni.count(), 2)
        self.assertContains(self.client.get(qui), "8 ore pianificate su 8 del corso")

    def test_next_esterno_ignorato(self):
        r = self.client.post(reverse("anagrafica:formazione_iscrizione_add", args=[self.sess.pk]), {
            "legacy_anagrafica_id": self.p.pk, "next": "https://esterno.example/x"})
        self.assertRedirects(r, reverse("anagrafica:formazione_sessione_iscritti", args=[self.sess.pk]),
                             fetch_redirect_response=False)

    def test_iscrivi_e_togli_dal_percorso(self):
        qui = self._url(passo="iscritti")
        r = self.client.post(reverse("anagrafica:formazione_iscrizione_add", args=[self.sess.pk]), {
            "legacy_anagrafica_id": self.p.pk, "next": qui})
        self.assertRedirects(r, qui, fetch_redirect_response=False)
        isc = TrainingEnrollment.objects.get(sessione=self.sess, legacy_anagrafica_id=self.p.pk)
        r = self.client.post(reverse("anagrafica:formazione_iscrizione_delete", args=[self.sess.pk, isc.pk]),
                             {"next": qui})
        self.assertRedirects(r, qui, fetch_redirect_response=False)
        self.assertFalse(TrainingEnrollment.objects.filter(pk=isc.pk).exists())

    def test_pronta_e_riprendi_sulla_sessione(self):
        detail = reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk])
        self.assertContains(self.client.get(detail), "Riprendi la preparazione")
        self._lezione()
        TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=self.p.pk)
        self.assertTrue(stato_preparazione(self.sess)["completa"])
        self.assertNotContains(self.client.get(detail), "Riprendi la preparazione")
        r = self.client.get(self._url())
        self.assertContains(r, "Sessione pronta")
        self.assertContains(r, "QR d'aula")

    def test_edizione_completata_non_si_prepara(self):
        self.sess.stato = "COMPLETATA"
        self.sess.save()
        r = self.client.get(self._url())
        self.assertRedirects(r, reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk]),
                             fetch_redirect_response=False)

    def test_senza_permesso_di_modifica(self):
        semplice = User.objects.create_user("sp_user", "spu@example.invalid", "x")
        self.client.force_login(semplice)
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("/prepara/", r["Location"])
