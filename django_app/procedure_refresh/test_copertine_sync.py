"""CN-SGI: icona e logo delle copertine, stato della sincronizzazione con la cartella."""
from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteConfig

from . import libreria as lib
from .models import SgiScaffale
from .test_libreria import _doc

User = get_user_model()


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class CopertineScaffaliTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cnsgi_logo_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        ov = override_settings(PRIVATE_ATTACHMENTS_ROOT=self._tmp)
        ov.enable()
        self.addCleanup(ov.disable)
        self.admin = User.objects.create_user(username="cop_admin", password="pw", is_superuser=True)
        self.client.force_login(self.admin)
        _doc("MT CN 01", "Acquisizione ordini")
        lib.assicura_scaffali()
        self.s = SgiScaffale.objects.get()

    def _salva(self, **extra):
        dati = {f"s{self.s.pk}_nome": self.s.nome, f"s{self.s.pk}_colore": self.s.colore,
                f"s{self.s.pk}_ordine": "1", f"s{self.s.pk}_attivo": "1"}
        dati.update({f"s{self.s.pk}_{k}": v for k, v in extra.items()})
        return self.client.post(reverse("procedure_refresh:libreria_scaffali"), dati)

    def test_icona_e_logo_sulla_copertina(self):
        self._salva(icona="plane", logo=SimpleUploadedFile("ente.png", _png()))
        self.s.refresh_from_db()
        self.assertEqual(self.s.icona, "plane")
        self.assertTrue(self.s.logo.name.endswith(".jpg"))
        r = self.client.get(reverse("procedure_refresh:libreria"))
        self.assertContains(r, 'class="cn-vol-ico"')
        self.assertContains(r, f"/procedure-refresh/scaffale-logo/{self.s.pk}/")
        logo = self.client.get(reverse("procedure_refresh:libreria_scaffale_logo", args=[self.s.pk]))
        self.assertEqual(logo["Content-Type"], "image/jpeg")
        self.assertTrue(b"".join(logo.streaming_content).startswith(b"\xff\xd8"))

    def test_icona_sconosciuta_e_file_non_immagine(self):
        self._salva(icona="<script>", logo=SimpleUploadedFile("finto.png", b"non sono un'immagine"))
        self.s.refresh_from_db()
        self.assertEqual(self.s.icona, "")
        self.assertFalse(self.s.logo)

    def test_togli_logo(self):
        self._salva(logo=SimpleUploadedFile("ente.png", _png()))
        self._salva(togli_logo="1")
        self.s.refresh_from_db()
        self.assertFalse(self.s.logo)


class StatoSincronizzazioneTests(TestCase):
    def test_controlli_e_file_esclusi(self):
        from .tasks import run_sgi_auto_sync, stato_sincronizzazione

        SiteConfig.set("pr_sgi_auto_sync_attivo", "1", "test")
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ["9100/MT CN 07 Rev.3_Nuovo.pdf", "9100/Piano Cliente Rev.1.pdf",
                        "9100/MT CN 08 Rev.2_A.pdf", "9100/sub/MT CN 08 Rev.2_A.pdf"]:
                p = Path(tmp) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"%PDF-1.4 x")
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                res = run_sgi_auto_sync(reindex=False)
                stato = stato_sincronizzazione()
        self.assertTrue(res["ok"])
        # Il nome libero («Piano Cliente») entra anche dalla sincronizzazione automatica.
        from .models import ProcedureDocument

        self.assertTrue(ProcedureDocument.objects.filter(code__icontains="Piano Cliente").exists())
        titoli = {c["titolo"]: c["ok"] for c in stato["controlli"]}
        self.assertTrue(titoli["Sincronizzazione automatica accesa"])
        self.assertIn("Ultimo controllo della cartella", titoli)
        self.assertFalse(stato["tutto_ok"])  # mai controllata: il controllo periodico non è partito
        self.assertEqual(SiteConfig.get("pr_sgi_esclusi", "") and True, True)

    def test_impostazioni_mostrano_lo_stato(self):
        admin = User.objects.create_user(username="stato_admin", password="pw", is_superuser=True)
        self.client.force_login(admin)
        r = self.client.get(reverse("procedure_refresh:admin_dashboard"))
        self.assertContains(r, "Sincronizzazione automatica accesa")
        self.assertContains(r, "Cartella SGI raggiungibile dal sito")
