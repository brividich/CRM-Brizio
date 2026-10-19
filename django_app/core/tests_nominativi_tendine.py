"""Tendine con persone: il testo mostrato è «COGNOME NOME» MAIUSCOLO, il value non cambia."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase


class TendineNominativiTests(TestCase):
    def setUp(self):
        # Come i login AD: il displayName «Cognome Nome» finisce con il cognome in first_name.
        self.user = get_user_model().objects.create_user(
            username="m.rossi", password="x", first_name="Rossi", last_name="Mario"
        )

    def test_attrezzature_assegnatario_mostra_nominativo_non_username(self):
        from attrezzature.forms import AttrezzaturaTaskForm

        campo = AttrezzaturaTaskForm().fields["assegnato_a"]
        etichette = {str(value): label for value, label in campo.choices if value}
        self.assertEqual(etichette[str(self.user.pk)], "ROSSI MARIO")

    def test_assenze_etichetta_anagrafica_cognome_nome_maiuscolo(self):
        from assenze.views import _anagrafica_row_label

        self.assertEqual(_anagrafica_row_label({"id": 1, "nome": "Mario", "cognome": "Rossi"}), "ROSSI MARIO")
        self.assertEqual(_anagrafica_row_label({"id": 2, "aliasusername": "m.rossi"}), "m.rossi")


class RicercaPersonaTests(TestCase):
    def test_q_persona_trova_in_qualunque_ordine(self):
        from core import naming
        from core.legacy_models import AnagraficaDipendente

        AnagraficaDipendente.objects.create(nome="MARIO", cognome="ROSSI")
        AnagraficaDipendente.objects.create(nome="LUCA", cognome="BIANCHI")
        for testo in ("rossi mario", "Mario Rossi", "ROSSI", "mar ros"):
            trovati = list(AnagraficaDipendente.objects.filter(naming.q_persona(testo, "nome", "cognome"))
                           .values_list("cognome", flat=True))
            self.assertEqual(trovati, ["ROSSI"], testo)
        self.assertFalse(AnagraficaDipendente.objects.filter(naming.q_persona("", "nome", "cognome")).exists())
