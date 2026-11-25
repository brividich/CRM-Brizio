"""Revisione e-learning: video a pezzi e compressione (D), percorso a moduli e video fino in fondo (B)."""
from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_elearning import TrainingElearningModulo
from .models_formazione import TrainingCourse, TrainingPlan, TrainingSlide
from .services import elearning_fruizione as fr
from .services import elearning_video as ev

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00\x00\x00\x08free" + b"\x00" * 200


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.str", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PS", nome="Piano")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="ES1", titolo="Corso", durata_ore_teorica=Decimal("1"),
                                                   is_elearning=True, stato="ATTIVO")


class VideoPezziTests(_Base):
    def test_caricamento_a_pezzi_crea_la_slide(self):
        url = reverse("anagrafica:formazione_video_pezzo", args=[self.corso.pk])
        with mock.patch.object(ev, "accoda_compressione") as accoda, self.settings(ANAGRAFICA_PRIVATE_ROOT=self._tmp()):
            r = self.client.post(url, {"upload_id": "a" * 32, "indice": 0, "totale": 1, "nome": "v.mp4",
                                       "titolo": "Benvenuto", "fino_in_fondo": "1",
                                       "pezzo": SimpleUploadedFile("pezzo", MP4)})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["fatto"])
        s = TrainingSlide.objects.get(corso=self.corso)
        self.assertEqual((s.tipo, s.titolo, s.video_fino_in_fondo), ("VIDEO", "Benvenuto", True))
        accoda.assert_called_once()

    def test_file_non_video_rifiutato(self):
        url = reverse("anagrafica:formazione_video_pezzo", args=[self.corso.pk])
        with self.settings(ANAGRAFICA_PRIVATE_ROOT=self._tmp()):
            r = self.client.post(url, {"upload_id": "b" * 32, "indice": 0, "totale": 1, "nome": "v.mp4",
                                       "pezzo": SimpleUploadedFile("pezzo", b"<html>no</html>")})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(TrainingSlide.objects.exists())

    def test_pezzo_fuori_ordine_e_id_non_valido(self):
        with self.settings(ANAGRAFICA_PRIVATE_ROOT=self._tmp()):
            with self.assertRaises(ev.VideoError):
                ev.aggiungi_pezzo(1, "c" * 32, 3, SimpleUploadedFile("p", b"x"), 10 ** 9)
            with self.assertRaises(ev.VideoError):
                ev.percorso_parziale(1, "../../etc")

    def test_compressione_senza_ffmpeg_non_rompe(self):
        s = TrainingSlide(corso=self.corso, ordine=1, titolo="V", tipo="VIDEO")
        with self.settings(ANAGRAFICA_PRIVATE_ROOT=self._tmp()):
            s.video.save("v.mp4", SimpleUploadedFile("v.mp4", MP4), save=True)
            with mock.patch.object(ev, "ffmpeg", return_value=None):
                self.assertEqual(ev.comprimi_slide(s.pk)["esito"], "ffmpeg_assente")

    def _tmp(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="pn_video_")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class PercorsoModuliTests(_Base):
    def test_modulo_fuori_percorso_non_serve_per_il_quiz(self):
        m1 = TrainingElearningModulo.objects.create(corso=self.corso, ordine=1, titolo="Obbligatorio")
        m2 = TrainingElearningModulo.objects.create(corso=self.corso, ordine=2, titolo="Approfondimento", obbligatorio=False)
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="A", contenuto="a", modulo=m1)
        TrainingSlide.objects.create(corso=self.corso, ordine=2, titolo="B", contenuto="b", modulo=m2)
        TrainingSlide.objects.create(corso=self.corso, ordine=3, titolo="C", contenuto="c")
        self.assertEqual(fr.ordini_slide(self.corso), [1, 3])

    def test_video_fino_in_fondo(self):
        s = TrainingSlide(corso=self.corso, ordine=1, titolo="V", tipo="VIDEO", video_fino_in_fondo=True, video_durata_secondi=100)
        self.assertEqual(fr.video_mancante(s, 50), 40)
        self.assertEqual(fr.video_mancante(s, 95), 0)
        s.video_fino_in_fondo = False
        self.assertEqual(fr.video_mancante(s, 0), 0)

    def test_biblioteca_con_login(self):
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="ciao")
        r = self.client.get(reverse("anagrafica:formazione_online_materiale", args=[self.corso.pk]))
        self.assertContains(r, "Materiale del corso")
        s = TrainingSlide.objects.get()
        self.assertContains(self.client.get(reverse("anagrafica:formazione_online_materiale", args=[self.corso.pk]) + f"?s={s.pk}"), "ciao")
