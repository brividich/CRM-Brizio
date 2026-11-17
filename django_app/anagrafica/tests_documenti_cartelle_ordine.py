"""Scheda dipendente: i documenti arrivano raggruppati per cartella (dati sintetici).

Il template usa `{% regroup %}`, che unisce solo elementi consecutivi: con l'ordine
per data la stessa cartella compariva due volte dopo un caricamento.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from .models import CartellaDocumentoDipendente, DocumentoDipendente
from .tests import _ensure_anagrafica_table
from .tests_exports_persone import _insert_dipendente


class DocumentiRaggruppatiPerCartellaTests(TestCase):
    def setUp(self):
        self.private = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)
        override = override_settings(ANAGRAFICA_PRIVATE_ROOT=str(self.private))
        override.enable()
        self.addCleanup(override.disable)

        _ensure_anagrafica_table()
        self.legacy_id = _insert_dipendente(7201, "Anna", "Bianchi")
        self.superuser = get_user_model().objects.create_superuser("ordcart_super", "o@example.invalid", "x")
        self.contratti = CartellaDocumentoDipendente.objects.create(nome="Contratti")
        self.richiami = CartellaDocumentoDipendente.objects.create(nome="Richiami")

    def _doc(self, cartella, nome, giorni_fa):
        doc = DocumentoDipendente(
            legacy_anagrafica_id=self.legacy_id, tipo=DocumentoDipendente.Tipo.MANUALE,
            cartella=cartella, nome_originale=nome, tipo_mime="application/pdf",
        )
        doc.file.save(nome, ContentFile(b"%PDF-1.4 sintetico"), save=True)
        DocumentoDipendente.objects.filter(pk=doc.pk).update(
            created_at=timezone.now() - timedelta(days=giorni_fa)
        )

    def _documenti(self):
        from .views import dipendente_detail

        request = RequestFactory().get(f"/anagrafica/dipendenti/{self.legacy_id}/")
        request.user = self.superuser
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        with patch("anagrafica.views.dipendenti.render") as render:
            dipendente_detail(request, legacy_id=self.legacy_id)
        return render.call_args.args[2]["documenti_dipendente"]

    def test_stessa_cartella_consecutiva_dopo_nuovo_caricamento(self):
        self._doc(self.contratti, "contratto_vecchio.pdf", 10)
        self._doc(self.richiami, "richiamo.pdf", 5)
        self._doc(None, "sciolto.pdf", 2)
        self._doc(self.contratti, "contratto_nuovo.pdf", 0)

        nomi = [d.nome_originale for d in self._documenti()]
        self.assertEqual(
            nomi, ["contratto_nuovo.pdf", "contratto_vecchio.pdf", "richiamo.pdf", "sciolto.pdf"]
        )
