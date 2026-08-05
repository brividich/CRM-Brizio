"""Formazione HR — catena dell'evidenza: origine dell'obbligo e registro audit.

Due anelli della catena che un auditor percorre dal piano fino alla firma:

- **da dove nasce il corso** (`fonte_obbligo` + riferimento + articolo). Prima
  il riferimento viveva dentro il titolo come testo libero ("Rif. 9070Q"), e la
  domanda «mostrami tutti i corsi che discendono dall'Accordo Stato-Regioni»
  non aveva risposta. I campi sono deliberatamente **non bloccanti**: i corsi
  storici restano validi senza compilarli, altrimenti la migrazione sarebbe
  stata impossibile su un catalogo già popolato.
- **chi ha toccato cosa**: cancellazioni e ritocchi a una presenza già firmata
  finiscono in `core.AuditLog`. Le registrazioni ordinarie no, altrimenti il
  registro diventa illeggibile e quindi inutile.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from .forms import TrainingCourseForm
from .models_formazione import (
    TrainingCourse,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)

User = get_user_model()

MODULO = "anagrafica.formazione"


def _piano(codice="CAT") -> TrainingPlan:
    return TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}")


def _corso(piano, codice="CAT-01", **extra) -> TrainingCourse:
    campi = {
        "piano": piano,
        "codice": codice,
        "titolo": f"Corso {codice}",
        "durata_ore_teorica": Decimal("8.00"),
        "stato": "ATTIVO",
    }
    campi.update(extra)
    return TrainingCourse.objects.create(**campi)


# ---------------------------------------------------------------------------
# Anello 1 — origine dell'obbligo
# ---------------------------------------------------------------------------

class FonteObbligoModelTests(TestCase):
    def test_corso_resta_valido_senza_fonte(self):
        """Non bloccante: i 488 corsi storici non hanno la fonte e devono restare validi."""
        corso = _corso(_piano("SEN"))
        corso.full_clean()  # non deve sollevare
        self.assertEqual(corso.fonte_obbligo, "")
        self.assertEqual(corso.riferimento_fonte, "")
        self.assertEqual(corso.articolo_fonte, "")

    def test_fonte_valorizzata_e_interrogabile(self):
        piano = _piano("ASR")
        _corso(piano, "ASR-01", fonte_obbligo="ACCORDO",
               riferimento_fonte="Accordo Stato-Regioni 21/12/2011", articolo_fonte="art. 37 c. 2")
        _corso(piano, "ASR-02", fonte_obbligo="ACCORDO",
               riferimento_fonte="Accordo Stato-Regioni 21/12/2011")
        _corso(piano, "CLI-01", fonte_obbligo="CLIENTE", riferimento_fonte="Avio 9070Q")
        _corso(piano, "LIB-01")

        # È questa la domanda che prima non aveva risposta.
        self.assertEqual(TrainingCourse.objects.filter(fonte_obbligo="ACCORDO").count(), 2)
        self.assertEqual(TrainingCourse.objects.filter(fonte_obbligo="CLIENTE").count(), 1)
        self.assertEqual(TrainingCourse.objects.exclude(fonte_obbligo="").count(), 3)

    def test_fonte_fuori_catalogo_rifiutata(self):
        corso = _corso(_piano("BAD"), fonte_obbligo="QUALCOSA")
        with self.assertRaises(Exception):
            corso.full_clean()


class FonteObbligoFormTests(TestCase):
    def _dati(self, **extra):
        piano = TrainingPlan.objects.get_or_create(codice="FRM", defaults={"nome": "Piano FRM"})[0]
        dati = {
            "piano": piano.pk,
            "codice": "FRM-01",
            "titolo": "Corso dal form",
            "durata_ore_teorica": "8.00",
            "validita_mesi": "0",
            "quiz_punteggio_minimo": "70",
            "stato": "ATTIVO",
            "versione": "1.0",
            "is_active": "on",
        }
        dati.update(extra)
        return dati

    def test_form_valido_senza_fonte(self):
        form = TrainingCourseForm(data=self._dati())
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data["fonte_obbligo"], "")

    def test_form_salva_la_fonte(self):
        form = TrainingCourseForm(data=self._dati(
            fonte_obbligo="LEGGE",
            riferimento_fonte="D.Lgs 81/08",
            articolo_fonte="art. 37",
        ))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        corso = form.save()
        self.assertEqual(corso.fonte_obbligo, "LEGGE")
        self.assertEqual(corso.riferimento_fonte, "D.Lgs 81/08")

    def test_opzione_vuota_esposta_nel_menu(self):
        form = TrainingCourseForm()
        valori = [v for v, _ in form.fields["fonte_obbligo"].widget.choices]
        self.assertIn("", valori)
        self.assertIn("ACCORDO", valori)


# ---------------------------------------------------------------------------
# Anello 10 — registro delle modifiche
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False)
class AuditFormazioneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("audit_form", "a@b.c", "pwd12345")
        self.client.force_login(self.user)
        self.corso = _corso(_piano("AUD"), "AUD-01")
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="AUD-01-E1",
            data_inizio=date(2026, 9, 3), data_fine=date(2026, 9, 3),
        )
        self.lez = TrainingLesson.objects.create(
            sessione=self.sess, numero=1, data=date(2026, 9, 3),
            ora_inizio=time(8, 0), ora_fine=time(17, 0),
        )

    def _voci(self, azione: str):
        return AuditLog.objects.filter(modulo=MODULO, azione=azione)

    def test_prima_registrazione_non_sporca_il_registro(self):
        """Le presenze ordinarie sono migliaia: se finissero tutte in audit,
        il registro non servirebbe più a nessuno."""
        self.client.post(
            reverse("anagrafica:formazione_presenza_set",
                    args=[self.sess.pk, self.lez.pk]),
            {"legacy_anagrafica_id": "4242", "stato_presenza": "PRESENTE"},
        )
        self.assertEqual(TrainingLessonAttendance.objects.count(), 1)
        self.assertFalse(self._voci("presenza_modificata").exists())

    def test_cambio_di_stato_su_presenza_esistente_tracciato(self):
        TrainingLessonAttendance.objects.create(
            lezione=self.lez, legacy_anagrafica_id=4242, stato_presenza="PRESENTE",
        )
        self.client.post(
            reverse("anagrafica:formazione_presenza_set",
                    args=[self.sess.pk, self.lez.pk]),
            {"legacy_anagrafica_id": "4242", "stato_presenza": "ASSENTE_INGIUST"},
        )
        voce = self._voci("presenza_modificata").first()
        self.assertIsNotNone(voce, "il ritocco di una presenza esistente va tracciato")
        self.assertEqual(voce.dettaglio.get("stato_precedente"), "PRESENTE")
        self.assertEqual(voce.dettaglio.get("stato_nuovo"), "ASSENTE_INGIUST")
        self.assertEqual(voce.dettaglio.get("legacy_anagrafica_id"), 4242)

    def test_ritocco_dopo_la_firma_tracciato_anche_a_stato_invariato(self):
        """È il caso peggiore in verifica ispettiva: qualcuno tocca una riga
        già firmata. Va tracciato anche se lo stato non cambia."""
        TrainingLessonAttendance.objects.create(
            lezione=self.lez, legacy_anagrafica_id=99, stato_presenza="PRESENTE",
            signature_status="FIRMATO",
        )
        self.client.post(
            reverse("anagrafica:formazione_presenza_set",
                    args=[self.sess.pk, self.lez.pk]),
            {"legacy_anagrafica_id": "99", "stato_presenza": "PRESENTE",
             "signature_status": "FIRMATO"},
        )
        voce = self._voci("presenza_modificata").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.dettaglio.get("firma_precedente"), "FIRMATO")

    def test_eliminazione_lezione_tracciata_con_le_presenze_travolte(self):
        TrainingLessonAttendance.objects.create(
            lezione=self.lez, legacy_anagrafica_id=7, stato_presenza="PRESENTE",
        )
        self.client.post(
            reverse("anagrafica:formazione_lezione_delete",
                    args=[self.sess.pk, self.lez.pk]),
        )
        self.assertFalse(TrainingLesson.objects.filter(pk=self.lez.pk).exists())
        voce = self._voci("lezione_eliminata").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.dettaglio.get("presenze_eliminate"), 1)
        self.assertEqual(voce.dettaglio.get("numero"), 1)

    def test_eliminazione_sessione_tracciata(self):
        self.client.post(
            reverse("anagrafica:formazione_sessione_delete", args=[self.sess.pk]),
        )
        self.assertFalse(TrainingSession.objects.filter(pk=self.sess.pk).exists())
        voce = self._voci("sessione_eliminata").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.dettaglio.get("codice_sessione"), "AUD-01-E1")
        self.assertEqual(voce.dettaglio.get("lezioni_eliminate"), 1)

    def test_eliminazione_corso_tracciata(self):
        vuoto = _corso(self.corso.piano, "AUD-02")
        self.client.post(
            reverse("anagrafica:formazione_corso_delete", args=[vuoto.pk]),
        )
        self.assertFalse(TrainingCourse.objects.filter(pk=vuoto.pk).exists())
        voce = self._voci("corso_eliminato").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.dettaglio.get("codice"), "AUD-02")

    def test_la_voce_di_audit_dice_chi(self):
        self.client.post(
            reverse("anagrafica:formazione_sessione_delete", args=[self.sess.pk]),
        )
        voce = self._voci("sessione_eliminata").first()
        self.assertIsNotNone(voce)
        self.assertTrue(voce.utente_display, "senza il nome dell'operatore l'audit non serve")
