from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.encrypted_storage import EncryptedStorageMixin, decrypt_bytes, is_encrypted
from tasks.models import TaskAttachment


class _StorageProva(EncryptedStorageMixin, FileSystemStorage):
    pass


class MediaPrivatizzaTests(TestCase):
    """GDPR 21/10: i file storici in MEDIA_ROOT passano allo storage privato cifrato."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.media = self.tmp / "media"
        self.privata = self.tmp / "media_private"
        (self.media / "tasks_attachments/2025/01").mkdir(parents=True)
        self.privata.mkdir()
        self.nome = "tasks_attachments/2025/01/verbale.pdf"
        (self.media / self.nome).write_bytes(b"%PDF verbale storico")
        TaskAttachment.objects.bulk_create([TaskAttachment(file=self.nome)])
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _esegui(self, *args):
        field = TaskAttachment._meta.get_field("file")
        storage = _StorageProva(location=str(self.privata))
        out = io.StringIO()
        with override_settings(MEDIA_ROOT=str(self.media), DOCUMENT_ENCRYPTION_KEY=self.chiave), \
                mock.patch("core.management.commands.media_privatizza._campi_privati",
                           return_value=[(TaskAttachment, field, storage)]):
            call_command("media_privatizza", *args, stdout=out, stderr=io.StringIO())
            contenuto = (self.privata / self.nome).read_bytes() if (self.privata / self.nome).exists() else None
            in_chiaro = decrypt_bytes(contenuto) if contenuto else None
        return out.getvalue(), contenuto, in_chiaro

    chiave = Fernet.generate_key().decode()

    def test_anteprima_non_sposta(self):
        out, contenuto, _ = self._esegui()
        self.assertIn("1 file da spostare", out)
        self.assertIsNone(contenuto)
        self.assertTrue((self.media / self.nome).exists())

    def test_apply_cifra_e_toglie_dalla_webroot(self):
        out, contenuto, in_chiaro = self._esegui("--apply")
        self.assertIn("Spostati 1 file", out)
        self.assertFalse((self.media / self.nome).exists())
        self.assertTrue(is_encrypted(contenuto))
        self.assertEqual(in_chiaro, b"%PDF verbale storico")

    def test_apply_senza_chiave_si_ferma(self):
        self.chiave = ""
        with self.assertRaises(CommandError):
            self._esegui("--apply")
        self.assertTrue((self.media / self.nome).exists())


class CartelleStoricheBloccateTests(TestCase):
    """GDPR 21/10: ogni cartella protetta e' bloccata in tutti i web.config generati."""

    def test_template_e_wizard_bloccano_le_cartelle_protette(self):
        from django.conf import settings

        from core.management.commands.media_privatizza import CARTELLE_PROTETTE

        root = Path(settings.BASE_DIR).parent / "deployment"
        sorgenti = [
            root / "config" / "web.config.httpplatform.template",
            root / "config" / "web.config.wfastcgi.template",
            root / "setup_wizard.py",
        ]
        for sorgente in sorgenti:
            testo = sorgente.read_text(encoding="utf-8")
            for cartella in CARTELLE_PROTETTE:
                self.assertIn(f'<location path="media/{cartella}">', testo, f"{sorgente.name}: manca {cartella}")
            self.assertIn('<location path="media_private">', testo, f"{sorgente.name}: manca media_private")
