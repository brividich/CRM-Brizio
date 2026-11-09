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


@override_settings(LEGACY_AUTH_ENABLED=False)
class CorsoAChiServeTests(TestCase):
    """Il viceversa: dalla creazione/modifica del corso si sceglie a chi serve."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        from .models import RuoloOperativo
        self.admin = User.objects.create_superuser("acs_admin", "acs@example.invalid", "x")
        self.client.force_login(self.admin)
        self.m1 = CompetenzaSkm.objects.create(competenza_key="P-A", display="Assemblaggio", tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.m2 = CompetenzaSkm.objects.create(competenza_key="P-B", display="Collaudo", tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.ruolo = RuoloOperativo.objects.create(nome="Preposto sintetico")
        self.piano = TrainingPlan.objects.create(codice="P-ACS", nome="Piano sintetico")

    def _dati(self, **extra):
        d = {"piano": self.piano.pk, "titolo": "Corso a chi serve", "durata_ore_teorica": "4", "validita_mesi": "0",
             "quiz_punteggio_minimo": "0", "stato": "ATTIVO", "is_active": "on"}
        d.update(extra)
        return d

    def test_creazione_con_mansioni_obbligatorie_e_consigliate(self):
        resp = self.client.post(reverse("anagrafica:formazione_corso_create"), self._dati(
            mansioni_obbligatorie=[self.m1.pk], mansioni_consigliate=[self.m2.pk], ruoli_obbligatori=[self.ruolo.pk]))
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(titolo="Corso a chi serve")
        self.assertTrue(TrainingRequirementRule.objects.get(corso=corso, competenza=self.m1).is_mandatory)
        self.assertFalse(TrainingRequirementRule.objects.get(corso=corso, competenza=self.m2).is_mandatory)
        self.assertTrue(TrainingRequirementRule.objects.get(corso=corso, ruolo_operativo=self.ruolo).is_mandatory)

    def test_stessa_mansione_obbligatoria_e_consigliata_rifiutata(self):
        resp = self.client.post(reverse("anagrafica:formazione_corso_create"), self._dati(
            mansioni_obbligatorie=[self.m1.pk], mansioni_consigliate=[self.m1.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TrainingCourse.objects.filter(titolo="Corso a chi serve").exists())
        self.assertIn("Già indicate come obbligatorie", resp.content.decode())

    def test_modifica_allinea_e_non_tocca_area_e_persona(self):
        corso = TrainingCourse.objects.create(piano=self.piano, codice="C-ACS", titolo="Corso a chi serve",
                                              durata_ore_teorica=4, is_active=True)
        TrainingRequirementRule.objects.create(corso=corso, competenza=self.m1, is_mandatory=True)
        persona = TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=99, is_mandatory=True)
        # La pagina di modifica mostra già la mansione selezionata.
        body = self.client.get(reverse("anagrafica:formazione_corso_edit", args=[corso.pk])).content.decode()
        self.assertIn("A chi serve", body)
        self.assertRegex(body, rf'<option value="{self.m1.pk}" selected')
        # m1 diventa consigliata, m2 non c'è: m1 si aggiorna, la regola per persona resta.
        self.client.post(reverse("anagrafica:formazione_corso_edit", args=[corso.pk]),
                         self._dati(mansioni_consigliate=[self.m1.pk]))
        r = TrainingRequirementRule.objects.get(corso=corso, competenza=self.m1)
        self.assertFalse(r.is_mandatory)
        self.assertTrue(TrainingRequirementRule.objects.filter(pk=persona.pk).exists())
        # Tolta da tutte le liste: la regola sparisce.
        self.client.post(reverse("anagrafica:formazione_corso_edit", args=[corso.pk]), self._dati())
        self.assertFalse(TrainingRequirementRule.objects.filter(corso=corso, competenza=self.m1).exists())
        self.assertTrue(TrainingRequirementRule.objects.filter(pk=persona.pk).exists())

    def test_collegamento_visibile_dai_due_lati(self):
        self.client.post(reverse("anagrafica:formazione_corso_create"), self._dati(mansioni_consigliate=[self.m2.pk]))
        corso = TrainingCourse.objects.get(titolo="Corso a chi serve")
        body = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.m2.pk])).content.decode()
        self.assertIn(corso.titolo, body)
        self.assertIn("consigliato", body)


@override_settings(LEGACY_AUTH_ENABLED=False)
class SchedaCorsoAChiServeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("sca_admin", "sca@example.invalid", "x")
        self.client.force_login(self.admin)
        self.m = CompetenzaSkm.objects.create(competenza_key="P-SC", display="Verniciatura", tipo=CompetenzaSkm.TIPO_PROCESSO)
        piano = TrainingPlan.objects.create(codice="P-SC", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-SC", titolo="Vernici sicure",
                                                   durata_ore_teorica=4, is_active=True)

    def test_cambia_tipo_dalla_scheda_corso(self):
        r = TrainingRequirementRule.objects.create(corso=self.corso, competenza=self.m, is_mandatory=True)
        url = reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk])
        self.assertIn("Rendi consigliato", self.client.get(url).content.decode())
        self.client.post(reverse("anagrafica:formazione_corso_req_rule_tipo", args=[self.corso.pk, r.pk]),
                         {"tipo": "consigliato"})
        r.refresh_from_db()
        self.assertFalse(r.is_mandatory)
        self.assertIn("Rendi obbligatorio", self.client.get(url).content.decode())

    def test_mansioni_da_competenza_visibili_sul_corso(self):
        from .models_skillmatrix import VoceMacchinaCatalogo
        VoceMacchinaCatalogo.objects.create(mansione=self.m, nome="Verniciatura a spruzzo", corso=self.corso)
        body = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk])).content.decode()
        self.assertIn("Richiesto anche come requisito di una competenza", body)
        self.assertIn("Verniciatura a spruzzo", body)
