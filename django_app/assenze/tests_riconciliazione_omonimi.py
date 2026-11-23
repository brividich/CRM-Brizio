from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from assenze.riconciliazione import trova_conflitti


class OmonimiTests(SimpleTestCase):
    """Audit P12: un conflitto fra omonimi è segnato «da verificare»."""

    def _dati(self):
        presenze = [SimpleNamespace(id=1, nome_dipendente="Mario Rossi", data=date(2026, 3, 2), ore_totali=8, assenza_id=None)]
        assenze = [{"id": 9, "copia_nome": "MARIO ROSSI", "data_inizio": date(2026, 3, 1),
                    "data_fine": date(2026, 3, 5), "tipo_assenza": "Ferie"}]
        return presenze, assenze

    def test_omonimo_segnato(self):
        presenze, assenze = self._dati()
        (c,) = trova_conflitti(presenze, assenze, {"MARIO ROSSI"})
        self.assertTrue(c.omonimo)

    def test_nome_unico_non_segnato(self):
        presenze, assenze = self._dati()
        (c,) = trova_conflitti(presenze, assenze)
        self.assertFalse(c.omonimo)
