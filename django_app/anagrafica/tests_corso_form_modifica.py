"""Scheda corso: «Modifica corso» apre la pagina a tappe (non più la modale),
la regola di obbligo ha un solo destinatario scelto con «Si applica a» e la
persona si sceglie per nome; le tendine lunghe sono ricercabili (Tom Select)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule

User = get_user_model()


class CorsoFormModificaTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-corso", "su-corso@test.local", "x")
        self.client.force_login(self.su)
        piano = TrainingPlan.objects.create(codice="P-CFM", nome="Piano test form corso")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="C-CFM", titolo="Corso form modifica", durata_ore_teorica=4, is_active=True,
        )

    def test_scheda_corso_senza_modale_con_link_modifica(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        body = resp.content.decode()
        self.assertNotIn('id="modal-edit-corso"', body)
        self.assertIn(reverse("anagrafica:formazione_corso_edit", args=[self.corso.pk]), body)
        # Regola con un solo destinatario e persona per nome.
        self.assertIn('name="rr_target"', body)
        self.assertIn("A chi serve questo corso", body)
        self.assertIn("— Scegli la persona —", body)

    def test_modifica_in_get_rende_la_pagina_a_tappe(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_edit", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Modifica corso", body)
        self.assertIn('value="Corso form modifica"', body)
        self.assertIn("Salva modifiche", body)
        # «Annulla» torna alla scheda del corso.
        self.assertIn(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]), body)

    def test_modifica_post_non_valida_resta_in_pagina(self):
        resp = self.client.post(
            reverse("anagrafica:formazione_corso_edit", args=[self.corso.pk]),
            {"piano": self.corso.piano_id, "titolo": "", "durata_ore_teorica": "4", "stato": "ATTIVO"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("fmd-ferr", resp.content.decode())
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.titolo, "Corso form modifica")

    def test_modifica_post_valida_salva_e_torna_alla_scheda(self):
        resp = self.client.post(
            reverse("anagrafica:formazione_corso_edit", args=[self.corso.pk]),
            {"piano": self.corso.piano_id, "titolo": "Titolo nuovo", "durata_ore_teorica": "6",
             "stato": "ATTIVO", "is_active": "on", "validita_mesi": "0", "quiz_punteggio_minimo": "0"},
        )
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors.as_text())
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.titolo, "Titolo nuovo")

    def test_regola_per_persona_scelta_per_nome(self):
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) VALUES (%s,%s,%s,%s,%s)",
                ["p.regola", "Pia", "Regola", "UT", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["p.regola"])
            lid = int(cur.fetchone()[0])
        resp = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertIn(f'<option value="{lid}">', resp.content.decode())
        resp = self.client.post(
            reverse("anagrafica:formazione_corso_req_rule_add", args=[self.corso.pk]),
            {"legacy_anagrafica_id": str(lid), "is_mandatory": "on", "is_active": "on", "priority": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        regola = TrainingRequirementRule.objects.get(corso=self.corso)
        self.assertEqual(regola.legacy_anagrafica_id, lid)


class TendineRicercabiliTests(TestCase):
    def test_init_automatico_delle_tendine_lunghe(self):
        from django.contrib.staticfiles import finders
        path = finders.find("core/js/tomselect-init.js")
        src = open(path, encoding="utf-8").read()
        self.assertIn("AUTO_MIN = 10", src)
        self.assertIn("data-no-search", src)
        self.assertIn('select:not(.js-searchable)', src)


class VersioniAutomaticheTests(TestCase):
    """Le versioni del corso d'aula nascono da sole (services/corso_versioni.py)."""

    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.su = User.objects.create_superuser("su-ver", "su-ver@test.local", "x")
        self.client.force_login(self.su)
        self.piano = TrainingPlan.objects.create(codice="P-VER", nome="Piano versioni")

    def _post_modifica(self, corso, **campi):
        dati = {"piano": corso.piano_id, "titolo": corso.titolo, "durata_ore_teorica": str(corso.durata_ore_teorica),
                "stato": "ATTIVO", "is_active": "on", "validita_mesi": str(corso.validita_mesi or 0),
                "quiz_punteggio_minimo": "0"}
        dati.update(campi)
        return self.client.post(reverse("anagrafica:formazione_corso_edit", args=[corso.pk]), dati)

    def _corso(self):
        from .services.corso_versioni import registra
        corso = TrainingCourse.objects.create(piano=self.piano, codice="C-VER", titolo="Corso versioni",
                                              durata_ore_teorica=8, validita_mesi=60, is_active=True)
        registra(corso, user=self.su)
        return corso

    def test_prima_versione_alla_creazione(self):
        corso = self._corso()
        self.assertEqual(list(corso.versioni.values_list("version_label", flat=True)), ["1.0"])

    def test_modifica_senza_completamenti_aggiorna_la_versione_corrente(self):
        corso = self._corso()
        self._post_modifica(corso, durata_ore_teorica="12")
        corso.refresh_from_db()
        self.assertEqual(corso.versione, "1.0")
        v = corso.versioni.get()
        self.assertEqual(str(v.durata_ore_snapshot), "12.00")
        self.assertIn("Durata 8.00 → 12.00 h", v.note)

    def test_modifica_dopo_completamento_apre_nuova_versione(self):
        from .models_formazione import TrainingEmployeeRecord
        corso = self._corso()
        TrainingEmployeeRecord.objects.create(
            corso=corso, legacy_anagrafica_id=7, course_version_snapshot="1.0",
            data_completamento=timezone.localdate(),
        )
        resp = self._post_modifica(corso, validita_mesi="36")
        self.assertEqual(resp.status_code, 302)
        corso.refresh_from_db()
        self.assertEqual(corso.versione, "1.1")
        vecchia = corso.versioni.get(version_label="1.0")
        nuova = corso.versioni.get(version_label="1.1")
        self.assertIsNotNone(vecchia.data_fine_validita)
        self.assertIn("Validità 60 → 36 mesi", nuova.note)

    def test_salvataggio_senza_cambi_non_crea_versioni(self):
        corso = self._corso()
        self._post_modifica(corso)
        self.assertEqual(corso.versioni.count(), 1)

    def test_programma_cambiato_aggiorna_la_versione(self):
        corso = self._corso()
        self.client.post(reverse("anagrafica:formazione_corso_argomento_add", args=[corso.pk]),
                         {"argomento": "Rischi specifici", "ore_previste": "2"})
        v = corso.versioni.get()
        self.assertEqual(len(v.contenuti_json["programma"]), 1)
        self.assertIn("Programma didattico (0 → 1 argomenti)", v.note)

    def test_scheda_senza_form_manuale_e_a_schede(self):
        corso = self._corso()
        body = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[corso.pk])).content.decode()
        self.assertNotIn('name="version_label"', body)
        self.assertIn("Automatiche", body)
        for scheda in ("panoramica", "persone", "contenuti", "superamento"):
            self.assertIn(f'data-corso-panel="{scheda}"', body)

    def test_elearning_escluso(self):
        from .services.corso_versioni import registra
        corso = TrainingCourse.objects.create(piano=self.piano, codice="C-VEL", titolo="Online",
                                              durata_ore_teorica=1, is_active=True, is_elearning=True)
        registra(corso, user=self.su)
        self.assertEqual(corso.versioni.count(), 0)
