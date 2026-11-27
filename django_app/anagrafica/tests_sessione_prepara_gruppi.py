"""Percorso «Prepara la sessione», seconda parte: gruppi, sala, avvisi, programma
per giornata, «come l'ultima edizione». Dati sintetici.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente
from tasks.models import MeetingRoom

from .models_formazione import (TrainingCourse, TrainingEnrollment, TrainingLesson, TrainingLessonAttendance,
                                TrainingPlan, TrainingSession, TrainingSessionArgomento)
from .services import formazione_preparazione as prep
from .services.formazione_pianificazione import aggiungi_lavorativi
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class PreparaGruppiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("spg_admin", "spg@example.invalid", "x")
        self.client.force_login(self.admin)
        self.pp = [AnagraficaDipendente.objects.create(nome=f"N{i}", cognome=f"PROVA{i}", reparto="A" if i < 2 else "B",
                                                       aliasusername=f"spg.{i}") for i in range(4)]
        piano = TrainingPlan.objects.create(codice="P-SPG", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-SPG", titolo="Corso gruppi",
                                                   durata_ore_teorica=8, is_active=True)
        self.lun = date.today() + timedelta(days=(7 - date.today().weekday()))
        self.sala = MeetingRoom.objects.create(nome="Aula Prova", capienza=2)
        self.sess = self._sessione("C-SPG-26E1", self.lun)
        for i in range(2):
            TrainingLesson.objects.create(sessione=self.sess, numero=i + 1, data=self.lun + timedelta(days=i),
                                          ora_inizio=time(8), ora_fine=time(12), argomento="G")
        self.isc = [TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=p.pk) for p in self.pp]

    def _sessione(self, codice, inizio, **kw):
        return TrainingSession.objects.create(corso=kw.pop("corso", self.corso), codice_sessione=codice, modalita="IN_SEDE",
                                              data_inizio=inizio, data_fine=inizio + timedelta(days=1), **kw)

    def _azione(self, azione, dati, sess=None):
        return self.client.post(reverse("anagrafica:formazione_sessione_prepara", args=[(sess or self.sess).pk]) + f"{azione}/", dati)

    def test_passo_gruppi_tra_iscritti_e_pronta(self):
        r = self.client.get(reverse("anagrafica:formazione_sessione_prepara", args=[self.sess.pk]) + "?passo=gruppi")
        self.assertContains(r, "Tutti insieme")
        self.assertContains(r, 'id="sp-lavagna"')
        # i gruppi sono facoltativi: la sessione è pronta anche senza
        from .views_sessione_prepara import stato_preparazione
        self.assertTrue(stato_preparazione(self.sess)["completa"])

    def test_dividi_stesso_giorno_orari_diversi_con_assegnazione(self):
        dati = {"n_gruppi": "2", "modello": "orari", "ora_1": "13:00"}
        for i, p in enumerate(self.pp):
            dati[f"a_{p.pk}"] = "0" if i < 2 else "1"
        self._azione("dividi", dati)
        self.sess.refresh_from_db()
        gemella = self.sess.sessioni_gemelle().get()
        self.assertEqual(sorted(gemella.iscrizioni.values_list("legacy_anagrafica_id", flat=True)),
                         sorted(p.pk for p in self.pp[2:]))
        lz = list(gemella.lezioni.order_by("data"))
        self.assertEqual([(x.data, x.ora_inizio, x.ora_fine) for x in lz],
                         [(self.lun, time(13), time(17)), (self.lun + timedelta(days=1), time(13), time(17))])

    def test_dividi_giorni_lavorativi_e_libero(self):
        self.assertEqual(aggiungi_lavorativi(self.lun + timedelta(days=4), 1), self.lun + timedelta(days=7))
        self._azione("dividi", {"n_gruppi": "3", "modello": "libero"})
        self.sess.refresh_from_db()
        gemelle = list(self.sess.sessioni_gemelle())
        self.assertEqual(len(gemelle), 2)
        self.assertFalse(TrainingLesson.objects.filter(sessione__in=gemelle).exists())

    def test_dividi_oltre_mezzanotte_non_crea_niente(self):
        self._azione("dividi", {"n_gruppi": "2", "modello": "orari", "ora_1": "22:00"})
        self.assertFalse(self.sess.sessioni_gemelle().exists())

    def test_sposta_fra_gruppi_e_chi_ha_firmato_resta(self):
        self._azione("dividi", {"n_gruppi": "2", "modello": "giorni", "giorni": "2"})
        self.sess.refresh_from_db()
        gemella = self.sess.sessioni_gemelle().get()
        resta = self.sess.iscrizioni.first()
        TrainingLessonAttendance.objects.create(lezione=self.sess.lezioni.first(),
                                                legacy_anagrafica_id=resta.legacy_anagrafica_id, stato_presenza="PRESENTE")
        altra = self.sess.iscrizioni.exclude(pk=resta.pk).first()
        self._azione("sposta", {f"m_{resta.pk}": gemella.pk, f"m_{altra.pk}": gemella.pk})
        resta.refresh_from_db()
        altra.refresh_from_db()
        self.assertEqual(resta.sessione_id, self.sess.pk)
        self.assertEqual(altra.sessione_id, gemella.pk)

    def test_sala_scelta_posti_e_occupata(self):
        self._azione("sala", {"sala": self.sala.pk})
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.sala, self.sala)
        self.assertEqual(self.sess.sede, "Aula Prova")
        altra = self._sessione("C-SPG-26E9", self.lun, sala=self.sala)
        TrainingLesson.objects.create(sessione=altra, numero=1, data=self.lun, ora_inizio=time(10), ora_fine=time(11), argomento="X")
        r = self.client.get(reverse("anagrafica:formazione_sessione_prepara", args=[self.sess.pk]) + "?passo=giornate")
        self.assertContains(r, "Aula Prova già occupata 10:00–11:00")
        r = self.client.get(reverse("anagrafica:formazione_sessione_prepara", args=[self.sess.pk]) + "?passo=iscritti")
        self.assertContains(r, "la sala Aula Prova ha 2 posti")

    def test_sala_occupata_vista_da_reception_e_kickoff(self):
        self.sess.sala = self.sala
        self.sess.save()
        from reception.sale import verifica
        self.assertIn("formazione", verifica(self.sala, self.lun, time(9), time(10)))
        self.assertEqual(verifica(self.sala, self.lun, time(13), time(14)), "")
        from tasks.services.sale import disponibilita_giorno
        sale = disponibilita_giorno(self.lun, sale=[self.sala])["sale"]
        self.assertEqual(len(sale[0]["blocchi"]), 1)

    def test_prenota_senza_outlook_non_rompe(self):
        self.sess.sala = self.sala
        self.sess.save()
        r = self._azione("prenota", {})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.sess.lezioni.exclude(outlook_event_id="").exists())

    def test_avviso_iscritto_a_altro_corso_stesse_ore(self):
        altro = TrainingCourse.objects.create(piano=self.corso.piano, codice="C-ALT", titolo="Altro", durata_ore_teorica=1, is_active=True)
        s = self._sessione("C-ALT-26E1", self.lun, corso=altro)
        TrainingLesson.objects.create(sessione=s, numero=1, data=self.lun, ora_inizio=time(11), ora_fine=time(12), argomento="X")
        TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=self.pp[0].pk)
        esito = prep.conflitti_persone(self.sess, list(self.sess.lezioni.all()), [p.pk for p in self.pp])
        self.assertEqual(list(esito), [self.pp[0].pk])
        self.assertIn("C-ALT-26E1", esito[self.pp[0].pk][0])

    def test_copia_giornate_dall_ultima_edizione(self):
        nuova = self._sessione("C-SPG-26E2", self.lun + timedelta(days=14))
        self.assertEqual(prep.ultima_edizione(nuova), self.sess)
        self._azione("copia", {"sorgente": self.sess.pk}, sess=nuova)
        self.assertEqual(list(nuova.lezioni.values_list("data", "ora_inizio")),
                         [(self.lun + timedelta(days=14), time(8)), (self.lun + timedelta(days=15), time(8))])

    def test_programma_per_giornata(self):
        voci = [TrainingSessionArgomento.objects.create(sessione=self.sess, ordine=i, argomento=f"A{i}") for i in range(2)]
        g1, g2 = self.sess.lezioni.order_by("numero")
        self._azione("programma", {f"p_{g1.pk}_{voci[0].pk}": "on", f"p_{g2.pk}_{voci[1].pk}": "on"})
        self.assertEqual(list(g1.argomenti_svolti.all()), [voci[0]])
        self.assertEqual(list(g2.argomenti_svolti.all()), [voci[1]])

    def test_come_ultima_edizione_nel_form_e_sala(self):
        self.sess.sala = self.sala
        self.sess.save()
        r = self.client.get(reverse("anagrafica:formazione_sessione_create"))
        self.assertContains(r, "Come l'ultima edizione")
        self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": self.corso.pk, "modalita": "IN_SEDE", "data_inizio": (self.lun + timedelta(days=28)).isoformat(),
            "come_edizione": self.sess.pk})
        nuova = TrainingSession.objects.order_by("-pk").first()
        self.assertEqual(nuova.sala, self.sala)
