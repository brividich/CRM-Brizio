"""Proposte di chiusura automatiche dell'AI: prove dai report, apprendimento dalle decisioni, chiusura da sola.

Dati sintetici; AI sempre simulata.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord, SecurityAlert, SecurityAlertActionLog, SecurityAlertDismissal, SecurityAlertProposta, SecurityEventRecord,
    SecuritySource, Severity, Status,
)
from security.services import ai_proposte, soc_settings
from security.services.alert_lifecycle import close_alert, reopen_alert

CHIEDI = "security.services.cpe_ai._chiedi"
DISPONIBILE = "security.services.cpe_ai.disponibile"


def _risposta(data):
    return {"ok": True, "data": data, "error": "", "model": "demo-model", "ms": 5}


RISOLTO = {"esito": "risolto", "confidenza": 92, "motivo": "Il backup successivo è riuscito.", "prove": ["P1", "P2"]}


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_demo", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Backup demo", vendor="Demo", source_type="email")
        soc_settings.save({"ai.proposte.soglia": 3, "ai.proposte.attesa_ore": 1}, None)

    def alert(self, job="JOB-DEMO-01", severity=Severity.WARNING, ore_fa=5, title=None):
        aperto_il = timezone.now() - timedelta(hours=ore_fa)
        dedup = f"dedup-{job}-{SecurityAlert.objects.count()}"
        event = SecurityEventRecord.objects.create(
            source=self.source, event_type="backup_job", severity=severity, occurred_at=aperto_il - timedelta(minutes=5),
            fingerprint=dedup, dedup_hash=dedup, payload={"job_name": job, "device_name": "SRV-DEMO", "status": "failed"},
        )
        alert = SecurityAlert.objects.create(source=self.source, event=event, title=title or f"Backup fallito: {job}",
                                             severity=severity, status=Status.OPEN, dedup_hash=dedup)
        SecurityAlert.objects.filter(pk=alert.pk).update(created_at=aperto_il)
        alert.refresh_from_db()
        BackupJobRecord.objects.create(source=self.source, job_name=job, status="completed", started_at=timezone.now() - timedelta(hours=1),
                                       dedup_hash=f"run-{dedup}")
        return alert

    def giro(self, data=RISOLTO):
        with mock.patch(CHIEDI, return_value=_risposta(data)) as ask, mock.patch(DISPONIBILE, return_value=(True, "")):
            out = ai_proposte.giro(limit=10)
        return out, ask


class ProveTests(_Base):
    def test_prove_dai_report_successivi(self):
        alert = self.alert()
        prove = ai_proposte.prove_alert(alert)
        self.assertTrue(any("non si è più ripetuto" in p for p in prove), prove)
        self.assertTrue(any("JOB-DEMO-01" in p and "completed" in p for p in prove), prove)

    def test_prove_inventate_tolte_e_chiusura_senza_prove_resta_aperta(self):
        numerate = ["P1: backup riuscito"]
        out = ai_proposte._valida({"esito": "risolto", "confidenza": 99, "motivo": "ok", "prove": ["P1", "P7"]}, numerate)
        self.assertEqual(out["prove"], ["P1: backup riuscito"])
        out = ai_proposte._valida({"esito": "falso_positivo", "confidenza": 99, "motivo": "ok", "prove": ["P9"]}, numerate)
        self.assertEqual(out["esito"], "aperto")
        self.assertIsNone(ai_proposte._valida({"esito": "cancella tutto"}, numerate))


class GiroTests(_Base):
    def test_propone_senza_chiudere_finche_non_ha_imparato(self):
        alert = self.alert()
        out, ask = self.giro()
        self.assertEqual(out["proposte"], 1)
        self.assertEqual(out["chiusi_da_soli"], 0)
        p = SecurityAlertProposta.objects.get(alert=alert)
        self.assertEqual((p.stato, p.esito, len(p.prove)), (SecurityAlertProposta.APERTA, "resolved", 2))
        self.assertIn("sta imparando", ai_proposte.proposta_aperta(alert).blocco)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.OPEN)
        # Niente di nuovo: nessuna nuova domanda all'AI.
        out, ask = self.giro()
        ask.assert_not_called()

    def test_alert_troppo_recente_aspetta(self):
        self.alert(ore_fa=0)
        out, ask = self.giro()
        ask.assert_not_called()

    def test_spento_non_gira(self):
        soc_settings.save({"ai.proposte.attivo": False}, None)
        self.assertIn("skipped", ai_proposte.giro_lettura())


class ApprendimentoTests(_Base):
    def _conferma(self, n):
        for i in range(n):
            alert = self.alert(job=f"JOB-{i}")
            self.giro()
            close_alert(alert, actor="soc_demo", reason="Backup rientrato", outcome="resolved")
            self.assertEqual(SecurityAlertProposta.objects.get(alert=alert).stato, SecurityAlertProposta.CONFERMATA)

    def test_chiusura_con_altro_esito_e_correzione(self):
        alert = self.alert()
        self.giro()
        close_alert(alert, actor="soc_demo", reason="Job dismesso", outcome="not_relevant")
        p = SecurityAlertProposta.objects.get(alert=alert)
        self.assertEqual((p.stato, p.esito_deciso, p.nota), (SecurityAlertProposta.CORRETTA, "not_relevant", "Job dismesso"))

    def test_dopo_n_conferme_chiude_da_sola_e_riaprire_toglie_la_fiducia(self):
        self._conferma(3)
        alert = self.alert(job="JOB-NUOVO")
        out, _ask = self.giro()
        self.assertEqual(out["chiusi_da_soli"], 1)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.CLOSED)
        self.assertTrue(alert.status_reason.startswith("Chiuso dall'AI (appreso da 3 conferme di fila)"))
        log = SecurityAlertActionLog.objects.filter(alert=alert, action="close").get()
        self.assertEqual(log.actor, ai_proposte.ACTOR)
        self.assertFalse(SecurityAlertDismissal.objects.filter(alert=alert).exists())  # l'AI non alimenta la soppressione appresa
        p = SecurityAlertProposta.objects.get(alert=alert)
        self.assertEqual(p.stato, SecurityAlertProposta.CHIUSA_AUTO)
        # La persona riapre: chiusura annullata, fiducia azzerata, il prossimo resta da confermare.
        r = self.client.post(reverse("security:alert_proposta_azione", args=[p.pk, "riapri"]), {"nota": "Il job fallisce ancora"})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        alert.refresh_from_db()
        self.assertEqual((p.stato, alert.status), (SecurityAlertProposta.ANNULLATA, Status.OPEN))
        self.assertEqual(ai_proposte.fiducia(p.schema, "resolved")["conferme"], 0)
        altro = self.alert(job="JOB-ALTRO")
        out, _ask = self.giro()
        self.assertEqual(out["chiusi_da_soli"], 0)
        self.assertEqual(SecurityAlertProposta.objects.get(alert=altro).stato, SecurityAlertProposta.APERTA)

    def test_mai_da_sola_su_alert_critici_o_con_confidenza_bassa(self):
        self._conferma(3)
        critico = self.alert(job="JOB-CRIT", severity=Severity.CRITICAL)
        self.giro()
        critico.refresh_from_db()
        self.assertEqual(critico.status, Status.OPEN)
        self.assertEqual(ai_proposte.proposta_aperta(critico).blocco, "alert critico")
        incerto = self.alert(job="JOB-INCERTO")
        self.giro({**RISOLTO, "confidenza": 40})
        incerto.refresh_from_db()
        self.assertEqual(incerto.status, Status.OPEN)

    def test_chiusura_automatica_spenta_propone_soltanto(self):
        self._conferma(3)
        soc_settings.save({"ai.proposte.chiusura_auto": False}, None)
        alert = self.alert(job="JOB-NUOVO")
        out, _ask = self.giro()
        self.assertEqual(out["chiusi_da_soli"], 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.OPEN)

    def test_le_decisioni_entrano_nella_domanda(self):
        vecchio = self.alert(job="JOB-A")
        close_alert(vecchio, actor="soc_demo", reason="Rientrato dopo il riavvio del NAS", outcome="resolved")
        close_alert(self.alert(job="JOB-B"), actor="system", reason="Regola di rientro", outcome="resolved")
        scartato = self.alert(job="JOB-C")
        self.giro()
        self.client.post(reverse("security:alert_proposta_azione", args=[scartato.proposte_ai.get().pk, "scarta"]),
                         {"nota": "Prima verificare lo spazio sul NAS"})
        nuovo = self.alert(job="JOB-D")
        decisioni = ai_proposte.decisioni_passate(nuovo)
        testo = "\n".join(decisioni)
        self.assertIn("Rientrato dopo il riavvio del NAS", testo)
        self.assertNotIn("Regola di rientro", testo)
        self.assertIn("Prima verificare lo spazio sul NAS", testo)
        scartato.refresh_from_db()
        self.assertEqual(scartato.status, Status.OPEN)


class PaginaTests(_Base):
    def test_pagina_e_conferma_dalla_coda(self):
        alert = self.alert()
        self.giro()
        r = self.client.get(reverse("security:alert_proposte"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alert da decidere, con l'AI")
        self.assertContains(r, "Il backup successivo è riuscito.")
        self.assertContains(r, reverse("security:alert_proposte"))  # voce nel menu del SOC
        r = self.client.get(reverse("security:alert_detail", args=[alert.pk]))
        self.assertContains(r, "Proposta automatica dell'AI")
        p = SecurityAlertProposta.objects.get(alert=alert)
        r = self.client.post(reverse("security:alert_proposta_azione", args=[p.pk, "conferma"]), {"nota": "Verificato il backup"})
        self.assertEqual(r.status_code, 302)
        alert.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual((alert.status, alert.status_reason, p.stato), (Status.CLOSED, "Verificato il backup", SecurityAlertProposta.CONFERMATA))
        # Già decisa: una seconda conferma non fa niente.
        self.client.post(reverse("security:alert_proposta_azione", args=[p.pk, "conferma"]))
        self.assertEqual(SecurityAlertActionLog.objects.filter(alert=alert, action="close").count(), 1)

    def test_riapertura_manuale_da_scheda_alert(self):
        alert = self.alert()
        p = SecurityAlertProposta.objects.create(alert=alert, schema="x", esito="resolved", stato=SecurityAlertProposta.CHIUSA_AUTO,
                                                 decisa_il=timezone.now())
        close_alert(alert, actor=ai_proposte.ACTOR, reason="AI", outcome="resolved")
        reopen_alert(alert, actor="soc_demo", reason="Non è rientrato")
        p.refresh_from_db()
        self.assertEqual((p.stato, p.nota), (SecurityAlertProposta.ANNULLATA, "Non è rientrato"))


class ScartiEBudgetTests(_Base):
    def test_risposta_non_valida_ricordata_e_non_richiesta_finche_il_contesto_non_cambia(self):
        alert = self.alert()
        out, ask = self.giro({"esito": "cancella tutto"})
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(out["scartate"], 1)
        riga = SecurityAlertProposta.objects.get(alert=alert)
        self.assertEqual(riga.stato, SecurityAlertProposta.NON_VALIDA)
        self.assertTrue(riga.contesto_hash)
        self.assertIsNone(ai_proposte.proposta_aperta(alert))
        self.assertEqual(ai_proposte.fiducia(riga.schema, "aperto")["errori"], 0)  # non è una decisione di una persona
        out, ask = self.giro({"esito": "cancella tutto"})
        ask.assert_not_called()
        # Nuovo report sullo stesso job: il contesto cambia e l'alert torna all'AI.
        BackupJobRecord.objects.create(source=self.source, job_name="JOB-DEMO-01", status="failed",
                                       started_at=timezone.now() - timedelta(minutes=10), dedup_hash="run-nuovo")
        out, ask = self.giro()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.NON_VALIDA).count(), 1)
        self.assertIsNotNone(ai_proposte.proposta_aperta(alert))

    def test_errore_di_collegamento_non_salvato(self):
        self.alert()
        errore = {"ok": False, "data": None, "error": "Ollama non raggiungibile: rete giù", "model": "m", "ms": 1}
        with mock.patch(CHIEDI, return_value=errore), mock.patch(DISPONIBILE, return_value=(True, "")):
            ai_proposte.giro(limit=10)
        self.assertFalse(SecurityAlertProposta.objects.exists())

    def test_giro_con_scadenza_sotto_il_worker(self):
        from ai_assistant import http_client
        from security.services.cpe_ai import TETTO_PIANIFICATO

        self.alert()
        residui = []

        def _chiedi(*args, **kwargs):
            residui.append(http_client.residuo())
            return _risposta(RISOLTO)

        with mock.patch(CHIEDI, side_effect=_chiedi), mock.patch(DISPONIBILE, return_value=(True, "")):
            ai_proposte.giro(limit=10)
        self.assertTrue(residui)
        self.assertTrue(all(r is not None and 0 < r <= TETTO_PIANIFICATO for r in residui))
