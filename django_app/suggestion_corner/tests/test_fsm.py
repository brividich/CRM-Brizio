from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner

User = get_user_model()


class SuggestionCornerCleanTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.u1 = User.objects.create(username="mario")
        self.u2 = User.objects.create(username="luigi")

    def _base(self, **kw):
        defaults = dict(reparto_provenienza=self.reparto, opportunity="Test.")
        defaults.update(kw)
        return SuggestionCorner(**defaults)

    def test_clean_ok_incaricato_diverso_da_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u2)
        s.clean()  # non solleva

    def test_clean_ok_se_uno_dei_due_none(self):
        s = self._base(incaricato=self.u1, controllore=None)
        s.clean()  # non solleva

    def test_clean_solleva_se_incaricato_uguale_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u1)
        with self.assertRaises(ValidationError):
            s.clean()

    def test_prep_evento_setta_transient(self):
        s = self._base()
        s._prep_evento(self.u1, foo="bar")
        self.assertEqual(s._evento_attore, self.u1)
        self.assertEqual(s._evento_payload, {"foo": "bar"})
