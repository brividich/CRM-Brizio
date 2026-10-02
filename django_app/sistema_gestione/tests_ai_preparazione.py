"""Copilota preparazione audit: storico degli audit chiusi, bozza AI (mockata) e apprendimento."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ai_assistant.models import AiProposta
from gestione_specifiche.models import RegistroOFI

from . import ai_preparazione
from .models import Audit, AuditEsito, AuditPreparazione, AuditVerificaEfficacia, AzioneCorrettivaAudit
from .tests_audit import AuditBase

CHAT = "ai_assistant.services.chat_with_ollama"


class PreparazioneAiTests(AuditBase):
    def setUp(self):
        super().setUp()
        for numero, anno in (("RAIS-2024-01", 2024), ("RAIS-2025-01", 2025)):
            vecchio = self.make_audit(numero=numero, stato=Audit.STATO_CHIUSO, data_inizio=date(anno, 3, 1), data_fine=date(anno, 3, 1))
            vecchio.processi_catalogo.add(self.processo)
            esito = AuditEsito.objects.create(audit=vecchio, processo=self.processo, esito=AuditEsito.ESITO_NC,
                                              testo_aggiuntivo="Taratura strumenti registrata?", scostamento="Calibro senza taratura",
                                              documento="PROC.07")
        registro = RegistroOFI.objects.create(numero=7, data_apertura=date(2025, 3, 2), tipo="NC")
        esito.ofi = registro
        esito.save()
        AzioneCorrettivaAudit.objects.create(registro=registro, data_richiesta=date(2025, 3, 2), responsabile=self.user,
                                             causa="Scadenzario non aggiornato", azione="Scadenzario nel portale")
        AuditVerificaEfficacia.objects.create(esito=esito, risultato="NON_EFFICACE", metodo="campione", evidenza="2 calibri scaduti",
                                              data_verifica=date(2025, 9, 1), verificato_da=self.user)
        self.audit = self.make_audit(numero="RAIS-2026-05", stato=Audit.STATO_PIANIFICATO)
        self.audit.processi_catalogo.add(self.processo)

    def test_storico_ricorrenti_e_non_efficaci(self):
        storico = ai_preparazione.storico_audit(self.audit)
        self.assertEqual([a["numero"] for a in storico["precedenti"]], ["RAIS-2025-01", "RAIS-2024-01"])
        self.assertEqual(storico["ricorrenti"], ["Taratura strumenti registrata?"])
        self.assertEqual(storico["non_efficaci"][0]["car"]["causa"], "Scadenzario non aggiornato")
        testo = ai_preparazione.contesto(self.audit, storico)
        self.assertIn("verifica efficacia: NON efficace", testo)
        self.assertIn("CAR: causa «Scadenzario non aggiornato»", testo)

    def test_bozza_e_apprendimento(self):
        bozza = {"audit_precedenti": "RAIS-2024-01 e RAIS-2025-01: NC sulla taratura dei calibri.",
                 "car_cliente": "CAR 7 aperta, verifica non efficace.",
                 "documenti_registrazioni": "PROC.07, scadenzario tarature, registrazioni calibri.",
                 "obiettivi_carenze": "Verificare la taratura degli strumenti: NC ripetuta e azione non efficace."}
        import json
        with patch(CHAT, return_value=SimpleNamespace(content=json.dumps(bozza))):
            proposta = ai_preparazione.proponi_preparazione(self.audit, user=self.user)
        self.assertEqual(proposta["bozza"]["car_cliente"], "CAR 7 aperta, verifica non efficace.")
        preparazione = AuditPreparazione(audit=self.audit, verificato_da=self.user, **bozza)
        preparazione.obiettivi_carenze = "Riguardare tutto il processo acquisti."  # questo campo l'auditor lo riscrive
        preparazione.save()
        ai_preparazione.registra_esito(preparazione, user=self.user)
        p = AiProposta.objects.get(modulo="sgi")
        self.assertEqual((p.esito, p.campi_corretti), (AiProposta.MODIFICATA, ["obiettivi_carenze"]))

    @patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
    def test_pagina_e_permessi(self, _acl):
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True, "skipped": False})
        self.client.force_login(self.user)
        with patch("sistema_gestione.procedure_views._has_perm", return_value=True), \
                patch("sistema_gestione.procedure_views._assigned_executor", return_value=True):
            page = self.client.get(reverse("sistema_gestione:procedura_preparazione", args=[self.audit.pk]))
            self.assertContains(page, "Prepara dagli audit precedenti")
            with patch(CHAT, side_effect=RuntimeError("giù")):
                r = self.client.post(reverse("sistema_gestione:procedura_preparazione_ai", args=[self.audit.pk]))
            self.assertContains(r, "RAIS-2025-01")
            self.assertContains(r, "AI locale non ha risposto")
        with patch("sistema_gestione.procedure_views._has_perm", return_value=True), \
                patch("sistema_gestione.procedure_views._assigned_executor", return_value=False):
            r = self.client.post(reverse("sistema_gestione:procedura_preparazione_ai", args=[self.audit.pk]))
        self.assertEqual(r.status_code, 403)
