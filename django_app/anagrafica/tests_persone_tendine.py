"""Regola unica delle tendine persone (core/persone_tendine.py): in forza,
COGNOME NOME, ordine alfabetico. Dati sintetici."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Profile
from core import persone_tendine as pt

from .models import DipendenteAnagraficaAziendale
from .tests import _ensure_anagrafica_table, _ensure_utenti_table


class PersoneTendineTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.u_verdi = UtenteLegacy.objects.create(nome="Verdi Anna", password="x", attivo=True)
        self.u_bianchi = UtenteLegacy.objects.create(nome="carlo bianchi", password="x", attivo=True)
        self.u_spento = UtenteLegacy.objects.create(nome="Neri Ugo", password="x", attivo=False)
        self.verdi = AnagraficaDipendente.objects.create(nome="Anna", cognome="Verdi", utente=self.u_verdi)
        self.bianchi = AnagraficaDipendente.objects.create(nome="Carlo", cognome="Bianchi", utente=self.u_bianchi)
        self.rossi = AnagraficaDipendente.objects.create(nome="Mario", cognome="Rossi")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.verdi.id, data_cessazione=date(2020, 1, 31)
        )

    def test_anagrafica_in_forza_esclude_cessati_e_ordina_per_cognome(self):
        nomi = [str(a) for a in pt.anagrafica_in_forza()]
        self.assertEqual(nomi, ["BIANCHI CARLO", "ROSSI MARIO"])

    def test_utenti_legacy_per_tendina(self):
        righe = pt.utenti_legacy_per_tendina()
        # Verdi cessata, Neri account spento; etichetta dall'anagrafica collegata.
        self.assertEqual([u.etichetta for u in righe], ["BIANCHI CARLO"])

    def test_utenti_django_in_forza(self):
        User = get_user_model()
        # Convenzione del portale: first_name = cognome (displayName AD spezzato).
        zeta = User.objects.create(username="zeta", first_name="Zanetti", last_name="Luca")
        alfa = User.objects.create(username="alfa", first_name="Amato", last_name="Sara")
        ex = User.objects.create(username="ex", first_name="Verdi", last_name="Anna")
        User.objects.create(username="spento", first_name="Bassi", last_name="Pia", is_active=False)
        Profile.objects.create(user=ex, legacy_user_id=self.u_verdi.id)
        utenti = list(pt.utenti_in_forza())
        self.assertEqual(utenti[:2], [alfa, zeta])
        self.assertNotIn(ex, utenti)
        self.assertEqual(pt.etichetta_utente(alfa), "AMATO SARA")

    def test_imposta_tendina_tiene_il_valore_salvato(self):
        from django import forms

        User = get_user_model()
        ex = User.objects.create(username="ex2", first_name="Verdi", last_name="Anna")
        Profile.objects.create(user=ex, legacy_user_id=self.u_verdi.id)
        campo = forms.ModelChoiceField(queryset=User.objects.none())
        pt.imposta_tendina_persone(campo, pt.utenti_in_forza(), tieni=[ex.pk])
        self.assertIn(ex, list(campo.queryset))
        self.assertEqual(campo.label_from_instance(ex), "VERDI ANNA")
