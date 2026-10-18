"""Regressioni dei finding delle review indipendenti (sicurezza e QA lead auditor) del prompt 08."""
from datetime import date, timedelta
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import SiteConfig

from . import audit_views, automation_views, miei_rilievi_views, procedure_views, programma_views
from .models import (Audit, AuditEsito, AuditPersona, AuditRapportoVersione, AzioneCorrettivaAudit, ChecklistProcesso,
                     ProgrammaAudit, Processo)
from .services import audit as service
from .services import cruscotto
from .services.audit_automation import problemi_esito
from .tests_audit import AuditBase, _request
from .tests_audit_pro import _StoragePrivato

User = get_user_model()


class RapportoStoricoTests(AuditBase):
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_audit_chiuso_senza_emissione_non_esce_come_bozza(self, _perm):
        audit = self.make_audit(stato=Audit.STATO_CHIUSO, giudizio="Storico")
        response = audit_views.audit_export(_request(self.user, method="get"), audit.pk, "rapporto")
        self.assertNotIn("BOZZA", response["Content-Disposition"])
        testo = "".join(p.get_text() for p in fitz.open(stream=response.content, filetype="pdf"))
        self.assertNotIn("BOZZA - NON EMESSO", testo)
        self.assertIn("rigenerato", testo)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_versione_immutabile_e_impronta_riverificata(self, _perm):
        rdd = User.objects.create_user(username="rdd-imm", password="x")
        audit = self.make_audit(stato=Audit.STATO_RAPPORTO, rapporto_firmato_auditor_da=self.user, rapporto_firmato_auditor_il=timezone.now(),
                                rapporto_convalidato_ente_da=self.direzione, rapporto_convalidato_ente_il=timezone.now())
        with _StoragePrivato():
            with self.captureOnCommitCallbacks(execute=True):
                audit_views.audit_valuta_rdd(_request(rdd, data={"valutazione_rdd": "ok"}), audit.pk)
            emesso = audit.versioni_rapporto.get()
            emesso.sha256 = "0" * 64
            with self.assertRaises(ValidationError):
                emesso.save()
            with self.assertRaises(ValidationError):
                emesso.delete()
            AuditRapportoVersione.objects.filter(pk=emesso.pk).update(sha256="0" * 64)  # file alterato fuori dall'app
            response = audit_views.audit_export(_request(self.user, method="get"), audit.pk, "rapporto")
        self.assertEqual(response.status_code, 302)


