"""Regression: il form della specifica deve renderizzare l'allegato privato.

L'allegato vive su ``PrivateSpecificaStorage`` (``url()`` solleva
``NotImplementedError``). Il ``ClearableFileInput`` di default, per un file
esistente, accede a ``value.url`` in ``is_initial`` → 500 in modifica.
"""
import os
import shutil
import tempfile

from django.test import TestCase, override_settings

from gestione_specifiche.forms import SpecificaForm
from gestione_specifiche.models import Specifica


class SpecificaFormAllegatoWidgetTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.priv = os.path.join(self.tmp, "priv")

    def _spec_con_allegato(self):
        with override_settings(GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv):
            spec = Specifica.objects.create(
                codice="SPEC-W1", revisione="A", titolo="t",
                tipo="specifica", fonte="generica",
            )
            spec.allegato.save("prova.pdf", __import__(
                "django.core.files.base", fromlist=["ContentFile"]
            ).ContentFile(b"%PDF-1.4 x"), save=True)
            return spec

    def test_render_form_con_allegato_non_solleva(self):
        """Rendere il form in modifica non deve sollevare NotImplementedError."""
        spec = self._spec_con_allegato()
        with override_settings(GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv):
            form = SpecificaForm(instance=spec)
            html = str(form["allegato"])  # <- prima del fix: NotImplementedError
        self.assertIn("type=\"file\"", html)
