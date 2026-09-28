from datetime import date
from unittest.mock import patch

from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone

from .tests_audit import AuditBase, _request
from .models import Audit, AuditEsito, Processo, ProcessoRevisione, AuditPersona, AuditAgenda
from .audit_forms import AuditForm, ProcessoForm, RigaProgrammaForm, AuditAgendaForm
from .services.audit import verifica_completezza, prepara_nuovo_audit
from . import processi_views, audit_views
from .acl_bootstrap import _ROUTE_BINDINGS, PERM_AUDIT_EDIT, PERM_AUDIT_VIEW


class CatalogoProcessiTests(AuditBase):
    def dati_processo(self, **kwargs):
        dati = dict(codice="P-01", nome="Processo sintetico", categoria="OPERATIVO",
            responsabile=self.direzione.pk, enti="Reparto prova", scopo="Scopo verificabile",
            input="Richiesta", output="Risultato", rischi="Ritardo", indicatori="Consegne puntuali >= 95%",
            procedure="PR-01 Rev.1", punti_9100="8.1", frequenza_mesi=12, attivo="on",
            motivo="Prima emissione", versione=0)
        dati.update(kwargs)
        return dati

    def dati_audit(self, **kwargs):
        dati = dict(numero="TEST-01", tipo=Audit.TIPO_SISTEMA, en9100="on",
            lead_auditor=self.auditor.pk, processi_catalogo=[self.processo.pk],
            data_inizio="2026-10-15", sede="Sede test", metodo_intervista="on")
        dati.update(kwargs)
        return dati

    @patch("sistema_gestione.processi_views._has_perm", return_value=True)
    def test_revisioni_snapshot_e_conflitto_editor(self, _perm):
        response = processi_views.modifica(_request(self.user, data=self.dati_processo()))
        self.assertEqual(response.status_code, 302)
        processo = Processo.objects.get(codice="P-01")
        response = processi_views.modifica(_request(self.user,
            data=self.dati_processo(nome="Nome nuovo", versione=1, motivo="Aggiornamento")), processo.pk)
        self.assertEqual(response.status_code, 302)
        processo.refresh_from_db()
        self.assertEqual(processo.revisione, 2)
        self.assertEqual(processo.revisioni.get(numero=1).dati["nome"], "Processo sintetico")
        response = processi_views.modifica(_request(self.user,
            data=self.dati_processo(nome="Obsoleto", versione=1)), processo.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "altro utente")
        processo.refresh_from_db()
        self.assertEqual(processo.nome, "Nome nuovo")
        self.assertEqual(ProcessoRevisione.objects.count(), 2)

    def test_codice_case_insensitive_e_frequenza(self):
        self.processo.codice = "P-01"
        self.processo.save()
        form = ProcessoForm(self.dati_processo(codice="p-01", frequenza_mesi=0))
        self.assertFalse(form.is_valid())
        self.assertIn("codice", form.errors)
        self.assertIn("frequenza_mesi", form.errors)

    def test_catalogo_obbligatorio_testo_libero_non_sufficiente(self):
        form = AuditForm(self.dati_audit(processi_catalogo=[], processi="Inventato"))
        self.assertFalse(form.is_valid())
        self.assertIn("processi_catalogo", form.errors)

    def test_audit_compila_riferimenti_e_conserva_copia(self):
        self.processo.procedure = "PR-01 Rev.1"
        self.processo.punti_9100 = "8.1"
        self.processo.save()
        form = AuditForm(self.dati_audit())
        self.assertTrue(form.is_valid(), form.errors)
        audit = form.save()
        self.assertIn("PR-01 Rev.1", audit.procedure_criteri)
        self.assertIn("8.1", audit.punti_norma)
        self.processo.nome = "Nuovo nome"
        self.processo.revisione = 2
        self.processo.save()
        audit.refresh_from_db()
        self.assertNotIn("Nuovo nome", audit.processi)
        self.assertEqual(audit.processi_snapshot[0]["revisione"], 1)

    def test_archiviato_escluso_da_nuovi_audit(self):
        self.processo.attivo = False
        self.processo.save()
        form = AuditForm(self.dati_audit())
        self.assertFalse(form.is_valid())
        self.assertIn("processi_catalogo", form.errors)

    def test_agenda_accetta_solo_processi_del_piano_e_date_valide(self):
        audit = self.make_audit(processi_snapshot=[self.processo.snapshot()])
        audit.processi_catalogo.add(self.processo)
        altro = Processo.objects.create(codice="ALTRO", nome="Altro processo")
        dati = dict(quando="2026-10-15T10:00", processo=self.processo.pk, attivita="Esame campione S-01", ordine=20)
        form = AuditAgendaForm(dati, audit=audit)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn(self.processo.codice, form.cleaned_data["processo_area"])
        form = AuditAgendaForm(dict(dati, processo=altro.pk), audit=audit)
        self.assertFalse(form.is_valid())
        self.assertIn("processo", form.errors)
        form = AuditAgendaForm(dict(dati, quando="2026-10-16T10:00"), audit=audit)
        self.assertFalse(form.is_valid())
        self.assertIn("quando", form.errors)

    def test_salvataggio_piano_non_aggiorna_schede_retroattivamente(self):
        form = AuditForm(self.dati_audit())
        self.assertTrue(form.is_valid(), form.errors)
        audit = form.save()
        self.processo.nome = "Nome revisionato"
        self.processo.revisione = 2
        self.processo.save()
        form = AuditForm(self.dati_audit(sede="Sede cambiata"), instance=audit)
        self.assertTrue(form.is_valid(), form.errors)
        audit = form.save()
        self.assertEqual(audit.processi_snapshot[0]["revisione"], 1)
        self.assertNotIn("Nome revisionato", audit.processi)

    def test_owner_nel_team_richiede_deroga(self):
        self.processo.responsabile = self.user
        self.processo.save()
        form = AuditForm(self.dati_audit())
        self.assertFalse(form.is_valid())
        self.assertIn("imparzialita_deroga_motivo", form.errors)

    def test_programma_malformato_non_causa_500(self):
        form = AuditForm(self.dati_audit(programma="non-numerico"))
        self.assertFalse(form.is_valid())
        self.assertIn("programma", form.errors)

    def test_binding_catalogo(self):
        for nome in ("processi_catalogo", "processo_dettaglio"):
            self.assertEqual(_ROUTE_BINDINGS[f"sistema_gestione:{nome}"], PERM_AUDIT_VIEW)
        for nome in ("processo_nuovo", "processo_modifica"):
            self.assertEqual(_ROUTE_BINDINGS[f"sistema_gestione:{nome}"], PERM_AUDIT_EDIT)

    @patch("sistema_gestione.processi_views._has_perm", return_value=False)
    @patch("sistema_gestione.processi_views._nega", return_value=HttpResponseForbidden())
    def test_accesso_negato_senza_permesso(self, _nega, _perm):
        self.assertEqual(processi_views.catalogo(_request(self.user, method="get")).status_code, 403)
        self.assertEqual(processi_views.modifica(_request(self.user, data=self.dati_processo())).status_code, 403)
        self.assertFalse(Processo.objects.filter(codice="P-01").exists())

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_firma_blocca_esiti_vuoti_e_na_senza_motivo(self, _perm):
        audit = self.make_audit(stato=Audit.STATO_RAPPORTO, giudizio="Giudizio motivato")
        _, _, domanda = self.make_checklist()
        esito = AuditEsito.objects.create(audit=audit, domanda=domanda)
        for valore in ("", "NA", "CONFORME"):
            esito.esito = valore
            esito.save()
            audit_views.audit_firma_rapporto(_request(self.user), audit.pk)
            audit.refresh_from_db()
            self.assertIsNone(audit.rapporto_firmato_auditor_il)
        esito.evidenze = "Documento PR-01 Rev.1; campione S-001 del 15/10/2026 verificato."
        esito.save()
        audit_views.audit_firma_rapporto(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertIsNotNone(audit.rapporto_firmato_auditor_il)
        firma = audit.rapporto_firmato_auditor_il
        audit_views.audit_firma_rapporto(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.rapporto_firmato_auditor_il, firma)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_modifica_persone_invalida_firma_piano(self, _perm):
        audit = self.make_audit(piano_approvato_lead_da=self.user, piano_approvato_lead_il=timezone.now())
        audit_views.audit_persona_salva(_request(self.user, data={"nome": "Persona test", "ruolo": "AUDITATO"}), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.piano_approvato_lead_il)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    @patch("sistema_gestione.processi_views._has_perm", return_value=True)
    def test_render_pagine_catalogo_e_guida(self, _p, _a):
        audit = self.make_audit()
        for view, args, testo in [(processi_views.catalogo, (), "Catalogo processi"),
            (processi_views.dettaglio, (self.processo.pk,), "Registro revisioni"),
            (audit_views.audit_modifica, (), "Campo di audit"),
            (audit_views.audit_dettaglio, (audit.pk,), "Il prossimo passo")]:
            response = view(_request(self.user, method="get"), *args)
            self.assertContains(response, testo)
            self.assertNotContains(response, "{#")

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_correzione_elementi_limitata_a_bozza_e_audit_corretto(self, _perm):
        from django.http import Http404
        audit = self.make_audit(piano_approvato_lead_il=timezone.now())
        persona = AuditPersona.objects.create(audit=audit, nome="Prima", ruolo=AuditPersona.RUOLO_AUDITATO)
        audit_views.audit_elemento_modifica(_request(self.user, data={"nome":"Corretta", "ruolo":AuditPersona.RUOLO_AUDITATO}), audit.pk, "persona", persona.pk)
        persona.refresh_from_db()
        audit.refresh_from_db()
        self.assertEqual(persona.nome,"Corretta")
        self.assertIsNone(audit.piano_approvato_lead_il)
        altro = self.make_audit(numero="ALTRO")
        with self.assertRaises(Http404):
            audit_views.audit_elemento_modifica(_request(self.user, data={"azione":"rimuovi"}), altro.pk, "persona", persona.pk)
        audit.stato=Audit.STATO_PIANO_APPROVATO
        audit.save()
        with self.assertRaises(Http404):
            audit_views.audit_elemento_modifica(_request(self.user, data={"azione":"rimuovi"}), audit.pk, "persona", persona.pk)
        self.assertTrue(AuditPersona.objects.filter(pk=persona.pk).exists())

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_form_errore_conserva_evidenza(self, _perm):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO)
        _, _, domanda = self.make_checklist()
        esito = AuditEsito.objects.create(audit=audit, domanda=domanda)
        response = audit_views.audit_esito_salva(_request(self.user, data={"esito":"INVALIDO", "evidenze":"Testo da conservare"}), audit.pk, esito.pk)
        self.assertContains(response,"Testo da conservare")
        esito.refresh_from_db()
        self.assertEqual(esito.esito, "")

    def test_riga_programma_deriva_solo_dal_catalogo(self):
        self.processo.punti_9100="8.1"
        self.processo.save()
        form = RigaProgrammaForm(data={"processo":self.processo.pk,"ordine":10,"area":"Testo falsificato","punti_9100":"9.9"})
        self.assertTrue(form.is_valid(),form.errors)
        self.assertIn(self.processo.codice,form.cleaned_data["area"])
        self.assertEqual(form.cleaned_data["punti_9100"],"8.1")
