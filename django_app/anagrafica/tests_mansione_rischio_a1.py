from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Mansione
from .models_rischi import EsposizioneRischio, FattoreRischio


class EsposizioneRischioTargetTests(TestCase):
    def setUp(self):
        self.fattore = FattoreRischio.objects.create(codice="RUM", nome="Rumore")

    def test_target_solo_dipendente_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore, legacy_anagrafica_id=42)
        esp.full_clean()  # non deve sollevare
        esp.save()
        self.assertEqual(esp.legacy_anagrafica_id, 42)

    def test_nessun_target_non_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore)
        with self.assertRaises(ValidationError):
            esp.full_clean()

    def test_target_mansione_resta_valido(self):
        m = Mansione.objects.create(nome="Tornitore-A1")
        EsposizioneRischio(fattore=self.fattore, mansione=m).full_clean()
