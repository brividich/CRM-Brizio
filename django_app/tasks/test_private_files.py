from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from tasks.models import Project, TaskAttachment
from tasks.storage import PrivateTasksStorage


class TasksPrivateStorageTests(TestCase):
    """SEC: allegati Task e documenti VRF (dati commerciali) non più su /media
    pubblico ma su storage privato cifrato, serviti solo da view protette."""

    def test_attachment_uses_private_storage_and_no_public_url(self):
        att = TaskAttachment.objects.create(
            file=SimpleUploadedFile("preventivo.pdf", b"%PDF dati commerciali"),
        )
        try:
            self.assertIsInstance(att.file.storage, PrivateTasksStorage)
            with self.assertRaises(NotImplementedError):
                _ = att.file.url
            self.assertIn(
                "media_private",
                str(att.file.storage.location).replace("\\", "/").lower(),
            )
            # Il contenuto è leggibile (e decifrato) attraverso lo storage privato
            self.assertEqual(att.file.open("rb").read(), b"%PDF dati commerciali")
        finally:
            try:
                att.file.storage.delete(att.file.name)
            except Exception:
                pass

    def test_vrf_file_field_uses_private_storage(self):
        storage = Project._meta.get_field("vrf_file").storage
        self.assertIsInstance(storage, PrivateTasksStorage)

    def test_attachment_download_url_is_registered(self):
        # La url di download esiste (serve solo attachment_id, non l'URL pubblico)
        url = reverse("tasks:task_attachment_download", args=[123])
        self.assertIn("/attachments/123/download/", url)
