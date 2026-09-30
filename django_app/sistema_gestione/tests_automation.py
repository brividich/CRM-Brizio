import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import fitz
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404, HttpResponseForbidden
from django.test import override_settings
from django.utils import timezone

from .tests_audit import AuditBase, _request
from .models import (Audit, AuditEsito, AuditAllegato, AuditVerificaEfficacia, AuditRapportoVersione,
                     ChecklistProcesso, Processo, ProgrammaAudit)
from .services import audit as service
from .services import audit_automation as automation
from .audit_forms import AuditEsitoForm
from .automation_forms import AllegatoEvidenzaForm, VerificaEfficaciaForm
from . import automation_views as views
from .audit_exports import rapporto_audit_pdf
from .storage import PrivateSistemaGestioneStorage


class AutomazioniAuditTests(AuditBase):
    def setUp(self):
        super().setUp()
        self.processo.scopo = "Controllare l'esito del processo"
        self.processo.input = "Ordine approvato"
        self.processo.output = "Risultato verificato"
        self.processo.rischi = "Ritardo"
        self.processo.indicatori = "Consegne puntuali >= 95%"
        self.processo.procedure = "PR-TEST Rev.1"
        self.processo.punti_9100 = "8.1"
        self.processo.save()

    def domanda(self, **kwargs):
        dati = dict(processo=self.processo, codice="TEST-01", punti="8.1", domanda="Il campione segue il criterio?",
                    criterio="PR-TEST Rev.1", attiva=True)
        dati.update(kwargs)
        return ChecklistProcesso.objects.create(**dati)

    def esito(self, **kwargs):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO, data_inizio=timezone.localdate(),
                               data_fine=timezone.localdate())
        dati = dict(audit=audit, processo=self.processo, testo_aggiuntivo="Verifica campione", punti_aggiuntivi="8.1", strutturato=True)
        dati.update(kwargs)
        return AuditEsito.objects.create(**dati)

    def dati_esito(self, **kwargs):
        dati = dict(esito="CONFORME", documento="PR-TEST", revisione_documento="1", campione="Campione S-001, 3 pezzi",
                    data_verifica=timezone.localdate().isoformat(), evidenze="Tre pezzi conformi al criterio", versione=0)
        dati.update(kwargs)
        return dati

    def test_proposte_solo_bozze_senza_duplicati(self):
        self.assertEqual(automation.proponi_domande(self.processo), 6)
        self.assertFalse(self.processo.checklist.filter(attiva=True).exists())
        self.assertEqual(automation.proponi_domande(self.processo), 0)
        self.assertEqual(self.processo.checklist.get(codice="EN9100-KPI").criterio, self.processo.indicatori)

    def test_proposte_non_inventano_riferimenti_normativi(self):
        self.processo.punti_9100 = ""
        self.processo.save()
        self.assertEqual(automation.proponi_domande(self.processo), 0)

    def test_checklist_storicizzata_idempotente_e_filtrata_per_norma(self):
        domanda = self.domanda()
        self.domanda(codice="ISMS", norma="iso27001")
        audit = self.make_audit(processi_snapshot=[self.processo.snapshot()])
        domanda.domanda = "Testo cambiato nel catalogo"
        domanda.save()
        self.assertEqual(service.inizializza_checklist(audit), 1)
        self.assertEqual(service.inizializza_checklist(audit), 0)
        esito = audit.esiti.get()
        self.assertEqual(esito.testo, "Il campione segue il criterio?")
        self.assertTrue(esito.strutturato)

    def test_modello_non_attivo_non_entra_nel_piano(self):
        self.domanda(attiva=False)
        audit = self.make_audit(processi_snapshot=[self.processo.snapshot()])
        self.assertEqual(service.inizializza_checklist(audit), 0)

    def test_aggiornamento_piano_preserva_bozze_gia_salvate(self):
        domanda = self.domanda()
        audit = self.make_audit(processi_snapshot=[self.processo.snapshot()])
        automation.genera_checklist_processi(audit)
        esito = audit.esiti.get()
        esito.documento = "Documento gia raccolto"
        esito.versione = 1
        esito.save()
        domanda.domanda = "Nuova domanda"
        domanda.save()
        audit.processi_snapshot = [self.processo.snapshot()]
        automation.genera_checklist_processi(audit)
        esito.refresh_from_db()
        self.assertEqual(esito.testo, "Il campione segue il criterio?")
        audit.processi_snapshot = []
        automation.genera_checklist_processi(audit)
        self.assertTrue(audit.esiti.filter(pk=esito.pk).exists())

    def test_aggiornamento_piano_riallinea_solo_domande_intatte(self):
        domanda = self.domanda()
        audit = self.make_audit(processi_snapshot=[self.processo.snapshot()])
        automation.genera_checklist_processi(audit)
        domanda.domanda = "Nuova domanda"
        domanda.save()
        audit.processi_snapshot = [self.processo.snapshot()]
        automation.genera_checklist_processi(audit)
        self.assertEqual(audit.esiti.get().testo, "Nuova domanda")
        audit.processi_snapshot = []
        automation.genera_checklist_processi(audit)
        self.assertFalse(audit.esiti.exists())

    def test_completamento_richiede_campione_documento_data(self):
        esito = self.esito(esito="CONFORME", evidenze="Conforme")
        self.assertGreaterEqual(len(automation.problemi_esito(esito)), 4)
        esito.esito = "NA"
        self.assertEqual(automation.problemi_esito(esito), [])
        esito.evidenze = ""
        self.assertTrue(automation.problemi_esito(esito))

    def test_form_impedisce_date_future_e_versione_obsoleta(self):
        esito = self.esito(versione=2)
        form = AuditEsitoForm(self.dati_esito(versione=1), instance=esito)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())
        form = AuditEsitoForm(self.dati_esito(versione=2, data_verifica=(timezone.localdate()+timedelta(days=1)).isoformat()), instance=esito)
        self.assertFalse(form.is_valid())
        self.assertIn("data_verifica", form.errors)

    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    def test_autosalvataggio_optimistic_lock_non_emette_ofi(self, _executor):
        esito = self.esito()
        dati = self.dati_esito(esito="NC", requisito_atteso="Criterio", scostamento="Scarto", responsabile_azione=self.direzione.pk,
                               scadenza_azione=(timezone.localdate()+timedelta(days=7)).isoformat())
        response = views.esito_bozza(_request(self.user, data=dati), esito.audit_id, esito.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["versione"], 1)
        esito.refresh_from_db()
        self.assertIsNone(esito.ofi_id)
        self.assertEqual(esito.esito, "NC")
        response = views.esito_bozza(_request(self.user, data=dict(dati, evidenze="Scrittura obsoleta")), esito.audit_id, esito.pk)
        self.assertEqual(response.status_code, 409)
        esito.refresh_from_db()
        self.assertNotEqual(esito.evidenze, "Scrittura obsoleta")
        service.salva_esito(esito, utente=self.user)
        esito.refresh_from_db()
        self.assertIsNotNone(esito.ofi_id)
        self.assertEqual(esito.ofi.proprietario, self.direzione.get_username())
        self.assertIn("Requisito atteso: Criterio", esito.ofi.opportunita)
        self.assertEqual(esito.ofi.data_richiesta, esito.scadenza_azione)
        service.salva_esito(esito, utente=self.user)
        self.assertEqual(esito.audit.esiti.filter(ofi__isnull=False).count(), 1)

    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    def test_bozza_incompleta_salvabile_ma_non_firmabile(self, _executor):
        esito = self.esito()
        response = views.esito_bozza(_request(self.user, data={"versione":0,"esito":"NC","evidenze":"Primi appunti"}), esito.audit_id, esito.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)["mancanti"])
        self.assertTrue(service.verifica_completezza(esito.audit)["rapporto"])

    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    def test_autosave_bloccato_dopo_firma(self, _executor):
        esito = self.esito()
        Audit.objects.filter(pk=esito.audit_id).update(rapporto_firmato_auditor_il=timezone.now())
        response = views.esito_bozza(_request(self.user, data=self.dati_esito()), esito.audit_id, esito.pk)
        self.assertEqual(response.status_code, 409)
        esito.refresh_from_db()
        self.assertEqual(esito.versione, 0)

    def test_autosave_anonimo_401(self):
        response = views.esito_bozza(_request(AnonymousUser()), 1, 1)
        self.assertEqual(response.status_code, 401)

    @patch("sistema_gestione.automation_views._assigned_executor", return_value=False)
    def test_autosave_non_assegnato_403(self, _executor):
        esito = self.esito()
        self.assertEqual(views.esito_bozza(_request(self.direzione), esito.audit_id, esito.pk).status_code, 403)

    def test_allegato_rifiuta_html_mascherato_e_vuoto(self):
        for contenuto in [b"<html>fake</html>", b""]:
            form = AllegatoEvidenzaForm(files={"file":SimpleUploadedFile("falso.pdf", contenuto, content_type="application/pdf")})
            self.assertFalse(form.is_valid())

    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    def test_upload_privato_cifrato_deduplicato_e_download(self, _perm, _executor):
        esito = self.esito()
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR/".tmp_tests") as root, override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            storage = PrivateSistemaGestioneStorage()
            storage._location = root
            with patch.object(AuditAllegato._meta.get_field("file"), "storage", storage):
                for _ in range(2):
                    request = _request(self.user, data={"file":SimpleUploadedFile("prova.pdf", b"%PDF-1.4\nfixture sintetica", content_type="application/pdf")})
                    self.assertEqual(views.allegato_carica(request, esito.audit_id, esito.pk).status_code,302)
                self.assertEqual(esito.allegati.count(),1)
                allegato = esito.allegati.get()
                self.assertTrue(Path(allegato.file.path).read_bytes().startswith(b"NCENC1"))
                response = views.allegato_download(_request(self.user, method="get"), esito.audit_id, allegato.pk)
                self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-1.4"))
                self.assertEqual(response["X-Content-Type-Options"],"nosniff")
                response.file_to_stream.close()
                with self.assertRaises(Http404):
                    views.allegato_download(_request(self.user,method="get"),999,allegato.pk)

    def test_riepilogo_non_inventa_giudizio(self):
        esito = self.esito(esito="NA", evidenze="Escluso dal campo per motivazione sintetica")
        audit = esito.audit
        audit.giudizio="Giudizio umano"
        audit.save()
        testo = automation.riepilogo_rapporto(audit)
        self.assertIn("Escluso dal campo",testo)
        self.assertIn("N/A: 1",testo)
        audit.refresh_from_db()
        self.assertEqual(audit.giudizio,"Giudizio umano")

    def test_priorita_spiegabile_ordinata_e_query_limitate(self):
        self.processo.criticita=3
        self.processo.save()
        Processo.objects.create(codice="LOW",nome="Processo secondario",criticita=1)
        with self.assertNumQueries(3):
            righe=automation.priorita_processi(Processo.objects.all())
        self.assertEqual(righe[0]["processo"],self.processo)
        self.assertEqual(righe[0]["punteggio"],60)
        self.assertTrue(any("Nessun audit" in m for m in righe[0]["motivi"]))

    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    def test_proposte_programma_idempotenti_e_bozza_obbligatoria(self,_perm):
        programma=ProgrammaAudit.objects.create(anno=timezone.localdate().year)
        dati={"programma":programma.pk,"processi":[self.processo.pk]}
        for _ in range(2):
            views.applica_priorita(_request(self.user,data=dati))
        self.assertEqual(programma.righe.count(),1)
        self.assertEqual(programma.righe.get().celle.count(),1)
        programma.stato=ProgrammaAudit.STATO_APPROVATO
        programma.save()
        with self.assertRaises(Http404):
            views.applica_priorita(_request(self.user,data=dati))

    def test_efficacia_negativa_richiede_riverifica(self):
        form=VerificaEfficaciaForm({"risultato":"NON_EFFICACE","metodo":"Campionamento", "evidenza":"Problema ripetuto", "data_verifica":timezone.localdate()})
        self.assertFalse(form.is_valid())
        self.assertIn("prossima_verifica",form.errors)

    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    def test_efficacia_storico_separato_da_chiusura_ofi(self,_executor,_perm):
        esito=self.esito(esito="NC",evidenze="Scostamento sintetico",strutturato=False)
        service.sincronizza_ofi(esito)
        esito.refresh_from_db()
        dati={"risultato":"EFFICACE","metodo":"Ricontrollo campione","evidenza":"Esito positivo su campione successivo", "data_verifica":timezone.localdate()}
        self.assertEqual(views.verifica_efficacia(_request(self.user,data=dati),esito.audit_id,esito.pk).status_code,302)
        self.assertEqual(esito.verifiche_efficacia.count(),1)
        esito.ofi.refresh_from_db()
        self.assertFalse(esito.ofi.is_chiuso)
        self.assertEqual(automation.stato_efficacia(esito),"Efficace")

    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    @patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
    def test_editor_e_priorita_renderizzano(self,_executor,_perm):
        esito=self.esito()
        self.assertContains(views.esito_editor(_request(self.user,method="get"),esito.audit_id,esito.pk),"data-audit-autosave")
        self.assertContains(views.priorita(_request(self.user,method="get")),"priorita-v1")

    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    def test_revisione_archivia_pdf_e_azzera_firme(self,_perm):
        audit=self.make_audit(stato=Audit.STATO_CHIUSO,giudizio="Conclusione originale",rapporto_firmato_auditor_il=timezone.now(),rapporto_firmato_auditor_da=self.user,rapporto_convalidato_ente_il=timezone.now(),rapporto_valutato_rdd_il=timezone.now())
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR/".tmp_tests") as root:
            storage=PrivateSistemaGestioneStorage()
            storage._location=root
            with patch.object(AuditRapportoVersione._meta.get_field("pdf"),"storage",storage):
                self.assertEqual(views.revisiona_rapporto(_request(self.direzione,data={"motivo":"Nuove evidenze"}),audit.pk).status_code,302)
                versione=audit.versioni_rapporto.get()
                with versione.pdf.open("rb") as file:
                    with fitz.open(stream=file.read(),filetype="pdf") as doc:
                        self.assertIn("Conclusione originale","".join(p.get_text() for p in doc))
                audit.refresh_from_db()
                self.assertEqual(audit.stato,Audit.STATO_IN_CORSO)
                self.assertIsNone(audit.rapporto_firmato_auditor_il)
                self.assertIsNone(audit.rapporto_convalidato_ente_il)
                self.assertIsNone(audit.rapporto_valutato_rdd_il)

    def test_pdf_include_verifiche_di_processo(self):
        esito=self.esito(esito="CONFORME",evidenze="Esito campione",documento="DOCUMENTO-SINTETICO",campione="CAMPIONE-123")
        with fitz.open(stream=rapporto_audit_pdf(esito.audit),filetype="pdf") as doc:
            testo="".join(p.get_text() for p in doc)
        self.assertIn("CAMPIONE-123",testo)
        self.assertIn("DOCUMENTO-SINTETICO",testo)

    def test_pdf_evidenza_lunga_si_impagina_senza_tagli(self):
        esito=self.esito(esito="CONFORME",evidenze="Campione verificato con risultato conforme. "*250,documento="DOCUMENTO-LUNGO",campione="CAMPIONE-999")
        with fitz.open(stream=rapporto_audit_pdf(esito.audit),filetype="pdf") as doc:
            testo="".join(p.get_text() for p in doc)
        self.assertIn("CAMPIONE-999",testo)
        self.assertEqual(testo.count("risultato"),250)
