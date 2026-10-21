"""GDPR 21/10/2026: conservazione degli archivi tecnici e audit a soli metadati. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core import audit_policy, gdpr_retention


class GdprRetentionTests(TestCase):
    def setUp(self):
        from monitoring.models import Issue, IssueOccurrence

        self.issue = Issue.objects.create(code="GDPR-T1", title="Prova", status=Issue.Status.RESOLVED)
        self.vecchia = IssueOccurrence.objects.create(issue=self.issue)
        self.nuova = IssueOccurrence.objects.create(issue=self.issue)
        IssueOccurrence.objects.filter(pk=self.vecchia.pk).update(created_at=timezone.now() - timedelta(days=120))

    def test_anteprima_non_cancella(self):
        from monitoring.models import IssueOccurrence

        out = StringIO()
        call_command("gdpr_retention", "--solo", "monitoring_occorrenze", stdout=out)
        self.assertIn("monitoring_occorrenze (termine 90 giorni): 1 righe", out.getvalue())
        self.assertEqual(IssueOccurrence.objects.count(), 2)

    def test_apply_cancella_solo_oltre_il_termine_e_registra(self):
        from core.models import AuditLog
        from monitoring.models import IssueOccurrence

        esiti = {e["codice"]: e for e in gdpr_retention.esegui(apply=True)}
        self.assertTrue(all(not e["errore"] for e in esiti.values()), esiti)
        self.assertEqual(list(IssueOccurrence.objects.values_list("pk", flat=True)), [self.nuova.pk])
        self.assertTrue(AuditLog.objects.filter(azione="gdpr_retention").exists())

    def test_termine_da_siteconfig_con_limiti(self):
        from core.models import SiteConfig

        regola = next(r for r in gdpr_retention.REGOLE if r.codice == "monitoring_occorrenze")
        SiteConfig.objects.update_or_create(chiave=gdpr_retention.chiave(regola), defaults={"valore": "1"})
        self.assertEqual(gdpr_retention.giorni(regola), gdpr_retention.GIORNI_MIN)

    def test_posta_soc_svuotata_non_cancellata(self):
        from security.models import SecurityMailboxMessage, SecuritySource

        fonte = SecuritySource.objects.create(name="Casella prova")
        msg = SecurityMailboxMessage.objects.create(source=fonte, sender="x@example.invalid", subject="Avviso",
                                                    body="corpo sintetico", raw_payload={"a": 1},
                                                    received_at=timezone.now() - timedelta(days=400))
        gdpr_retention.esegui(apply=True, solo="soc_posta")
        msg.refresh_from_db()
        self.assertEqual((msg.sender, msg.body, msg.raw_payload, msg.subject), ("", "", {}, "Avviso"))

    def test_schedule_notturno_registrato(self):
        from automazioni.schedules import SCHEDULES

        self.assertIn("core.tasks.run_gdpr_retention", {s["func"] for s in SCHEDULES})


class AuditMetadatiGdprTests(TestCase):
    def test_dati_sanitari_e_economici_solo_metadati(self):
        for chiave in ("anagrafica.visitamedica", "anagrafica.dipendenteanagraficacivile",
                       "anagrafica.saldocedolino", "anagrafica.candidato", "ai_assistant.aiconversationmessage"):
            self.assertEqual(audit_policy.classify_key(chiave), "metadata_only", chiave)
        self.assertGreaterEqual(audit_policy.AUDIT_POLICY_VERSION, 2)

    def test_modifica_di_una_visita_non_copia_le_prescrizioni(self):
        from anagrafica.models import TipoVisitaMedica, VisitaMedica
        from anagrafica.tests import _ensure_anagrafica_table
        from core.models import AuditLog

        _ensure_anagrafica_table()
        tipo = TipoVisitaMedica.objects.create(nome="Periodica audit", durata_mesi=12)
        visita = VisitaMedica.objects.create(legacy_anagrafica_id=1, tipo=tipo, data_svolgimento=timezone.localdate(),
                                             prescrizioni="PRESCRIZIONE-SINTETICA")
        visita.prescrizioni = "ALTRA-PRESCRIZIONE"
        visita.save()
        righe = AuditLog.objects.filter(azione__startswith="auto_", modulo="anagrafica")
        self.assertTrue(righe.exists())
        self.assertNotIn("PRESCRIZIONE", " ".join(str(r.dettaglio) for r in righe))
