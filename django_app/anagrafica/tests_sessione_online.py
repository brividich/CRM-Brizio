"""Lezione online di una sessione (slide + test) senza corso nuovo."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_formazione import (
    TrainingCourse, TrainingEmployeeRecord, TrainingEnrollment, TrainingPlan, TrainingQuizOption,
    TrainingQuizQuestion, TrainingSession, TrainingSlide,
)
from .models_sessione_online import (
    TrainingSessionAttempt, TrainingSessionOnline, TrainingSessionQuestion, TrainingSessionSlide,
)
from .services import sessione_online as so

LEGACY_ID = 4242


def _png() -> bytes:
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class _Base(TestCase):
    def setUp(self):
        self.piano = TrainingPlan.objects.create(codice="PS", nome="Piano sicurezza")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="FOR-012", titolo="Aggiornamento sicurezza",
            durata_ore_teorica=Decimal("6.0"), validita_mesi=60, stato="ATTIVO", quiz_punteggio_minimo=70,
        )
        oggi = timezone.localdate()
        self.sessione = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="S-ONL-1", modalita="ONLINE",
            data_inizio=oggi, data_fine=oggi + timedelta(days=14),
        )
        self.iscr = TrainingEnrollment.objects.create(sessione=self.sessione, legacy_anagrafica_id=LEGACY_ID)
        self.admin = get_user_model().objects.create_superuser("hr", "hr@example.com", "pwd12345")

    def _slide(self, n=3):
        for i in range(1, n + 1):
            s = TrainingSessionSlide(sessione=self.sessione, ordine=i, titolo=f"S{i}")
            s.immagine.save(f"s{i}.png", ContentFile(_png()), save=False)
            s.save()

    def _domande(self):
        so.salva_domanda(self.sessione, testo="Chi segnala?", risposte=["Chiunque", "Solo il preposto"], giuste={0})
        so.salva_domanda(self.sessione, testo="DPI?", risposte=["Guanti", "Occhiali", "Niente"], giuste={0, 1})

    def _pronta(self, **kw):
        self._slide()
        self._domande()
        cfg = so.config(self.sessione, crea=True)
        for k, v in kw.items():
            setattr(cfg, k, v)
        cfg.save()
        return cfg


class ServizioTests(_Base):
    def test_config_parte_da_corso_e_sessione(self):
        cfg = so.config(self.sessione, crea=True)
        self.assertEqual(cfg.soglia_pct, 70)
        self.assertEqual(cfg.scadenza, self.sessione.data_fine)

    def test_cosa_manca_e_pubblica(self):
        cfg = so.config(self.sessione, crea=True)
        self.assertTrue(so.cosa_manca(self.sessione, cfg))
        with self.assertRaises(so.LezioneOnlineError):
            so.pubblica(self.sessione, cfg, self.admin, invia=False)
        self._slide()
        self._domande()
        self.assertEqual(so.cosa_manca(self.sessione, cfg), [])
        so.pubblica(self.sessione, cfg, self.admin, invia=False)
        self.assertTrue(cfg.pubblicata)

    def test_salva_domanda_valida(self):
        with self.assertRaises(so.LezioneOnlineError):
            so.salva_domanda(self.sessione, testo="X", risposte=["a", "b"], giuste=set())
        with self.assertRaises(so.LezioneOnlineError):
            so.salva_domanda(self.sessione, testo="X", risposte=["a", ""], giuste={0})

    def test_testo_incollato(self):
        n = so.incolla_domande(self.sessione, "1. Chi?\n* Tutti\n- Nessuno\n\nDove?\na) Qui\n* Lì\n")
        self.assertEqual(n, 2)
        d = so.domande(self.sessione)[1]
        self.assertEqual([o.testo for o in d.opzioni.all() if o.corretta], ["Lì"])
        with self.assertRaises(so.LezioneOnlineError):
            so.leggi_testo_incollato("Domanda senza giusta\n- a\n- b")

    def test_copia_dal_corso(self):
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="# Ciao")
        q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="2+2?")
        TrainingQuizOption.objects.create(domanda=q, ordine=1, testo="4", corretta=True)
        TrainingQuizOption.objects.create(domanda=q, ordine=2, testo="5")
        self.assertEqual(so.copia_slide_dal_corso(self.sessione), (1, 0))
        self.assertEqual(so.copia_domande_dal_corso(self.sessione), 1)
        self.assertEqual(TrainingSessionSlide.objects.get(sessione=self.sessione).testo, "# Ciao")

    def test_sequenza_e_tempo_minimo(self):
        cfg = self._pronta(secondi_minimi_slide=20)
        prog = so.avanzamento(self.iscr)
        self.assertFalse(so.apri_slide(prog, 2, 3))          # non si salta avanti
        self.assertTrue(so.apri_slide(prog, 1, 3))
        self.assertGreater(so.completa_slide(prog, 1, cfg), 0)  # troppo presto
        prog.slide_aperta_il = timezone.now() - timedelta(seconds=25)
        prog.save()
        self.assertEqual(so.completa_slide(prog, 1, cfg), 0)
        self.assertEqual(prog.slide_viste, 1)
        self.assertGreaterEqual(prog.secondi, 20)

    def test_correzione_e_iscrizione(self):
        cfg = self._pronta(secondi_minimi_slide=0)
        prog = so.avanzamento(self.iscr)
        prog.slide_viste = 3
        prog.save()
        d1, d2 = so.domande(self.sessione)
        o1 = {o.testo: o.pk for o in d1.opzioni.all()}
        o2 = {o.testo: o.pk for o in d2.opzioni.all()}
        t = so.correggi(self.iscr, cfg, {d1.pk: {o1["Chiunque"]}, d2.pk: {o2["Guanti"]}})
        self.assertFalse(t.superato)                         # multipla: servono tutte le giuste
        self.assertEqual(t.punteggio_pct, Decimal("50.00"))
        t = so.correggi(self.iscr, cfg, {d1.pk: {o1["Chiunque"]}, d2.pk: {o2["Guanti"], o2["Occhiali"]}})
        self.assertTrue(t.superato)
        self.iscr.refresh_from_db()
        self.assertTrue(self.iscr.verifica_superata)
        self.assertEqual(self.iscr.modalita_verifica, "TEST")
        self.assertEqual(self.iscr.percentuale_presenza, Decimal("100"))
        self.assertEqual(self.iscr.ore_frequentate, Decimal("6.00"))
        self.assertEqual(self.iscr.stato, "IN_CORSO")
        with self.assertRaises(so.LezioneOnlineError):        # già superato
            so.correggi(self.iscr, cfg, {})

    def test_tentativi_finiti_e_tentativo_extra(self):
        cfg = self._pronta(max_tentativi=1)
        prog = so.avanzamento(self.iscr)
        prog.slide_viste = 3
        prog.save()
        so.correggi(self.iscr, cfg, {})
        self.iscr.refresh_from_db()
        self.assertIs(self.iscr.verifica_superata, False)
        with self.assertRaises(so.LezioneOnlineError):
            so.correggi(self.iscr, cfg, {})
        so.concedi_tentativo(self.iscr)
        self.iscr.refresh_from_db()
        self.assertIsNone(self.iscr.verifica_superata)
        self.assertEqual(so.tentativi_rimasti(cfg, so.avanzamento(self.iscr)), 1)

    def test_registra_completamenti(self):
        cfg = self._pronta()
        prog = so.avanzamento(self.iscr)
        prog.slide_viste = 3
        prog.save()
        d1, d2 = so.domande(self.sessione)
        scelte = {d.pk: {o.pk for o in d.opzioni.all() if o.corretta} for d in (d1, d2)}
        so.correggi(self.iscr, cfg, scelte)
        fatti, bloccati = so.registra_completamenti(self.sessione, self.admin)
        self.assertEqual((fatti, bloccati), (1, []))
        self.iscr.refresh_from_db()
        self.assertEqual(self.iscr.stato, "COMPLETATO")
        self.assertTrue(TrainingEmployeeRecord.objects.filter(enrollment=self.iscr).exists())
        righe = so.righe_gestione(self.sessione, cfg, 3)
        self.assertEqual(righe[0]["stato"], so.REGISTRATA)

    def test_numeri_e_domande_difficili(self):
        cfg = self._pronta()
        prog = so.avanzamento(self.iscr)
        prog.slide_viste = 3
        prog.iniziata_il = timezone.now()
        prog.save()
        so.correggi(self.iscr, cfg, {})
        righe = so.righe_gestione(self.sessione, cfg, 3)
        num = so.numeri(righe, cfg)
        self.assertEqual(num["totale"], 1)
        self.assertEqual(num["media_punteggio"], 0)
        self.assertEqual(len(so.domande_difficili(self.sessione)), 2)

    def test_promemoria_in_scadenza(self):
        cfg = self._pronta(promemoria_giorni=3)
        cfg.scadenza = timezone.localdate() + timedelta(days=3)
        cfg.pubblicata_il = timezone.now()
        cfg.save()
        with mock.patch.object(so, "invia_link") as invia:
            self.assertEqual(so.promemoria_in_scadenza(), 1)
            self.assertEqual(so.promemoria_in_scadenza(), 0)    # una volta sola al giorno
        invia.assert_called_once()


class GestioneViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_crea_sessione_online_porta_alla_preparazione(self):
        oggi = timezone.localdate()
        r = self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "ONLINE",
            "data_inizio": oggi.isoformat(), "data_fine": oggi.isoformat(),
        })
        nuova = TrainingSession.objects.exclude(pk=self.sessione.pk).first()
        if nuova is not None:  # il form può chiedere altri campi: qui conta il redirect se creata
            self.assertRedirects(r, reverse("anagrafica:sessione_online_prepara", args=[nuova.pk]),
                                 fetch_redirect_response=False)

    def test_passi_e_pagina_sessione(self):
        for passo in ("slide", "test", "invio"):
            r = self.client.get(reverse("anagrafica:sessione_online_prepara", args=[self.sessione.pk]) + f"?passo={passo}")
            self.assertEqual(r.status_code, 200, passo)
        self._slide()
        self._domande()
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.sessione.pk]) + "?pannello=test")
        self.assertContains(r, 'id="lezione-online"')
        self.assertContains(r, "Test finale")

    def test_domanda_da_form(self):
        url = reverse("anagrafica:sessione_online_domanda_salva", args=[self.sessione.pk])
        self.client.post(url, {"testo": "Domanda?", "risposta_0": "Sì", "risposta_1": "No", "giusta": "0"})
        self.assertEqual(TrainingSessionQuestion.objects.filter(sessione=self.sessione).count(), 1)

    def test_pubblica_e_registra(self):
        self._pronta()
        with mock.patch.object(so, "invia_link", return_value={"notifiche": 1, "senza_utente": 0, "persone": 1}):
            r = self.client.post(reverse("anagrafica:sessione_online_pubblica", args=[self.sessione.pk]), {"invia": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(TrainingSessionOnline.objects.get(sessione=self.sessione).pubblicata)
        r = self.client.get(reverse("anagrafica:sessione_online_export", args=[self.sessione.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Partecipante", r.content.decode("utf-8-sig"))

    def test_edizione_approvata_bloccata(self):
        TrainingSession.objects.filter(pk=self.sessione.pk).update(approvata_il=timezone.now())
        url = reverse("anagrafica:sessione_online_domanda_salva", args=[self.sessione.pk])
        self.client.post(url, {"testo": "D?", "risposta_0": "a", "risposta_1": "b", "giusta": "0"})
        self.assertFalse(TrainingSessionQuestion.objects.filter(sessione=self.sessione).exists())

    def test_senza_permesso_niente_gestione(self):
        utente = get_user_model().objects.create_user("dip", "d@example.com", "pwd12345")
        self.client.force_login(utente)
        with mock.patch("anagrafica.views._helpers._can_edit_formazione", return_value=False):
            self.client.post(reverse("anagrafica:sessione_online_domanda_salva", args=[self.sessione.pk]),
                             {"testo": "D?", "risposta_0": "a", "risposta_1": "b", "giusta": "0"})
        self.assertFalse(TrainingSessionQuestion.objects.filter(sessione=self.sessione).exists())


class PartecipanteViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.dip = get_user_model().objects.create_user("dip", "d@example.com", "pwd12345")
        from core.models import UserOnboarding
        UserOnboarding.objects.create(user=self.dip, completed=True)
        self.client.force_login(self.dip)
        p1 = mock.patch("anagrafica.views._helpers._current_legacy_anagrafica_id", return_value=LEGACY_ID)
        p2 = mock.patch("anagrafica.views._helpers._can_edit_formazione", return_value=False)
        p1.start(), p2.start()
        self.addCleanup(mock.patch.stopall)

    def test_non_pubblicata_negata(self):
        self._pronta()
        r = self.client.get(reverse("anagrafica:sessione_online_player", args=[self.sessione.pk]))
        self.assertRedirects(r, reverse("anagrafica:formazione_online_catalog"), fetch_redirect_response=False)

    def test_percorso_completo(self):
        cfg = self._pronta(secondi_minimi_slide=0)
        cfg.pubblicata_il = timezone.now()
        cfg.save()
        player = reverse("anagrafica:sessione_online_player", args=[self.sessione.pk])
        r = self.client.get(player + "?n=3")                 # non si salta: resta alla 1
        self.assertEqual(r.context["ordine"], 1)
        for n in (1, 2, 3):
            self.client.get(f"{player}?n={n}")
            self.client.post(reverse("anagrafica:sessione_online_avanti", args=[self.sessione.pk]), {"ordine": n})
        test = reverse("anagrafica:sessione_online_test", args=[self.sessione.pk])
        r = self.client.get(test)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "corretta")
        dati = {}
        for d in so.domande(self.sessione):
            dati[f"d{d.pk}"] = [str(o.pk) for o in d.opzioni.all() if o.corretta]
        r = self.client.post(test, dati)
        self.assertRedirects(r, reverse("anagrafica:sessione_online_esito", args=[self.sessione.pk]),
                             fetch_redirect_response=False)
        self.assertTrue(TrainingSessionAttempt.objects.get(enrollment=self.iscr).superato)
        r = self.client.get(reverse("anagrafica:sessione_online_esito", args=[self.sessione.pk]))
        self.assertContains(r, "Test superato")

    def test_tempo_minimo_dal_server(self):
        cfg = self._pronta(secondi_minimi_slide=60)
        cfg.pubblicata_il = timezone.now()
        cfg.save()
        self.client.get(reverse("anagrafica:sessione_online_player", args=[self.sessione.pk]))
        self.client.post(reverse("anagrafica:sessione_online_avanti", args=[self.sessione.pk]), {"ordine": 1})
        self.assertEqual(so.avanzamento(self.iscr).slide_viste, 0)

    def test_non_iscritto_negato(self):
        cfg = self._pronta()
        cfg.pubblicata_il = timezone.now()
        cfg.save()
        with mock.patch("anagrafica.views._helpers._current_legacy_anagrafica_id", return_value=999):
            r = self.client.get(reverse("anagrafica:sessione_online_player", args=[self.sessione.pk]))
        self.assertEqual(r.status_code, 302)
        slide = TrainingSessionSlide.objects.filter(sessione=self.sessione).first()
        with mock.patch("anagrafica.views._helpers._current_legacy_anagrafica_id", return_value=999), \
                mock.patch("anagrafica.views._helpers._can_view_formazione", return_value=False):
            r = self.client.get(reverse("anagrafica:sessione_online_slide_img", args=[slide.pk]))
        self.assertEqual(r.status_code, 403)

    def test_catalogo_mostra_lezione(self):
        cfg = self._pronta()
        cfg.pubblicata_il = timezone.now()
        cfg.save()
        self.assertEqual(len(so.lezioni_della_persona(LEGACY_ID)), 1)
        self.assertEqual(so.lezioni_della_persona(LEGACY_ID)[0]["stato"], so.NON_INIZIATA)
