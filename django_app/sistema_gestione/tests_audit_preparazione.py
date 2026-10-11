"""Preparazione e inviti (prompt 08, fase 5): numerazione per tipo, follow-up dei rilievi aperti,
persone e agenda proposte, annullamento, inviti Outlook con conferma (Graph simulato)."""
from datetime import date, timedelta
from unittest.mock import patch

from django.utils import timezone

from . import audit_views, programma_views
from .models import Audit, AuditAgenda, AuditEsito, AuditPersona, AuditVerificaEfficacia, CellaProgramma, ProgrammaAudit, RigaProgramma
from .services import audit as service
from .services import audit_outlook
from .tests_audit import AuditBase, _request


class NumerazioneTests(AuditBase):
    def test_prefisso_per_tipo(self):
        self.assertEqual(service.prossimo_numero_audit(2026, Audit.TIPO_SISTEMA), "RAIS-2026-01")
        self.assertEqual(service.prossimo_numero_audit(2026, Audit.TIPO_MANDATORIO_CLIENTE), "RAI-2026-01")
        self.make_audit(numero="STR-2026-01", tipo=Audit.TIPO_STRAORDINARIO)
        self.assertEqual(service.prossimo_numero_audit(2026, Audit.TIPO_STRAORDINARIO), "STR-2026-02")


class FollowupTests(AuditBase):
    def _precedente(self, esito="NC", **kwargs):
        chiuso = self.make_audit(numero=f"RAIS-2025-{AuditEsito.objects.count() + 1:02d}", stato=Audit.STATO_CHIUSO, data_inizio=date(2025, 5, 10))
        chiuso.processi_catalogo.add(self.processo)
        rilievo = AuditEsito.objects.create(audit=chiuso, testo_aggiuntivo="Verifica", punti_aggiuntivi="8.5.1",
                                            esito=esito, gravita="MINORE" if esito == "NC" else "", scostamento="Taratura scaduta", **kwargs)
        service.sincronizza_ofi(rilievo)
        return rilievo

    def test_rilievi_aperti_diventano_domande_di_follow_up_una_volta_sola(self):
        aperto = self._precedente()
        chiuso_efficace = self._precedente()
        car = service.sincronizza_ofi(chiuso_efficace)
        from .models import AzioneCorrettivaAudit
        AzioneCorrettivaAudit.objects.create(registro=car, data_richiesta=date(2025, 5, 10), responsabile=self.direzione, chiusa_il=timezone.now())
        AuditVerificaEfficacia.objects.create(esito=chiuso_efficace, risultato="EFFICACE", metodo="m", evidenza="e", data_verifica=date(2025, 9, 1))
        audit = self.make_audit(numero="RAIS-2026-09", data_inizio=date(2026, 10, 15))
        audit.processi_catalogo.add(self.processo)
        self.assertEqual(service.genera_domande_followup(audit), 1)
        self.assertEqual(service.genera_domande_followup(audit), 0)
        domanda = audit.esiti.get(domanda_snapshot__followup_di=aperto.pk)
        self.assertIn("Taratura scaduta", domanda.testo)
        self.assertTrue(domanda.strutturato)


class PersoneEAgendaProposteTests(AuditBase):
    def test_nuovo_piano_propone_responsabile_e_attivita_per_processo(self):
        self.direzione.email = "resp.qa@example.test"
        self.direzione.save()
        audit = self.make_audit(numero="RAIS-2026-10", data_inizio=date(2026, 10, 15), data_fine=date(2026, 10, 15))
        audit.processi_catalogo.add(self.processo)
        service.prepara_nuovo_audit(audit, nuovo=True)
        self.assertTrue(audit.persone.filter(ruolo=AuditPersona.RUOLO_PROCESSO, email="resp.qa@example.test").exists())
        attivita = audit.agenda.filter(processo=self.processo)
        self.assertEqual(attivita.count(), 1)
        service.prepara_nuovo_audit(audit, nuovo=True)
        self.assertEqual(audit.agenda.filter(processo=self.processo).count(), 1)
        self.assertEqual(audit.persone.filter(ruolo=AuditPersona.RUOLO_PROCESSO).count(), 1)


