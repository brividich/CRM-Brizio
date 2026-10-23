"""Struttura Fase 3: gli altri moduli leggono ruoli, mansioni lavorative e abilitazioni.

Formazione per mansione lavorativa, scheda macchina con gli abilitati, processo SGI
con owner ed esecutori, proposte di auditati. Solo dati sintetici.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchina, AmbitoRuolo, CompetenzaSkm, DipendenteRuoloOperativo, RuoloOperativo, SogliaCopertura,
)
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan, TrainingRequirementRule
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class StrutturaFase3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("f3_admin", "f3@example.invalid", "x")
        ambito, _ = AmbitoRuolo.objects.get_or_create(nome="Produttivo", defaults={"alimenta_scheda": True})
        self.ruolo = RuoloOperativo.objects.create(nome="Operatore sintetico F3", sigla="OPF", ambito=ambito)
        self.owner = RuoloOperativo.objects.create(nome="Owner sintetico F3", sigla="OWF", ambito=ambito)
        self.anna = AnagraficaDipendente.objects.create(nome="Anna", cognome="PROVA", aliasusername="f3.anna",
                                                        email_notifica="anna@example.invalid")
        self.bruno = AnagraficaDipendente.objects.create(nome="Bruno", cognome="PROVA", aliasusername="f3.bruno",
                                                         email_notifica="bruno@example.invalid")
        self.carla = AnagraficaDipendente.objects.create(nome="Carla", cognome="PROVA", aliasusername="f3.carla",
                                                         email_notifica="carla@example.invalid")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.carla.pk, ruolo=self.owner)
        self.asset = Asset.objects.create(name="Fresa sintetica F3", asset_tag="CNC-F3- 1", reparto="F3")
        self.macchina = CompetenzaSkm.objects.create(competenza_key="F3-FRESA", display="F3 - Fresa sintetica",
                                                     tipo=CompetenzaSkm.TIPO_MACCHINA, asset=self.asset)
        self.macchina.ruoli.add(self.ruolo)
        # Anna operativa (U), Bruno in addestramento (I).
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.anna.pk, asset=self.asset,
                                            competenza=self.macchina, livello="U")
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.bruno.pk, asset=self.asset,
                                            competenza=self.macchina, livello="I")
        piano = TrainingPlan.objects.create(codice="F3P", nome="Piano sintetico F3")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="F3C", titolo="Uso sicuro fresa sintetica",
                                                   durata_ore_teorica=2)
        TrainingRequirementRule.objects.create(corso=self.corso, competenza=self.macchina)

    # ── Formazione ────────────────────────────────────────────────────────
    def test_regola_per_mansione_lavorativa_genera_fabbisogno(self):
        from .services.scadenze import ricalcola_formazione

        ricalcola_formazione([self.anna.pk, self.bruno.pk, self.carla.pk])
        tenuti = set(TrainingDeadline.objects.filter(corso=self.corso).values_list("legacy_anagrafica_id", flat=True))
        # In lista = tenuto, anche in addestramento; chi non è in lista no.
        self.assertEqual(tenuti, {self.anna.pk, self.bruno.pk})

    def test_pertinenza_corso_e_onboarding(self):
        from .services import onboarding
        from .services.training_eligibility import _legacy_ids_pertinenti

        dipendenti = {p.pk: {"mansione": ""} for p in (self.anna, self.bruno, self.carla)}
        ids, has_rules = _legacy_ids_pertinenti(self.corso, dipendenti)
        self.assertTrue(has_rules)
        self.assertEqual(ids, {self.anna.pk, self.bruno.pk})
        # Chi entra col ruolo che fa la mansione: il corso è già nell'onboarding.
        titoli = onboarding._corsi_obbligatori(None, "", "", [self.ruolo.pk])
        self.assertIn(self.corso.titolo, titoli)

    def test_form_regola_accetta_solo_mansione_lavorativa(self):
        from .forms import TrainingRequirementRuleForm

        form = TrainingRequirementRuleForm({"corso": self.corso.pk, "competenza": self.macchina.pk,
                                            "is_mandatory": "on", "is_active": "on", "priority": 0})
        self.assertTrue(form.is_valid(), form.errors)

    def test_scheda_mansione_mostra_formazione(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.macchina.pk]))
        self.assertContains(resp, "Formazione obbligatoria per chi fa questa mansione")
        self.assertContains(resp, self.corso.titolo)

    # ── Scheda macchina ───────────────────────────────────────────────────
    def test_operatori_macchina(self):
        from .services import struttura_macchina

        SogliaCopertura.objects.create(nome="Copertura fresa", asset=self.asset, minimo_abilitati=2)
        dati = struttura_macchina.operatori(self.asset, con_nomi=True)
        self.assertEqual((dati["n_operativi"], dati["n_addestramento"]), (1, 1))
        self.assertTrue(dati["uomo_solo"])
        self.assertTrue(dati["scoperta"])
        self.assertEqual(dati["persone"][0]["legacy_id"], self.anna.pk)
        senza = struttura_macchina.operatori(self.asset, con_nomi=False)
        self.assertEqual(senza["persone"], [])
        vuoto = Asset.objects.create(name="Asset senza abilitati F3", asset_tag="F3-VUOTO- 1")
        self.assertIsNone(struttura_macchina.operatori(vuoto, con_nomi=True))

    def test_scheda_asset_mostra_operatori(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(resp, "Operatori abilitati")
        self.assertContains(resp, "PROVA")
        self.assertContains(resp, "Uomo solo")

    # ── Sistema di Gestione ───────────────────────────────────────────────
    def _processo(self):
        from sistema_gestione.models import Processo

        processo = Processo.objects.create(codice="F3-P", nome="Fresatura sintetica", ruolo_owner=self.owner)
        self.macchina.processo_sgi = processo
        self.macchina.save(update_fields=["processo_sgi"])
        return processo

    def test_processo_owner_ed_esecutori(self):
        from .services.struttura_processo import persone_processo

        dati = persone_processo(self._processo())
        self.assertEqual([p["legacy_id"] for p in dati["owner"]], [self.carla.pk])
        self.assertEqual([p["legacy_id"] for p in dati["esecutori"]], [self.anna.pk])  # Bruno non è operativo
        self.assertEqual((dati["mansioni"][0]["n_operativi"], dati["mansioni"][0]["n_lista"]), (1, 2))

    def test_processo_dettaglio_mostra_chi_esegue(self):
        processo = self._processo()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("sistema_gestione:processo_dettaglio", args=[processo.pk]))
        self.assertContains(resp, "Chi possiede e chi esegue il processo")
        self.assertContains(resp, "F3 - Fresa sintetica")

    def test_proposte_auditati(self):
        from sistema_gestione.models import Audit, AuditPersona, Auditor

        from .services.struttura_processo import proposte_auditati

        processo = self._processo()
        auditor = Auditor.objects.create(user=self.admin, interno=True)
        audit = Audit.objects.create(numero="F3-2026-01", lead_auditor=auditor, processi="Fresatura",
                                     data_inizio=date(2026, 11, 2), data_fine=date(2026, 11, 2), created_by=self.admin)
        audit.processi_catalogo.add(processo)
        proposte = proposte_auditati(audit)
        self.assertEqual([(p["legacy_id"], p["ruolo"]) for p in proposte],
                         [(self.carla.pk, AuditPersona.RUOLO_PROCESSO), (self.anna.pk, AuditPersona.RUOLO_AUDITATO)])
        self.assertEqual(proposte[0]["email"], "carla@example.invalid")
        # Già nel piano: non si ripropone.
        AuditPersona.objects.create(audit=audit, nome="Qualcuno", email="anna@example.invalid",
                                    ruolo=AuditPersona.RUOLO_AUDITATO)
        self.assertEqual([p["legacy_id"] for p in proposte_auditati(audit)], [self.carla.pk])
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("sistema_gestione:audit_dettaglio", args=[audit.pk]))
        self.assertContains(resp, "Proposte dalla struttura organizzativa")
