"""Test mirati per i micro-corsi e-learning (slide + quiz).

Coprono: renderer Markdown sicuro, integrità modelli, endpoint autore (slide/quiz)
via client con superuser (che supera `_can_edit_formazione`). Il flusso discente HTTP
dipende dalle tabelle legacy (anagrafica_dipendenti, unmanaged) non presenti nel DB di
test, quindi qui si verifica la logica di punteggio a livello di modello/servizio.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingElearningEnrollment,
    TrainingPlan,
    TrainingQuizOption,
    TrainingQuizQuestion,
    TrainingSlide,
)
from .services.elearning_markdown import render_markdown


class MarkdownRendererTests(TestCase):
    def test_escape_first_blocca_xss(self):
        html = render_markdown("<script>alert(1)</script>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_sottoinsieme_markdown(self):
        html = render_markdown("# Tit\n\n**b** *i* `c`\n\n- a\n- b\n\n[x](https://e.it)")
        self.assertIn("<h2>Tit</h2>", html)
        self.assertIn("<strong>b</strong>", html)
        self.assertIn("<em>i</em>", html)
        self.assertIn("<code>c</code>", html)
        self.assertIn("<ul><li>a</li><li>b</li></ul>", html)
        self.assertIn('<a href="https://e.it"', html)

    def test_link_schema_non_sicuro_ignorato(self):
        # javascript: non matcha il pattern http/https/mailto -> resta testo escapato
        html = render_markdown("[x](javascript:alert(1))")
        self.assertNotIn("<a ", html)


class ElearningModelTests(TestCase):
    def setUp(self):
        self.piano = TrainingPlan.objects.create(codice="PE", nome="Piano E-learning")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="EL01", titolo="Sicurezza base",
            durata_ore_teorica=Decimal("1.0"), is_elearning=True, quiz_punteggio_minimo=70,
            stato="ATTIVO",
        )

    def test_relazioni_slide_e_quiz(self):
        s = TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="# Ciao")
        q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="2+2?")
        TrainingQuizOption.objects.create(domanda=q, ordine=1, testo="4", corretta=True)
        TrainingQuizOption.objects.create(domanda=q, ordine=2, testo="5", corretta=False)
        self.assertEqual(self.corso.slides.count(), 1)
        self.assertEqual(self.corso.quiz_domande.count(), 1)
        self.assertEqual(q.opzioni.filter(corretta=True).count(), 1)
        self.assertIn("EL01", str(s))


class ElearningAuthoringEndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("autore", "a@e.it", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PE", nome="Piano E-learning")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="EL01", titolo="Corso", durata_ore_teorica=Decimal("1.0"),
            is_elearning=True, stato="ATTIVO",
        )

    def test_crea_slide(self):
        url = reverse("anagrafica:formazione_slide_save", args=[self.corso.pk])
        resp = self.client.post(url, {"titolo": "Slide 1", "ordine": 1, "contenuto": "# x", "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.corso.slides.count(), 1)

    def test_crea_domanda_e_opzione(self):
        q_url = reverse("anagrafica:formazione_question_save", args=[self.corso.pk])
        self.client.post(q_url, {"testo": "Domanda?", "ordine": 1, "is_active": "on"})
        q = self.corso.quiz_domande.first()
        self.assertIsNotNone(q)
        o_url = reverse("anagrafica:formazione_option_save", args=[self.corso.pk, q.pk])
        self.client.post(o_url, {"testo": "Giusta", "ordine": 1, "corretta": "on"})
        self.assertEqual(q.opzioni.filter(corretta=True).count(), 1)

    def test_pagina_autore_render(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_elearning", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_hub_gestione_render(self):
        resp = self.client.get(reverse("anagrafica:formazione_elearning_hub"))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.context["tot"]["corsi"], 1)
        # Il corso del setup non ha slide -> salute CRIT (Senza slide)
        salute_codes = [r["salute"][0] for r in resp.context["rows"]]
        self.assertIn("CRIT", salute_codes)

    def test_create_preset_elearning(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_create") + "?elearning=1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].initial.get("is_elearning"))


def _pdf_due_pagine() -> bytes:
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 700, "Slide 1 - test")
    c.showPage()
    c.drawString(100, 700, "Slide 2 - test")
    c.showPage()
    c.save()
    return buf.getvalue()


class ElearningImportTests(TestCase):
    """Import da PDF (PyMuPDF, niente LibreOffice): una slide-immagine per pagina."""

    def setUp(self):
        self.piano = TrainingPlan.objects.create(codice="PE", nome="Piano")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="ELPDF", titolo="Corso PDF", durata_ore_teorica=Decimal("1.0"),
            is_elearning=True, stato="ATTIVO",
        )

    def test_import_pdf_crea_slide_immagine(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services.elearning_import import importa_slides_da_file
        f = SimpleUploadedFile("lezione.pdf", _pdf_due_pagine(), content_type="application/pdf")
        n = importa_slides_da_file(self.corso, f, user=None)
        self.assertEqual(n, 2)
        slides = list(self.corso.slides.order_by("ordine"))
        self.assertEqual(len(slides), 2)
        self.assertTrue(all(s.is_immagine for s in slides))

    def test_estensione_non_valida(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services.elearning_import import importa_slides_da_file, ImportError_
        f = SimpleUploadedFile("note.txt", b"ciao", content_type="text/plain")
        with self.assertRaises(ImportError_):
            importa_slides_da_file(self.corso, f, user=None)

    def test_delete_slide_rimuove_file(self):
        """Eliminando una slide-immagine il file viene rimosso dallo storage (no orfani)."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services.elearning_import import importa_slides_da_file
        f = SimpleUploadedFile("l.pdf", _pdf_due_pagine(), content_type="application/pdf")
        importa_slides_da_file(self.corso, f, user=None)
        slide = self.corso.slides.first()
        name = slide.immagine.name
        storage = slide.immagine.storage
        self.assertTrue(storage.exists(name))
        slide.delete()
        self.assertFalse(storage.exists(name))

    def test_serve_immagine_slide(self):
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .services.elearning_import import importa_slides_da_file
        f = SimpleUploadedFile("l.pdf", _pdf_due_pagine(), content_type="application/pdf")
        importa_slides_da_file(self.corso, f, user=None)
        slide = self.corso.slides.first()
        User = get_user_model()
        u = User.objects.create_user("disc", "d@e.it", "pwd12345")
        # Onboarding completato: evita il redirect del middleware (in prod i dipendenti l'hanno fatto)
        from django.utils import timezone as _tz
        from core.models import UserOnboarding
        UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True, "completed_at": _tz.now()})
        self.client.force_login(u)
        # Corso pubblicato e-learning -> qualsiasi utente autenticato puo' caricare l'immagine
        resp = self.client.get(reverse("anagrafica:formazione_slide_image", args=[slide.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")


class ElearningQuizValidationTests(TestCase):
    """Domande senza opzione corretta: escluse dal quiz discente + segnalate all'autore."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("autore2", "a2@e.it", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PV", nome="Piano")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="ELVAL", titolo="Corso", durata_ore_teorica=Decimal("1.0"),
            is_elearning=True, stato="ATTIVO",
        )
        # Domanda valida (1 opzione corretta)
        self.q_ok = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="Domanda valida", is_active=True)
        TrainingQuizOption.objects.create(domanda=self.q_ok, ordine=1, testo="Giusta", corretta=True)
        TrainingQuizOption.objects.create(domanda=self.q_ok, ordine=2, testo="Sbagliata", corretta=False)
        # Domanda invalida (nessuna opzione corretta)
        self.q_ko = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=2, testo="DomandaSenzaCorretta", is_active=True)
        TrainingQuizOption.objects.create(domanda=self.q_ko, ordine=1, testo="A", corretta=False)

    def test_quiz_get_esclude_domande_invalide(self):
        resp = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["domande"]), 1)
        self.assertNotContains(resp, "DomandaSenzaCorretta")

    def test_quiz_tutte_invalide_redirige(self):
        self.q_ok.delete()  # resta solo la invalida
        resp = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_autore_segnala_domanda_incompleta(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_elearning", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["n_domande_incomplete"], 1)


class ElearningManageTests(TestCase):
    """Cabina di regia: render, pubblica/ritira con controllo qualità, export CSV."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("autore3", "a3@e.it", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PM", nome="Piano")
        # Corso "pronto": slide + quiz valido, parte come BOZZA
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="ELMAN", titolo="Corso gestito", durata_ore_teorica=Decimal("1.0"),
            is_elearning=True, stato="BOZZA", is_active=True,
        )
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="S1", contenuto="x", is_active=True)
        q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="Q?", is_active=True)
        TrainingQuizOption.objects.create(domanda=q, ordine=1, testo="ok", corretta=True)
        TrainingElearningEnrollment.objects.create(
            corso=self.corso, legacy_anagrafica_id=999, stato="COMPLETATO",
            best_punteggio_pct=Decimal("90.00"), n_tentativi=1, n_slide_totali=1,
        )

    def test_manage_render_con_iscritti(self):
        resp = self.client.get(reverse("anagrafica:formazione_elearning_manage", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["counts"]["iscritti"], 1)
        self.assertEqual(resp.context["counts"]["completati"], 1)

    def test_pubblica_ok(self):
        resp = self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 302)
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "ATTIVO")

    def test_ritira(self):
        self.corso.stato = "ATTIVO"
        self.corso.save(update_fields=["stato"])
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "BOZZA")

    def test_pubblica_bloccata_senza_slide(self):
        self.corso.slides.all().delete()
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "BOZZA")  # non pubblicato

    def test_csv_export(self):
        resp = self.client.get(reverse("anagrafica:formazione_elearning_iscritti_csv", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        body = resp.content.decode("utf-8")
        self.assertIn("Dipendente", body)