@patch("sistema_gestione.programma_views._has_perm", return_value=True)
class AnnullamentoTests(AuditBase):
    def test_annulla_con_motivo_e_libera_la_cella(self, _perm):
        programma = ProgrammaAudit.objects.create(anno=2026)
        riga = RigaProgramma.objects.create(programma=programma, processo=self.processo, area="QA")
        audit = self.make_audit()
        cella = CellaProgramma.objects.create(riga=riga, mese=10, audit=audit)
        programma_views.audit_annulla(_request(self.user, data={"motivo": ""}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_PIANIFICATO)
        programma_views.audit_annulla(_request(self.user, data={"motivo": "Reparto chiuso per inventario"}), audit.pk)
        audit.refresh_from_db()
        cella.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_ANNULLATO)
        self.assertIsNone(cella.audit_id)

    def test_audit_avviato_non_si_annulla(self, _perm):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO)
        programma_views.audit_annulla(_request(self.user, data={"motivo": "x"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_IN_CORSO)


class InvitoOutlookTests(AuditBase):
    def setUp(self):
        super().setUp()
        self.user.email = "lead@example.test"
        self.user.save()
        self.audit = self.make_audit(sede="Sede sintetica")
        AuditPersona.objects.create(audit=self.audit, nome="Auditato Uno", email="uno@example.test", ruolo=AuditPersona.RUOLO_AUDITATO)
        AuditPersona.objects.create(audit=self.audit, nome="Resp Due", email="due@example.test", ruolo=AuditPersona.RUOLO_PROCESSO)

    @patch("core.outlook_calendar.create_event", return_value={"id": "EVT-1"})
    @patch("core.outlook_calendar.graph_ready", return_value=True)
    def test_invito_con_partecipanti_e_conferme(self, _ready, create):
        self.assertEqual(audit_outlook.invia_invito(self.audit), "EVT-1")
        payload = create.call_args.kwargs["payload"]
        self.assertEqual(create.call_args.kwargs["target_email"], "lead@example.test")
        self.assertTrue(payload["responseRequested"])
        self.assertEqual({a["emailAddress"]["address"] for a in payload["attendees"]}, {"uno@example.test", "due@example.test"})
        self.assertEqual(set(self.audit.persone.values_list("conferma_stato", flat=True)), {"IN_ATTESA"})
        evento = {"attendees": [
            {"emailAddress": {"address": "UNO@example.test"}, "status": {"response": "accepted"}},
            {"emailAddress": {"address": "due@example.test"}, "status": {"response": "declined"}},
        ]}
        with patch("core.outlook_calendar.get_event", return_value=evento):
            conteggio = audit_outlook.aggiorna_conferme(self.audit)
        self.assertEqual(conteggio, {"ACCETTATO": 1, "RIFIUTATO": 1})
        self.assertEqual(self.audit.persone.get(email="uno@example.test").conferma_stato, "ACCETTATO")

    @patch("core.outlook_calendar.graph_ready", return_value=False)
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_graph_non_configurato_comunicazione_non_vale(self, _perm, _ready):
        Audit.objects.filter(pk=self.audit.pk).update(data_inizio=timezone.localdate() + timedelta(days=30))
        audit_views.audit_comunica(_request(self.user, data={"metodo": Audit.COM_OUTLOOK}), self.audit.pk)
        self.audit.refresh_from_db()
        self.assertIsNone(self.audit.comunicazione_il)

    def test_ics_con_partecipanti_ed_escape(self):
        self.audit.processi = "Qualità; controllo, collaudo\nfinale"
        corpo = service._ics(self.audit, ["uno@example.test"]).decode()
        self.assertIn("ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:uno@example.test", corpo)
        self.assertIn("DESCRIPTION:Qualità\\; controllo\\, collaudo\\nfinale", corpo)
        self.assertIn("SEQUENCE:", corpo)
