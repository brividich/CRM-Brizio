from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch
import fitz
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import HttpResponseForbidden
from django.utils import timezone
from gestione_specifiche.models import RegistroOFI
from gestione_specifiche.forms import RegistroOFIForm
from .tests_audit import AuditBase, _request
from .models import Audit, AuditPreparazione, AzioneCorrettivaAudit, RilevazioneKpi, ProgrammaAudit, RigaProgramma, CellaProgramma, Auditor, Processo
from .services import procedure, audit as service
from .procedure_forms import KpiForm, CarForm
from . import procedure_views as views
from .audit_views import audit_avvia
from .acl_bootstrap import PERM_AUDIT_VIEW, PERM_AUDIT_EDIT, PERM_AUDIT_APPROVA, _ROUTE_BINDINGS


class ProcedureTests(AuditBase):
    def registro(self):
        return RegistroOFI.objects.create(numero=1, data_apertura=date(2026,1,31), tipo="NC")

    def car(self, **extra):
        dati = dict(registro=self.registro(),data_richiesta=date(2026,1,31),responsabile=self.user)
        dati.update(extra)
        return AzioneCorrettivaAudit.objects.create(**dati)

    def kpi_dati(self, **extra):
        dati = dict(processo=self.processo.pk,codice="QA",periodo_da="2026-01-01",periodo_a="2026-01-31",formula="PERCENTUALE",numeratore="3",denominatore="100",fonte_filtri="Fonte sintetica; data emissione; esclusi annullati",target="5",verso="MAX",confrontabile=True,commento="Campione sintetico",riferimento_riesame="VRS TEST")
        dati.update(extra)
        return dati

    def test_copertura_esige_mesi_e_ignora_annullati(self):
        programma=ProgrammaAudit.objects.create(anno=2026)
        riga=RigaProgramma.objects.create(programma=programma,processo=self.processo,area="QA")
        with self.assertRaises(service.TransizioneNonAmmessa):
            service.proponi_programma(programma,utente=self.user)
        c=CellaProgramma.objects.create(riga=riga,mese=10)
        procedure.verifica_copertura(programma)
        c.audit=self.make_audit(stato=Audit.STATO_ANNULLATO);c.save()
        with self.assertRaises(ValidationError): procedure.verifica_copertura(programma)

    def test_audit_altro_anno_non_copre_programma(self):
        programma=ProgrammaAudit.objects.create(anno=2025)
        riga=RigaProgramma.objects.create(programma=programma,processo=self.processo,area="QA")
        CellaProgramma.objects.create(riga=riga,mese=10,audit=self.make_audit())
        self.assertFalse(procedure.copertura_annuale(programma)[0]["pianificato"])

    def test_esecuzione_distinta_da_pianificazione(self):
        programma=ProgrammaAudit.objects.create(anno=2026)
        a=self.make_audit(stato=Audit.STATO_CHIUSO);a.processi_catalogo.add(self.processo)
        r=procedure.copertura_annuale(programma)[0]
        self.assertTrue(r["eseguito"]);self.assertFalse(r["pianificato"])

    def test_approvazione_riverifica_catalogo(self):
        programma=ProgrammaAudit.objects.create(anno=2026,stato=ProgrammaAudit.STATO_PROPOSTA)
        with self.assertRaises(service.TransizioneNonAmmessa): service.approva_programma(programma,utente=self.direzione)

    def test_team_interno_singolo_non_approvabile(self):
        self.assertTrue(any("affianca" in r["testo"] for r in service.verifica_completezza(self.make_audit())["piano"]))

    def test_deroga_non_supera_indipendenza(self):
        a=self.make_audit(imparzialita_deroga_motivo="Nota preesistente")
        self.processo.responsabile=self.user;self.processo.save();a.processi_catalogo.add(self.processo)
        self.assertTrue(any("indipendenza" in r["testo"] for r in service.verifica_completezza(a)["piano"]))

    def test_esterno_richiede_formazione_processi(self):
        a=self.auditor;a.interno=False;a.approvato_ceo_da=self.direzione;a.approvato_ceo_il=timezone.now()
        self.assertFalse(a.qualificato)
        a.formazione_processi_il=timezone.localdate();self.assertTrue(a.qualificato)

    @patch("sistema_gestione.audit_views._has_perm",return_value=True)
    def test_avvio_senza_preparazione_bloccato(self,_perm):
        a=self.make_audit(stato=Audit.STATO_PIANO_APPROVATO, comunicazione_il=timezone.now())
        audit_avvia(_request(self.user),a.pk);a.refresh_from_db()
        self.assertEqual(a.stato,Audit.STATO_PIANO_APPROVATO)

    def test_preparazione_va_riconfermata_dopo_approvazione(self):
        a=self.make_audit()
        AuditPreparazione.objects.create(audit=a,verificato_da=self.user,audit_precedenti="Nessuno",car_cliente="Nessuna",documenti_registrazioni="PR-QA",obiettivi_carenze="Campione")
        a.piano_approvato_direzione_il=timezone.now()+timedelta(seconds=1)
        self.assertTrue(procedure.problemi_preparazione(a))

    def test_car_scadenze_mesi_non_novanta_giorni(self):
        c=self.car()
        self.assertEqual(c.scadenza_analisi,date(2026,2,28));self.assertEqual(c.scadenza_chiusura,date(2026,4,30))

    def test_car_analisi_futura_e_versione_obsoleta(self):
        c=self.car(versione=2)
        form=CarForm({"versione":1,"responsabile":self.user.pk,"analizzata_il":"2099-01-01"},instance=c)
        self.assertFalse(form.is_valid());self.assertIn("analizzata_il",form.errors)

    def test_car_indipendenza_e_approvazione_obbligatorie(self):
        c=self.car(causa="Causa",contenimento="Contenimento",azione="Azione",analizzata_il=date(2026,2,15),evidenza_attuazione="Prova",evidenza_efficacia="Ricontrollo")
        self.assertGreaterEqual(len(procedure.problemi_chiusura_car(c,self.user)),2)
        c.approvata_il=timezone.now()
        self.assertFalse(procedure.problemi_chiusura_car(c,self.direzione))

    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_car_chiusura_aggiorna_registro_e_blocca_modifiche(self,_perm):
        c=self.car(causa="Causa",contenimento="Contenimento",azione="Azione",analizzata_il=date(2026,2,15),evidenza_attuazione="Prova",evidenza_efficacia="Ricontrollo",approvata_il=timezone.now())
        views.car(_request(self.direzione,data={"azione":"chiudi","versione":"0"}),c.registro_id)
        c.refresh_from_db();c.registro.refresh_from_db()
        self.assertEqual(c.chiusa_da,self.direzione);self.assertTrue(c.registro.is_chiuso)

    @patch("sistema_gestione.procedure_views._has_perm",side_effect=lambda req,code:code!=PERM_AUDIT_APPROVA)
    @patch("sistema_gestione.procedure_views._nega",return_value=HttpResponseForbidden())
    def test_proroga_non_approvatore_negata(self,_nega,_perm):
        c=self.car();response=views.car(_request(self.user,data={"azione":"proroga","versione":"0","proroga_al":"2027-01-01","motivo":"Motivo"}),c.registro_id)
        self.assertEqual(response.status_code,403);c.refresh_from_db();self.assertIsNone(c.proroga_al)

    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_proroga_approvata_allinea_registro(self,_perm):
        c=self.car();views.car(_request(self.direzione,data={"azione":"proroga","versione":"0","proroga_al":"2027-01-01","motivo":"Fornitura ripianificata"}),c.registro_id)
        c.refresh_from_db();c.registro.refresh_from_db()
        self.assertEqual(c.proroga_da,self.direzione);self.assertEqual(c.registro.data_richiesta,date(2027,1,1))

    def test_registro_non_aggira_chiusura_car(self):
        c=self.car();form=RegistroOFIForm({"data_apertura":"2026-01-31","tipo":"NC","fase":"CHIUSO","priorita":"MEDIA"},instance=c.registro)
        self.assertFalse(form.is_valid());self.assertIn("CAR",str(form.errors))

    def test_kpi_percentuale_e_delta(self):
        form=KpiForm(self.kpi_dati(valore_precedente="4"));self.assertTrue(form.is_valid(),form.errors)
        r=procedure.risultato_kpi(form.save(commit=False));self.assertEqual(r["valore"],Decimal(3));self.assertEqual(r["delta"],Decimal(-1))

    def test_kpi_denominatore_zero_non_conformita_fittizia(self):
        form=KpiForm(self.kpi_dati(denominatore="0"));self.assertFalse(form.is_valid())

    def test_kpi_non_confrontabile_richiede_motivo(self):
        form=KpiForm(self.kpi_dati(confrontabile=False));self.assertFalse(form.is_valid())

    def test_vendor_rating_soglie(self):
        for puntuali,nonconformi,atteso,classe in [(100,0,"1","Regolare"),(0,0,"0.7","Monitoraggio"),(0,1,"0.693","Attenzione")]:
            form=KpiForm(self.kpi_dati(formula="VENDOR",numeratore=str(puntuali),pezzi_nc=str(nonconformi),pezzi_totali="100",target="0.8",verso="MIN"))
            self.assertTrue(form.is_valid(),form.errors)
            r=procedure.risultato_kpi(form.save(commit=False));self.assertEqual(r["valore"],Decimal(atteso));self.assertEqual(r["classe"],classe)

    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_render_e_registrazione_kpi(self,_perm):
        self.assertContains(views.kpi(_request(self.user,method="get")),"Indicatori di processo")
        views.kpi(_request(self.user,data=self.kpi_dati()))
        self.assertEqual(RilevazioneKpi.objects.count(),1)
        self.assertEqual(RegistroOFI.objects.count(),0)
        self.assertContains(views.kpi(_request(self.user,method="get")),"3,0000")

    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_render_car_e_preparazione(self,_perm):
        c=self.car();a=self.make_audit()
        self.assertContains(views.car(_request(self.direzione,method="get"),c.registro_id),"Scadenze")
        self.assertContains(views.preparazione(_request(self.user,method="get"),a.pk),"Preparazione")

    def test_binding_route_procedurali(self):
        for name in ["procedura_car","procedura_preparazione","procedura_kpi"]:
            self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:"+name],PERM_AUDIT_VIEW)

    def test_import_turtle_inattivo_idempotente(self):
        root=settings.BASE_DIR/".tmp_tests";root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            path=Path(tmp)/"MOD.999 - TDX - Processo sintetico - Rev.1.pdf"
            with fitz.open() as pdf:
                pagina=pdf.new_page();pagina.insert_text((30,30),"CON COSA - RESOURCES\nRisorsa sintetica\nINPUT\nOrdine campione\nCOME - METHODS\nPR-QA Rev.1\nOUTPUT\nRisultato verificato\nCON CHI - RESOURCES\nFunzione QA\nPERFORMANCE INDICATOR\nKPI QA")
                pdf.save(path)
            call_command("importa_turtle_processi",tmp,stdout=StringIO())
            self.assertFalse(Processo.objects.filter(codice="TDX").exists())
            for _ in range(2):call_command("importa_turtle_processi",tmp,apply=True,stdout=StringIO())
            p=Processo.objects.get(codice="TDX");self.assertFalse(p.attivo);self.assertIsNone(p.responsabile_id);self.assertEqual(p.input,"Ordine campione");self.assertIn("SHA-256",p.fonte_documentale)


    def test_programma_copre_riferimenti_del_catalogo(self):
        self.processo.punti_9100="8.1; 8.4";self.processo.save()
        programma=ProgrammaAudit.objects.create(anno=2026)
        r=RigaProgramma.objects.create(programma=programma,processo=self.processo,area="QA",punti_9100="8.1")
        CellaProgramma.objects.create(riga=r,mese=10)
        self.assertIn("9100: 8.4",procedure.copertura_annuale(programma)[0]["scoperti"])
        r.punti_9100="8.1; 8.4";r.save();procedure.verifica_copertura(programma)

    def test_pdf_conserva_preparazione(self):
        from .audit_exports import rapporto_audit_pdf
        a=self.make_audit()
        AuditPreparazione.objects.create(audit=a,verificato_da=self.user,audit_precedenti="AUDIT-STORICO-QA",car_cliente="Nessuna",documenti_registrazioni="PR-QA",obiettivi_carenze="Campione")
        with fitz.open(stream=rapporto_audit_pdf(a),filetype="pdf") as pdf:
            self.assertIn("AUDIT-STORICO-QA","".join(p.get_text() for p in pdf))


    @patch("sistema_gestione.services.audit.timezone.localdate",return_value=date(2026,10,14))
    def test_preavviso_non_superabile_con_nota(self,_oggi):
        a=self.make_audit()
        with self.assertRaises(ValidationError):service.comunica_audit(a,metodo=Audit.COM_EMAIL,deroga_motivo="Nota")

    @patch("sistema_gestione.procedure_views._has_perm",return_value=False)
    @patch("sistema_gestione.procedure_views._nega",return_value=HttpResponseForbidden())
    def test_accesso_procedure_negato(self,_nega,_perm):
        self.assertEqual(views.kpi(_request(self.user,method="get")).status_code,403)
        self.assertEqual(views.car(_request(self.user,method="get"),1).status_code,403)

    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_chiusura_car_aggiorna_efficacia_audit(self,_perm):
        from .models import AuditEsito
        c=self.car(causa="Causa",contenimento="Contenimento",azione="Azione",analizzata_il=date(2026,2,15),evidenza_attuazione="Prova",evidenza_efficacia="Ricontrollo",approvata_il=timezone.now())
        e=AuditEsito.objects.create(audit=self.make_audit(),ofi=c.registro,esito="NC",testo_aggiuntivo="QA")
        views.car(_request(self.direzione,data={"azione":"chiudi","versione":"0"}),c.registro_id)
        self.assertEqual(e.verifiche_efficacia.get().risultato,"EFFICACE")


    @patch("sistema_gestione.procedure_views._has_perm",return_value=True)
    def test_approvazione_car_obsoleta_non_consentita(self,_perm):
        c=self.car(versione=3,causa="Causa",contenimento="Contenimento",azione="Azione",analizzata_il=date(2026,2,15))
        views.car(_request(self.direzione,data={"azione":"approva","versione":"2"}),c.registro_id)
        c.refresh_from_db();self.assertIsNone(c.approvata_il)
