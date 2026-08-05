"""Formazione HR — editor in-app del programma didattico.

Il modello del programma esisteva già (corso → copia sull'edizione → copertura
per giornata) ma si compilava solo dall'area amministrativa. Qui si presidiano
gli endpoint che lo rendono usabile dal portale, e in particolare le due regole
che non devono cedere passando dalla UI:

- «Riprendi dal corso» **non cancella le integrazioni** dell'edizione;
- le giornate segnate su un argomento devono appartenere a **quell'edizione**:
  un id arrivato da fuori non deve passare.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingCourseArgomento,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
    TrainingSessionArgomento,
)
from .services.formazione_pianificazione import copia_programma_dal_corso

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class ProgrammaUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("prg_ui", "p@b.c", "pwd12345")
        self.client.force_login(self.user)
        self.corso = TrainingCourse.objects.create(
            piano=TrainingPlan.objects.create(codice="UI", nome="Piano UI"),
            codice="UI-01", titolo="Corso UI",
            durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
        )
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="UI-01-E1",
            data_inizio=date(2026, 5, 4), data_fine=date(2026, 5, 5),
        )
        self.lez1 = TrainingLesson.objects.create(
            sessione=self.sess, numero=1, data=date(2026, 5, 4),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="G1",
        )
        self.lez2 = TrainingLesson.objects.create(
            sessione=self.sess, numero=2, data=date(2026, 5, 5),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="G2",
        )

    # ── programma del corso ─────────────────────────────────────────────────

    def test_aggiunta_argomento_al_corso(self):
        self.client.post(
            reverse("anagrafica:formazione_corso_argomento_add", args=[self.corso.pk]),
            {"argomento": "Rischi specifici", "ore_previste": "4,5",
             "riferimento": "Allegato A, punto 3"},
        )
        voce = self.corso.programma.get()
        self.assertEqual(voce.argomento, "Rischi specifici")
        self.assertEqual(voce.ore_previste, Decimal("4.5"), "la virgola decimale va accettata")
        self.assertEqual(voce.riferimento, "Allegato A, punto 3")
        self.assertEqual(voce.ordine, 1)

    def test_ordine_progressivo_senza_doverlo_digitare(self):
        url = reverse("anagrafica:formazione_corso_argomento_add", args=[self.corso.pk])
        self.client.post(url, {"argomento": "Primo"})
        self.client.post(url, {"argomento": "Secondo"})
        self.assertEqual([v.ordine for v in self.corso.programma.all()], [1, 2])

    def test_argomento_vuoto_rifiutato(self):
        self.client.post(
            reverse("anagrafica:formazione_corso_argomento_add", args=[self.corso.pk]),
            {"argomento": "   "},
        )
        self.assertEqual(self.corso.programma.count(), 0)

    def test_ore_non_numeriche_non_rompono(self):
        self.client.post(
            reverse("anagrafica:formazione_corso_argomento_add", args=[self.corso.pk]),
            {"argomento": "Con ore strane", "ore_previste": "quattro"},
        )
        self.assertIsNone(self.corso.programma.get().ore_previste)

    def test_rimozione_dal_corso_non_tocca_le_edizioni(self):
        voce = TrainingCourseArgomento.objects.create(
            corso=self.corso, ordine=1, argomento="Da rimuovere",
        )
        copia_programma_dal_corso(self.sess)
        self.assertEqual(self.sess.programma.count(), 1)

        self.client.post(
            reverse("anagrafica:formazione_corso_argomento_delete", args=[self.corso.pk, voce.pk]),
        )

        self.assertEqual(self.corso.programma.count(), 0)
        self.assertEqual(self.sess.programma.count(), 1, "l'edizione documenta un fatto già accaduto")

    # ── programma dell'edizione ─────────────────────────────────────────────

    def test_integrazione_nasce_marcata_come_aggiunta(self):
        self.client.post(
            reverse("anagrafica:formazione_sessione_argomento_add", args=[self.sess.pk]),
            {"argomento": "Prova pratica"},
        )
        voce = self.sess.programma.get()
        self.assertTrue(voce.aggiunto, "serve a farla sopravvivere a una ricopiatura")

    def test_riprendi_dal_corso_conserva_le_integrazioni(self):
        TrainingCourseArgomento.objects.create(corso=self.corso, ordine=1, argomento="Dal corso")
        TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=9, argomento="Integrato in aula", aggiunto=True,
        )

        self.client.post(
            reverse("anagrafica:formazione_sessione_programma_riprendi", args=[self.sess.pk]),
        )

        argomenti = set(self.sess.programma.values_list("argomento", flat=True))
        self.assertEqual(argomenti, {"Dal corso", "Integrato in aula"})

    def test_rimozione_dall_edizione(self):
        voce = TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Sbagliato",
        )
        self.client.post(
            reverse("anagrafica:formazione_sessione_argomento_delete", args=[self.sess.pk, voce.pk]),
        )
        self.assertEqual(self.sess.programma.count(), 0)

    # ── copertura giornata ↔ argomento ──────────────────────────────────────

    def test_segnare_le_giornate_svolte(self):
        voce = TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Teoria",
        )
        self.client.post(
            reverse("anagrafica:formazione_sessione_argomento_giornate", args=[self.sess.pk, voce.pk]),
            {"lezioni": [str(self.lez1.pk)]},
        )
        self.assertEqual([lz.pk for lz in voce.lezioni.all()], [self.lez1.pk])

    def test_deselezionare_tutto_azzera_la_copertura(self):
        voce = TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Teoria",
        )
        voce.lezioni.set([self.lez1, self.lez2])
        self.client.post(
            reverse("anagrafica:formazione_sessione_argomento_giornate", args=[self.sess.pk, voce.pk]),
            {},
        )
        self.assertEqual(voce.lezioni.count(), 0)

    def test_giornata_di_un_altra_edizione_ignorata(self):
        """Un id arrivato da fuori non deve legare argomenti a giornate altrui."""
        altra = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="UI-01-E2",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 1),
        )
        estranea = TrainingLesson.objects.create(
            sessione=altra, numero=1, data=date(2026, 6, 1),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="Altrove",
        )
        voce = TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Teoria",
        )

        self.client.post(
            reverse("anagrafica:formazione_sessione_argomento_giornate", args=[self.sess.pk, voce.pk]),
            {"lezioni": [str(self.lez1.pk), str(estranea.pk)]},
        )

        self.assertEqual([lz.pk for lz in voce.lezioni.all()], [self.lez1.pk])

    # ── permessi ────────────────────────────────────────────────────────────

    def test_non_editor_non_modifica_il_programma(self):
        self.client.force_login(User.objects.create_user("nessuno", "n@b.c", "pwd12345"))
        self.client.post(
            reverse("anagrafica:formazione_corso_argomento_add", args=[self.corso.pk]),
            {"argomento": "Non deve entrare"},
        )
        self.assertEqual(self.corso.programma.count(), 0)

    # ── resa in pagina ──────────────────────────────────────────────────────

    def test_scheda_sessione_mostra_il_programma_e_i_non_svolti(self):
        voce = TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Argomento scoperto",
        )
        r = self.client.get(
            reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk]),
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Programma dell'edizione")
        self.assertContains(r, "Argomento scoperto")
        self.assertEqual(r.context["programma_scoperti"], 1)
        self.assertEqual(len(r.context["programma"][0].scelte_giornate), 2)
        voce.lezioni.add(self.lez1)
        r2 = self.client.get(
            reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk]),
        )
        self.assertEqual(r2.context["programma_scoperti"], 0)

    def test_scheda_corso_mostra_il_programma(self):
        TrainingCourseArgomento.objects.create(
            corso=self.corso, ordine=1, argomento="Voce del corso",
        )
        r = self.client.get(
            reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]),
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Voce del corso")
        self.assertEqual(len(r.context["programma"]), 1)
