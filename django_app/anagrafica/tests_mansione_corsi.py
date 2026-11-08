"""Corsi ↔ mansione lavorativa: collegamento obbligatorio o consigliato, dai due lati.

Dati sintetici.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import AbilitazioneMacchina, CompetenzaSkm
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan, TrainingRequirementRule
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class MansioneCorsiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("mc_admin", "mc@example.invalid", "x")
        self.client.force_login(self.admin)
        self.mansione = CompetenzaSkm.objects.create(competenza_key="P-SAL", display="Saldatura sintetica",
                                                     tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.p1 = AnagraficaDipendente.objects.create(nome="UNO", cognome="SALDA", aliasusername="salda.uno.t")
        self.p2 = AnagraficaDipendente.objects.create(nome="DUE", cognome="SALDA", aliasusername="salda.due.t")
        for p in (self.p1, self.p2):
            AbilitazioneMacchina.objects.create(legacy_anagrafica_id=p.pk, competenza=self.mansione, livello="L",
                                                in_lista=True)
        piano = TrainingPlan.objects.create(codice="P-MC", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-SAL", titolo="Saldatura sicura",
                                                   durata_ore_teorica=8, validita_mesi=60, is_active=True)
        self.url = reverse("anagrafica:mansionario_mansione", args=[self.mansione.pk])

    def _collega(self, tipo="obbligatorio"):
        return self.client.post(reverse("anagrafica:mansionario_corso_collega", args=[self.mansione.pk]),
                                {"corso": self.corso.pk, "tipo": tipo})

    def test_collega_obbligatorio(self):
        resp = self._collega()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith("#formazione"))
        r = TrainingRequirementRule.objects.get(corso=self.corso, competenza=self.mansione)
        self.assertTrue(r.is_mandatory)
        self.assertTrue(r.is_active)

    def test_collega_consigliato_e_poi_obbligatorio_senza_doppioni(self):
        self._collega("consigliato")
        self.assertFalse(TrainingRequirementRule.objects.get(corso=self.corso).is_mandatory)
        self._collega("obbligatorio")
        self.assertEqual(TrainingRequirementRule.objects.filter(corso=self.corso).count(), 1)
        self.assertTrue(TrainingRequirementRule.objects.get(corso=self.corso).is_mandatory)

    def test_cambia_tipo_e_scollega(self):
        self._collega()
        r = TrainingRequirementRule.objects.get(corso=self.corso)
        self.client.post(reverse("anagrafica:mansionario_corso_tipo", args=[self.mansione.pk, r.pk]),
                         {"tipo": "consigliato"})
        r.refresh_from_db()
        self.assertFalse(r.is_mandatory)
        self.client.post(reverse("anagrafica:mansionario_corso_scollega", args=[self.mansione.pk, r.pk]))
        self.assertFalse(TrainingRequirementRule.objects.filter(pk=r.pk).exists())

    def test_scheda_mostra_copertura_e_iscrivi_chi_manca(self):
        self._collega()
        TrainingDeadline.objects.filter(corso=self.corso).delete()
        TrainingDeadline.objects.create(legacy_anagrafica_id=self.p1.pk, corso=self.corso, is_required=True,
                                        data_scadenza=timezone.localdate().replace(year=timezone.localdate().year + 2),
                                        stato_scadenza="VALIDO")
        body = self.client.get(self.url).content.decode()
        self.assertIn('id="tab-formazione"', body)
        self.assertIn("obbligatorio", body)
        self.assertIn("1 da fare", body)
        self.assertIn("1/2 in regola", body)
        self.assertIn(f'name="dipendenti_selezionati" value="{self.p2.pk}"', body)
        self.assertNotIn(f'name="dipendenti_selezionati" value="{self.p1.pk}"', body)

    def test_corso_da_competenza_compare_con_rendi_obbligatorio(self):
        from .models_skillmatrix import VoceMacchinaCatalogo
        VoceMacchinaCatalogo.objects.create(mansione=self.mansione, nome="Saldatura TIG", corso=self.corso)
        body = self.client.get(self.url).content.decode()
        self.assertIn("richiesto da Saldatura TIG", body)
        self.assertIn("Rendi obbligatorio", body)

    def test_consigliato_non_entra_nel_motore_degli_obblighi(self):
        from .services import requisiti
        ctx = requisiti.ambito()
        persone = {d.id: d for d in ctx._tutti() if d.id == self.p1.pk}
        self.assertIn(self.p1.pk, persone)
        self._collega("consigliato")
        richiesti = requisiti.requisiti_formazione(ctx, persone)
        self.assertNotIn(self.corso.pk, richiesti.get(self.p1.pk, {}))
        # Controprova: da obbligatorio entra.
        self._collega("obbligatorio")
        ctx = requisiti.ambito()
        richiesti = requisiti.requisiti_formazione(ctx, persone)
        self.assertIn(self.corso.pk, richiesti.get(self.p1.pk, {}))

    def test_senza_permessi_non_collega(self):
        plain = User.objects.create_user("mc_plain", "mcp@example.invalid", "x")
        self.client.force_login(plain)
        self._collega()
        self.assertFalse(TrainingRequirementRule.objects.filter(corso=self.corso).exists())
