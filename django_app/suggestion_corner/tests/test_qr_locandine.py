"""Form pubblico da QR (Anonimo / Mi identifico, foto) e locandine QR per le bacheche."""
from __future__ import annotations

import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Reparto
from core.models import UserOnboarding
from suggestion_corner.models import (
    SuggestionCorner, SuggestionCornerAllegato, SuggestionCornerConfig, SuggestionCornerLocandina,
)

User = get_user_model()


def _onboard(user):
    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())


def _jpeg_con_gps() -> bytes:
    """JPEG sintetico con EXIF (GPS + modello telefono) da far sparire."""
    from PIL import Image

    img = Image.new("RGB", (64, 48), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0110] = "TelefonoProva X"  # Model
    exif[0x8825] = {1: "N", 2: (45.0, 30.0, 0.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


class _MediaTemporanei(TestCase):
    def setUp(self):
        super().setUp()
        self._dir = tempfile.mkdtemp(prefix="sc-test-")
        self._override = override_settings(PRIVATE_ATTACHMENTS_ROOT=self._dir, MEDIA_ROOT=self._dir)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._dir, ignore_errors=True)
        super().tearDown()


@override_settings(LEGACY_AUTH_ENABLED=False)
class FormPubblicoIdentitaFotoTest(_MediaTemporanei):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.url = reverse("suggestion_corner:nuova")

    def _post(self, **extra):
        dati = {"reparto_provenienza": self.reparto.pk, "opportunity": "Idea di prova."}
        dati.update(extra)
        return self.client.post(self.url, dati)

    def test_get_mostra_due_scelte_e_campo_foto(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="anonimo"', html)
        self.assertIn('value="identificato"', html)
        self.assertIn('name="segnalante_nome"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('name="foto"', html)

    def test_senza_scelta_non_crea(self):
        resp = self._post()
        self.assertContains(resp, "Scegli «Anonimo» oppure «Mi identifico».")
        self.assertFalse(SuggestionCorner.objects.exists())

    def test_identificato_senza_nome_non_crea(self):
        resp = self._post(modo="identificato", segnalante_nome="  ")
        self.assertContains(resp, "Scrivi nome e cognome")
        self.assertFalse(SuggestionCorner.objects.exists())

    def test_con_login_identificato_usa_account(self):
        u = User.objects.create_user(username="op", password="x", first_name="Ada", last_name="Prova")
        _onboard(u)
        self.client.force_login(u)
        self.assertContains(self.client.get(self.url), "Invierai come")
        self._post(modo="identificato")
        seg = SuggestionCorner.objects.get()
        self.assertEqual(seg.created_by, u)
        self.assertFalse(seg.anonima)
        self.assertEqual(seg.segnalante_display.lower(), "ada prova")

    def test_con_login_anonimo_non_lega_account(self):
        u = User.objects.create_user(username="op2", password="x")
        _onboard(u)
        self.client.force_login(u)
        self._post(modo="anonimo")
        seg = SuggestionCorner.objects.get()
        self.assertTrue(seg.anonima)
        self.assertIsNone(seg.created_by)
        self.assertEqual(seg.segnalante_display, "Anonima")

    def test_foto_salvata_senza_metadati(self):
        from PIL import Image

        foto = SimpleUploadedFile("scatto.jpg", _jpeg_con_gps(), content_type="image/jpeg")
        self._post(modo="anonimo", foto=foto)
        seg = SuggestionCorner.objects.get()
        alleg = seg.allegati.get()
        self.assertIsNone(alleg.caricato_da)
        self.assertTrue(alleg.file.name.endswith(".jpg"))
        with alleg.file.open("rb") as fh:
            img = Image.open(io.BytesIO(fh.read()))
            self.assertEqual(len(img.getexif()), 0)

    def test_foto_non_immagine_rifiutata(self):
        finto = SimpleUploadedFile("scatto.jpg", b"%PDF-1.4 non sono una foto", content_type="image/jpeg")
        resp = self._post(modo="anonimo", foto=finto)
        self.assertContains(resp, "non è un&#x27;immagine leggibile")
        self.assertFalse(SuggestionCorner.objects.exists())

    def test_foto_estensione_non_ammessa(self):
        resp = self._post(modo="anonimo", foto=SimpleUploadedFile("x.gif", b"GIF89a", content_type="image/gif"))
        self.assertContains(resp, "usa un&#x27;immagine JPG, PNG o WEBP")
        self.assertFalse(SuggestionCorner.objects.exists())


@override_settings(LEGACY_AUTH_ENABLED=False)
class AllegatoVisibilitaTest(_MediaTemporanei):
    def setUp(self):
        super().setUp()
        cache.clear()
        rep = Reparto.objects.create(nome="TORNI")
        self.team = User.objects.create_user(username="team", password="x")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.ext):
            _onboard(u)
        self.team.groups.add(Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name))
        self.client.post(reverse("suggestion_corner:nuova"), {
            "reparto_provenienza": rep.pk, "opportunity": "Con foto.", "modo": "identificato",
            "segnalante_nome": "Bruno Prova",
            "foto": SimpleUploadedFile("a.png", _jpeg_con_gps(), content_type="image/png"),
        })
        self.seg = SuggestionCorner.objects.get()
        self.alleg = SuggestionCornerAllegato.objects.get()

    def test_team_vede_foto_e_autore_nel_dettaglio(self):
        self.client.force_login(self.team)
        resp = self.client.get(reverse("suggestion_corner:dettaglio", args=[self.seg.pk]))
        self.assertContains(resp, "Bruno Prova")
        self.assertContains(resp, "nome dichiarato")
        url_foto = reverse("suggestion_corner:allegato", args=[self.alleg.pk])
        self.assertContains(resp, url_foto)
        foto = self.client.get(url_foto)
        self.assertEqual(foto.status_code, 200)
        self.assertEqual(foto["Content-Type"], "image/jpeg")
        self.assertNotIn("attachment", foto.get("Content-Disposition", ""))

    def test_estraneo_non_vede_la_foto(self):
        self.client.force_login(self.ext)
        self.assertEqual(
            self.client.get(reverse("suggestion_corner:allegato", args=[self.alleg.pk])).status_code, 404,
        )

    def test_anonimo_senza_login_rimandato_al_login(self):
        resp = self.client.get(reverse("suggestion_corner:allegato", args=[self.alleg.pk]))
        self.assertEqual(resp.status_code, 302)


@override_settings(LEGACY_AUTH_ENABLED=False, SITE_URL="https://hub.example.local")
class LocandineTest(TestCase):
    def setUp(self):
        self.team = User.objects.create_user(username="team", password="x")
        self.ext = User.objects.create_user(username="ext", password="x")
        for u in (self.team, self.ext):
            _onboard(u)
        self.team.groups.add(Group.objects.create(name=SuggestionCornerConfig.load().sms_team_group_name))
        self.url = reverse("suggestion_corner:locandine")
        self.url_pdf = reverse("suggestion_corner:locandina_pdf")
        self.std = SuggestionCornerLocandina.objects.get(nome="Standard")

    def test_preset_iniziali_dalla_migrazione(self):
        nomi = set(SuggestionCornerLocandina.objects.values_list("nome", flat=True))
        self.assertTrue({"Standard", "Sicurezza", "Idee per migliorare", "Essenziale"} <= nomi)
        self.assertTrue(self.std.predefinita)

    def test_estraneo_403(self):
        self.client.force_login(self.ext)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url_pdf, {"preset": self.std.pk}).status_code, 403)

    def test_team_vede_pagina_con_url_del_qr(self):
        self.client.force_login(self.team)
        resp = self.client.get(self.url)
        self.assertContains(resp, "https://hub.example.local/suggestion-corner/nuova/")
        self.assertContains(resp, "Standard")
        self.assertContains(resp, 'name="sc-anteprima"')

    def test_pdf_preset_scaricabile(self):
        self.client.force_login(self.team)
        resp = self.client.get(self.url_pdf, {"preset": self.std.pk, "scarica": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(resp["X-Frame-Options"], "SAMEORIGIN")

    def test_anteprima_da_campi_non_salvati(self):
        self.client.force_login(self.team)
        resp = self.client.post(self.url_pdf, {
            "preset": self.std.pk, "titolo": "Titolo provvisorio", "tema": "verde", "formato": "A3",
            "passi": "Uno\nDue",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("inline", resp["Content-Disposition"])
        self.std.refresh_from_db()
        self.assertEqual(self.std.titolo, "Hai un'idea?")  # l'anteprima non salva

    def test_qr_nel_pdf_punta_al_form(self):
        import fitz
        import zxingcpp
        from PIL import Image

        self.client.force_login(self.team)
        pdf = self.client.get(self.url_pdf, {"preset": self.std.pk}).content
        pix = fitz.open(stream=pdf, filetype="pdf")[0].get_pixmap(dpi=120)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        letti = [r.text for r in zxingcpp.read_barcodes(img)]
        self.assertEqual(letti, ["https://hub.example.local/suggestion-corner/nuova/"])

    def test_salva_preset_e_predefinito_unico(self):
        self.client.force_login(self.team)
        sic = SuggestionCornerLocandina.objects.get(nome="Sicurezza")
        resp = self.client.post(self.url, {
            "preset": sic.pk, "azione": "salva", "nome": "Sicurezza", "titolo": "Rischio?",
            "tema": "rosso", "formato": "A4", "predefinita": "on", "passi": "a\nb",
        })
        self.assertRedirects(resp, f"{self.url}?preset={sic.pk}", fetch_redirect_response=False)
        sic.refresh_from_db()
        self.assertEqual(sic.titolo, "Rischio?")
        self.assertEqual(list(SuggestionCornerLocandina.objects.filter(predefinita=True)), [sic])

    def test_salva_come_nuovo(self):
        self.client.force_login(self.team)
        self.client.post(self.url, {
            "preset": self.std.pk, "azione": "nuovo", "nome_nuovo": "Mensa", "nome": "Standard",
            "titolo": "Idee dalla mensa", "tema": "hub", "formato": "A4",
        })
        self.assertTrue(SuggestionCornerLocandina.objects.filter(nome="Mensa", titolo="Idee dalla mensa").exists())
        self.assertEqual(SuggestionCornerLocandina.objects.get(nome="Standard").titolo, "Hai un'idea?")

    def test_troppi_passi_rifiutati(self):
        self.client.force_login(self.team)
        resp = self.client.post(self.url, {
            "preset": self.std.pk, "azione": "salva", "nome": "Standard", "titolo": "T",
            "tema": "hub", "formato": "A4", "passi": "1\n2\n3\n4",
        })
        self.assertContains(resp, "Al massimo 3 passi.")

    def test_elimina_preset_ma_non_l_ultimo(self):
        self.client.force_login(self.team)
        ess = SuggestionCornerLocandina.objects.get(nome="Essenziale")
        self.client.post(self.url, {"preset": ess.pk, "azione": "elimina"})
        self.assertFalse(SuggestionCornerLocandina.objects.filter(pk=ess.pk).exists())
        SuggestionCornerLocandina.objects.exclude(pk=self.std.pk).delete()
        self.client.post(self.url, {"preset": self.std.pk, "azione": "elimina"})
        self.assertTrue(SuggestionCornerLocandina.objects.filter(pk=self.std.pk).exists())

    def test_indirizzo_qr_configurabile(self):
        self.client.force_login(self.team)
        self.client.post(self.url, {"azione": "url", "url_pubblico_form": "https://idee.example.local/sc/"})
        self.assertEqual(SuggestionCornerConfig.load().url_pubblico_form, "https://idee.example.local/sc/")
        self.assertContains(self.client.get(self.url), "https://idee.example.local/sc/")

    def test_pulsante_locandine_in_home_e_gestione_solo_team(self):
        self.client.force_login(self.team)
        self.assertContains(self.client.get(reverse("suggestion_corner:home")), self.url)
        self.assertContains(self.client.get(reverse("suggestion_corner:gestione")), self.url)
        self.client.force_login(self.ext)
        self.assertNotContains(self.client.get(reverse("suggestion_corner:home")), self.url)