class FirmeSeparateTests(AuditBase):
    def _firmato(self):
        return self.make_audit(stato=Audit.STATO_RAPPORTO, rapporto_firmato_auditor_da=self.user, rapporto_firmato_auditor_il=timezone.now())

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_ente_esterno_al_team_e_rdd_diverso_dall_ente(self, _perm):
        audit = self._firmato()
        audit_views.audit_convalida_ente(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.rapporto_convalidato_ente_il)
        audit_views.audit_convalida_ente(_request(self.direzione), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.rapporto_convalidato_ente_da, self.direzione)
        audit_views.audit_valuta_rdd(_request(self.direzione, data={"valutazione_rdd": "x"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_RAPPORTO)

    @patch("sistema_gestione.services.audit._verifica_copertura_procedurale")
    def test_convalida_programma_diversa_dall_approvatore(self, _cop):
        programma = ProgrammaAudit.objects.create(anno=2026, stato=ProgrammaAudit.STATO_PROPOSTA, proposto_da=self.user,
                                                  approvato_da=self.direzione, approvato_il=timezone.now())
        with self.assertRaises(service.TransizioneNonAmmessa):
            service.convalida_programma(programma, utente=self.direzione)
        rdd = User.objects.create_user(username="rdd-prog", password="x")
        service.convalida_programma(programma, utente=rdd)
        self.assertEqual(programma.stato, ProgrammaAudit.STATO_APPROVATO)


@patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
class LostUpdateTests(AuditBase):
    def test_salvataggio_classico_azzera_il_token(self, _executor):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO, data_inizio=timezone.localdate(), data_fine=timezone.localdate())
        esito = AuditEsito.objects.create(audit=audit, testo_aggiuntivo="x", punti_aggiuntivi="8.1")
        dati = {"versione": 0, "esito": "CONFORME", "evidenze": "A", "salvataggio_id": "T"}
        automation_views.esito_bozza(_request(self.user, data=dati), audit.pk, esito.pk)
        esito.refresh_from_db()
        service.salva_esito(esito, utente=self.direzione)  # il coauditor registra dal form classico
        ripetuto = automation_views.esito_bozza(_request(self.user, data=dati), audit.pk, esito.pk)
        self.assertEqual(ripetuto.status_code, 409)


class MieiRilieviMultiprocessoTests(AuditBase):
    def test_responsabile_vede_solo_il_proprio_processo(self):
        resp_a = User.objects.create_user(username="resp-a", password="x", email="a@example.test")
        resp_b = User.objects.create_user(username="resp-b", password="x", email="b@example.test")
        pa = Processo.objects.create(codice="PA", nome="A", responsabile=resp_a)
        pb = Processo.objects.create(codice="PB", nome="B", responsabile=resp_b)
        audit = self.make_audit(rapporto_firmato_auditor_il=timezone.now(), rapporto_firmato_auditor_da=self.user)
        for email in ("a@example.test", "b@example.test"):
            AuditPersona.objects.create(audit=audit, nome=email, email=email, ruolo=AuditPersona.RUOLO_PROCESSO)
        nc_a = AuditEsito.objects.create(audit=audit, processo=pa, testo_aggiuntivo="x", esito="NC", gravita="MINORE", evidenze="e")
        AuditEsito.objects.create(audit=audit, processo=pb, testo_aggiuntivo="y", esito="NC", gravita="MINORE", evidenze="e")
        self.assertEqual(list(miei_rilievi_views.rilievi_utente(resp_a)), [nc_a])

    def test_email_corretta_ricollega_la_persona(self):
        vecchio = User.objects.create_user(username="vecchio", password="x", email="vecchio@example.test")
        nuovo = User.objects.create_user(username="nuovo", password="x", email="nuovo@example.test")
        persona = AuditPersona.objects.create(audit=self.make_audit(), nome="P", email="vecchio@example.test", ruolo=AuditPersona.RUOLO_AUDITATO)
        self.assertEqual(persona.user, vecchio)
        persona.email = "nuovo@example.test"
        persona.save()
        self.assertEqual(persona.user, nuovo)


class DatiStoriciECoperturaTests(AuditBase):
    def test_nc_storica_di_audit_chiuso_non_diventa_incompleta(self):
        audit = self.make_audit(stato=Audit.STATO_CHIUSO)
        nc = AuditEsito.objects.create(audit=audit, testo_aggiuntivo="x", punti_aggiuntivi="8.1", esito="NC", evidenze="e")
        self.assertEqual(problemi_esito(nc), [])
        self.assertEqual(cruscotto.chiave_rilievo(nc), "NC_ND")

    def test_clausola_attribuita_alla_norma_della_domanda(self):
        anno = timezone.localdate().year
        self.processo.punti_9100 = "7.1"
        self.processo.punti_45001 = "7.1"
        self.processo.save()
        audit = self.make_audit(stato=Audit.STATO_CHIUSO, en9100=True, iso45001=True, data_inizio=date(anno, 3, 1))
        domanda = ChecklistProcesso.objects.create(processo=self.processo, codice="Q1", norma="iso45001", punti="7.1", domanda="d", criterio="c")
        AuditEsito.objects.create(audit=audit, modello_processo=domanda, processo=self.processo, testo_aggiuntivo="x",
                                  domanda_snapshot={"punti": "7.1"}, esito="CONFORME", evidenze="ok")
        copertura = {n["norma"]: n for n in cruscotto.copertura_clausole(anno)}
        self.assertEqual(copertura["ISO 45001"]["verificate"], 1)
        self.assertEqual(copertura["EN 9100"]["verificate"], 0)


class FollowupLimitiTests(AuditBase):
    def test_non_si_ripete_dopo_follow_up_conforme(self):
        chiuso = self.make_audit(numero="RAIS-2024-01", stato=Audit.STATO_CHIUSO, data_inizio=date(2025, 1, 10))
        chiuso.processi_catalogo.add(self.processo)
        rilievo = AuditEsito.objects.create(audit=chiuso, testo_aggiuntivo="x", punti_aggiuntivi="8.5", esito="OFI", evidenze="e")
        secondo = self.make_audit(numero="RAIS-2025-02", stato=Audit.STATO_CHIUSO, data_inizio=date(2025, 9, 10))
        secondo.processi_catalogo.add(self.processo)
        service.genera_domande_followup(secondo)
        secondo.esiti.filter(domanda_snapshot__followup_di=rilievo.pk).update(esito="CONFORME")
        terzo = self.make_audit(numero="RAIS-2026-03", data_inizio=date(2026, 10, 10))
        terzo.processi_catalogo.add(self.processo)
        self.assertEqual(service.genera_domande_followup(terzo), 0)


class SollecitiFallbackTests(AuditBase):
    @patch("core.email_utils.send_hub_mail", return_value=1)
    @patch("core.notifiche.invia_notifica_email", return_value=1)
    def test_senza_profilo_ripiega_su_email_ed_escalation_al_responsabile_di_funzione(self, email, mail):
        from . import tasks

        self.direzione.email = "resp.funzione@example.test"
        self.direzione.save()
        audit = self.make_audit()
        esito = AuditEsito.objects.create(audit=audit, processo=self.processo, testo_aggiuntivo="x", punti_aggiuntivi="8.5", esito="NC", gravita="MINORE", evidenze="e")
        voce = service.sincronizza_ofi(esito)
        resp = User.objects.create_user(username="resp-car", password="x", email="resp.car@example.test")
        AzioneCorrettivaAudit.objects.create(registro=voce, data_richiesta=timezone.localdate() - timedelta(days=200), responsabile=resp)
        risultato = tasks.run_car_solleciti()
        self.assertEqual(risultato["solleciti"], 1)
        email.assert_called_once()
        self.assertIn("resp.funzione@example.test", mail.call_args.kwargs["recipients"])


class QualificaAllaDataTests(AuditBase):
    def test_qualifica_che_scade_prima_dell_audit(self):
        self.auditor.qualifica_scadenza = date(2026, 10, 1)
        self.auditor.save()
        nomi = service.auditor_non_qualificati(lead=self.auditor, auditor=[], al=date(2026, 10, 15))
        self.assertTrue(nomi and "in scadenza" in nomi[0])


@patch("sistema_gestione.programma_views._has_perm", return_value=True)
class AnnullamentoAvvisoTests(AuditBase):
    @patch("core.email_utils.send_hub_mail", return_value=1)
    def test_annullamento_avvisa_gli_auditati(self, mail, _perm):
        audit = self.make_audit(comunicazione_il=timezone.now(), comunicazione_metodo=Audit.COM_CALENDARIO)
        AuditPersona.objects.create(audit=audit, nome="A", email="a@example.test", ruolo=AuditPersona.RUOLO_AUDITATO)
        programma_views.audit_annulla(_request(self.user, data={"motivo": "Fermo impianto"}), audit.pk)
        allegati = mail.call_args.kwargs["attachments"]
        self.assertIn("METHOD:CANCEL", allegati[0][1].decode())

    def test_deroga_non_approvabile_dal_responsabile_del_processo(self, _perm):
        SiteConfig.set("sistema_gestione.audit_deroga_imparzialita_ammessa", "1")
        self.processo.responsabile = self.user
        self.processo.save()
        terzo = Processo.objects.create(codice="P3", nome="Terzo", responsabile=self.direzione)
        audit = self.make_audit(imparzialita_deroga_motivo="Unico esperto")
        audit.processi_catalogo.add(self.processo, terzo)
        programma_views.audit_approva_deroga(_request(self.direzione), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.imparzialita_deroga_approvata_il)


class ComunicazioneFuoriTransazioneTests(AuditBase):
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views.service.invia_email_comunicazione", side_effect=RuntimeError("SMTP non raggiungibile"))
    def test_email_fallita_la_comunicazione_non_vale(self, _invio, _perm):
        audit = self.make_audit(data_inizio=timezone.localdate() + timedelta(days=30))
        AuditPersona.objects.create(audit=audit, nome="A", email="a@example.test", ruolo=AuditPersona.RUOLO_AUDITATO)
        audit_views.audit_comunica(_request(self.user, data={"metodo": Audit.COM_EMAIL}), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.comunicazione_il)


class CarResponsabileTests(AuditBase):
    def test_responsabile_senza_modifica_non_riassegna(self):
        audit = self.make_audit()
        esito = AuditEsito.objects.create(audit=audit, testo_aggiuntivo="x", punti_aggiuntivi="8.5", esito="NC", gravita="MINORE", evidenze="e")
        voce = service.sincronizza_ofi(esito)
        resp = User.objects.create_user(username="resp-car2", password="x")
        AzioneCorrettivaAudit.objects.create(registro=voce, data_richiesta=timezone.localdate(), responsabile=resp)
        solo_miei = lambda r, p: p == "sistema_gestione.audit.miei_rilievi"  # noqa: E731
        with patch("sistema_gestione.procedure_views._has_perm", side_effect=solo_miei):
            response = procedure_views.car(_request(resp, method="get"), voce.pk)
        import re

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertRegex(html, re.compile(r'<select[^>]*name="responsabile"[^>]*disabled|<select[^>]*disabled[^>]*name="responsabile"'))
