"""Allegati di CORSO e loro copia opzionale sulla nuova edizione.

Il materiale caricato sul corso (dispense, programma, modulistica) e' la base che
ogni nuova edizione si ritrova proposta, pre-spuntata: si deseleziona cio' che non
serve e il resto viene **copiato**, non collegato.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import TrainingSessionForm
from .models_formazione import (
    TrainingAttachment,
    TrainingCourse,
    TrainingPlan,
    TrainingSession,
)
from .services.formazione_pianificazione import (
    allegati_proponibili,
    copia_allegati_dal_corso,
)

User = get_user_model()

PDF = b"%PDF-1.4 finto"


def _corso(codice="26001", note="") -> TrainingCourse:
    piano = TrainingPlan.objects.get_or_create(codice="SIC", defaults={"nome": "Sicurezza"})[0]
    return TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=f"Corso {codice}",
        durata_ore_teorica=8, note=note,
    )


def _allegato_corso(corso, nome="dispensa.pdf", proponi=True) -> TrainingAttachment:
    att = TrainingAttachment(
        corso=corso, tipo=TrainingAttachment.Tipo.MATERIALE,
        proponi_a_nuova_edizione=proponi, nome_originale=nome,
        tipo_mime="application/pdf", dimensione_bytes=len(PDF),
    )
    att.file = SimpleUploadedFile(nome, PDF, content_type="application/pdf")
    att.save()
    return att


class LivelliAllegatoTests(TestCase):
    def test_allegato_di_corso(self):
        att = _allegato_corso(_corso())
        self.assertEqual(att.livello, "corso")

    def test_allegato_di_edizione_e_di_lezione(self):
        corso = _corso()
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="26001-26E1",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 1),
        )
        att = TrainingAttachment(sessione=sess, nome_originale="registro.pdf")
        att.file = SimpleUploadedFile("registro.pdf", PDF)
        att.save()
        self.assertEqual(att.livello, "edizione")

    def test_allegato_orfano_rifiutato(self):
        # Ne' corso ne' edizione: sparirebbe da ogni elenco restando nello storage.
        att = TrainingAttachment(nome_originale="orfano.pdf")
        att.file = SimpleUploadedFile("orfano.pdf", PDF)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                att.save()

    def test_allegato_con_due_padroni_rifiutato(self):
        corso = _corso()
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="26001-26E1",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 1),
        )
        att = TrainingAttachment(corso=corso, sessione=sess, nome_originale="x.pdf")
        att.file = SimpleUploadedFile("x.pdf", PDF)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                att.save()


class CopiaAllegatiTests(TestCase):
    def setUp(self):
        self.corso = _corso()
        self.a1 = _allegato_corso(self.corso, "dispensa.pdf")
        self.a2 = _allegato_corso(self.corso, "programma.pdf")
        self.a3 = _allegato_corso(self.corso, "interno.pdf", proponi=False)
        self.sessione = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="26001-26E1",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 1),
        )

    def test_proponibili_esclude_i_non_proposti(self):
        nomi = {a.nome_originale for a in allegati_proponibili(self.corso)}
        self.assertEqual(nomi, {"dispensa.pdf", "programma.pdf"})

    def test_copia_solo_i_selezionati(self):
        n = copia_allegati_dal_corso(self.sessione, [self.a1])
        self.assertEqual(n, 1)
        copie = list(self.sessione.allegati.all())
        self.assertEqual(len(copie), 1)
        self.assertEqual(copie[0].nome_originale, "dispensa.pdf")
        self.assertEqual(copie[0].copiato_da_id, self.a1.pk)

    def test_la_copia_e_un_file_a_se(self):
        copia_allegati_dal_corso(self.sessione, [self.a1])
        copia = self.sessione.allegati.get()
        self.assertNotEqual(copia.file.name, self.a1.file.name)
        copia.file.open("rb")
        try:
            self.assertEqual(copia.file.read(), PDF)
        finally:
            copia.file.close()

    def test_non_ripropone_cio_che_e_gia_stato_copiato(self):
        copia_allegati_dal_corso(self.sessione, [self.a1])
        nomi = {a.nome_originale for a in allegati_proponibili(self.corso, self.sessione)}
        self.assertEqual(nomi, {"programma.pdf"})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FormNuovaEdizioneTests(TestCase):
    def setUp(self):
        self.corso = _corso(note="Portare i DPI.")
        self.att = _allegato_corso(self.corso)

    def test_materiale_prespuntato_in_creazione(self):
        form = TrainingSessionForm(initial={"corso": self.corso.pk})
        self.assertEqual(
            list(form.fields["allegati_dal_corso"].initial), [self.att.pk]
        )
        self.assertTrue(form.fields["copia_note_corso"].initial)

    def test_copia_allegati_dopo_il_salvataggio(self):
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": "2026-06-01",
            "allegati_dal_corso": [self.att.pk],
        })
        self.assertTrue(form.is_valid(), form.errors)
        sessione = form.save()
        self.assertEqual(form.copia_allegati(), 1)
        self.assertEqual(sessione.allegati.count(), 1)

    def test_note_del_corso_riportate_solo_se_richiesto(self):
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": "2026-06-01", "note": "Aula 2.",
            "copia_note_corso": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        sessione = form.save()
        self.assertIn("Aula 2.", sessione.note)
        self.assertIn("Portare i DPI.", sessione.note)

    def test_note_del_corso_non_riportate_di_default(self):
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": "2026-06-01", "note": "Aula 2.",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().note, "Aula 2.")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class UploadCorsoViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="all_corso", email="all_corso@x.local", password="x"
        )

    def setUp(self):
        self.corso = _corso()
        self.client.force_login(self.admin)

    def test_upload_sul_corso(self):
        r = self.client.post(
            reverse("anagrafica:formazione_corso_allegato_upload", args=[self.corso.pk]),
            {"file": SimpleUploadedFile("dispensa.pdf", PDF, content_type="application/pdf"),
             "tipo": "MATERIALE", "descrizione": "rev. B"},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        att = self.corso.allegati.get()
        self.assertEqual(att.nome_originale, "dispensa.pdf")
        self.assertTrue(att.proponi_a_nuova_edizione)

    def test_upload_negato_senza_permesso(self):
        self.client.logout()
        utente = User.objects.create_user(username="tizio", password="x")
        self.client.force_login(utente)
        self.client.post(
            reverse("anagrafica:formazione_corso_allegato_upload", args=[self.corso.pk]),
            {"file": SimpleUploadedFile("x.pdf", PDF, content_type="application/pdf")},
            follow=True,
        )
        self.assertEqual(self.corso.allegati.count(), 0)
