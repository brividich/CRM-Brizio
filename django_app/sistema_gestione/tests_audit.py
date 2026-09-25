from __future__ import annotations

import io
from datetime import date, timedelta

import fitz
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.fields.files import FieldFile
from django.http import HttpResponseForbidden
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from report_conformita.registry import ReportParams, get_report

from .acl_bootstrap import (
    PERM_AUDIT_APPROVA,
    PERM_AUDIT_EDIT,
    PERM_AUDIT_ESEGUI,
    PERM_AUDIT_VIEW,
    _ROUTE_BINDINGS,
)
from .audit_exports import piano_audit_pdf, programma_pdf, rapporto_audit_pdf
from .audit_forms import AuditForm
from .models import (
    Audit,
    AuditEsito,
    AuditPersona,
    AuditSezioneCar,
    Auditor,
    CellaProgramma,
    ChecklistDomanda,
    ChecklistModello,
    ChecklistSezione,
    ProgrammaAudit,
    RigaProgramma,
)
from .services import audit as service
from .services.mod035b_import import leggi_folder_b

User = get_user_model()


def _request(user, *, method="post", path="/", data=None):
    factory = RequestFactory()
    request = getattr(factory, method)(path, data=data or {})
    request.user = user
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)
    return request


def _pdf_folder_b() -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4)
    data = [["§", "Requisito / Domande guida", "Evidenze", "Rilievo"],
            ["§4 – CONTESTO Criteri: PROC.01", "", "", ""]]
    for n in range(1, 6):
        data.append([f"4.{n}", f"Domanda sintetica {n}", "", "☐ Conforme"])
    data.append(["CAR (MOD.036) aperta – §4", "", "", ""])
    table = Table(data, colWidths=[50, 260, 120, 80])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("SPAN", (0, 1), (-1, 1)), ("SPAN", (0, -1), (-1, -1)),
    ]))
    doc.build([table])
    return out.getvalue()


class AuditBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="auditor-test", password="x", first_name="Ada", last_name="Verdi")
        self.direzione = User.objects.create_user(username="direzione-test", password="x")
        self.auditor = Auditor.objects.create(
            user=self.user, interno=True, req_diploma=True, req_norme=True,
            req_tecniche_audit=True, req_settore=True, req_esperienza_2_anni=True,
            requisiti_verificati_il=date(2026, 1, 10), audit_svolti_pregressi=4,
        )

    def make_audit(self, **kwargs):
        dati = {
            "numero": "RAIS-2026-01", "lead_auditor": self.auditor,
            "processi": "Qualità", "punti_norma": "9.2", "data_inizio": date(2026, 10, 15),
            "data_fine": date(2026, 10, 15), "created_by": self.direzione,
        }
        dati.update(kwargs)
        return Audit.objects.create(**dati)

    def make_checklist(self):
        modello = ChecklistModello.objects.create(
            codice=ChecklistModello.CODICE_EN9100_FOLDER_B, norma="UNI EN 9100:2018",
            revisione=0, titolo="Sintetica",
        )
        sezione = ChecklistSezione.objects.create(
            modello=modello, codice="§4", titolo="Contesto", criteri="PROC.01", ordine=10,
        )
        domanda = ChecklistDomanda.objects.create(
            sezione=sezione, punti="4.1", testo="Domanda sintetica", ordine=10,
        )
        return modello, sezione, domanda


class ModelliAuditTest(AuditBase):
    def test_auditor_qualificato_con_requisiti_e_quattro_audit(self):
        self.assertTrue(self.auditor.qualificato)
        self.assertEqual(self.auditor.audit_svolti, 4)

    def test_cella_unica_per_riga_e_mese(self):
        programma = ProgrammaAudit.objects.create(anno=2026)
        riga = RigaProgramma.objects.create(programma=programma, area="Supporto")
        CellaProgramma.objects.create(riga=riga, mese=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CellaProgramma.objects.create(riga=riga, mese=5)

    def test_nuova_revisione_copia_righe_e_celle(self):
        programma = ProgrammaAudit.objects.create(anno=2026, stato=ProgrammaAudit.STATO_APPROVATO)
        riga = RigaProgramma.objects.create(programma=programma, ordine=10, area="Supporto", punti_9100="7")
        CellaProgramma.objects.create(riga=riga, mese=5, stato=CellaProgramma.STATO_RP)
        nuova = service.nuova_revisione_programma(programma, motivo="Data non rispettata", utente=self.user)
        self.assertEqual(nuova.revisione, 1)
        self.assertEqual(nuova.righe.get().area, "Supporto")
        self.assertEqual(nuova.righe.get().celle.get().stato, CellaProgramma.STATO_RP)

    def test_esiti_aggiuntivi_multipli_e_domanda_modello_unica(self):
        audit = self.make_audit()
        _modello, sezione, domanda = self.make_checklist()
        AuditEsito.objects.create(audit=audit, sezione=sezione, testo_aggiuntivo="Controllo sintetico A")
        AuditEsito.objects.create(audit=audit, sezione=sezione, testo_aggiuntivo="Controllo sintetico B")
        self.assertEqual(audit.esiti.filter(domanda__isnull=True).count(), 2)
        AuditEsito.objects.create(audit=audit, domanda=domanda)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditEsito.objects.create(audit=audit, domanda=domanda)

    def test_inizializza_checklist_resta_idempotente(self):
        audit = self.make_audit()
        self.make_checklist()
        self.assertEqual(service.inizializza_checklist(audit), 1)
        self.assertEqual(service.inizializza_checklist(audit), 0)
        self.assertEqual(audit.esiti.count(), 1)


class RegoleAuditTest(AuditBase):
    def test_preavviso_esclude_weekend_e_festivo(self):
        # 1 maggio 2026 è venerdì festivo: fra 23/4 e 4/5 restano 5 giorni lavorativi.
        self.assertEqual(service.giorni_lavorativi_di_preavviso(date(2026, 4, 23), date(2026, 5, 4)), 5)

    @patch("sistema_gestione.services.audit.reparto_auditor", return_value="Qualità")
    def test_imparzialita_blocca_senza_deroga(self, _reparto):
        form = AuditForm(data={
            "numero": "RAIS-2026-02", "tipo": Audit.TIPO_SISTEMA, "en9100": "on",
            "lead_auditor": self.auditor.pk, "processi": "Qualità",
            "data_inizio": "2026-10-15", "esclusioni": "Nessuna",
            "metodo_intervista": "on", "metodo_esame_documenti": "on", "metodo_verifica_evidenze": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("imparzialita_deroga_motivo", form.errors)

    @patch("sistema_gestione.services.audit.reparto_auditor", return_value="Qualità")
    def test_imparzialita_accetta_deroga_motivata(self, _reparto):
        form = AuditForm(data={
            "numero": "RAIS-2026-02", "tipo": Audit.TIPO_SISTEMA, "en9100": "on",
            "lead_auditor": self.auditor.pk, "processi": "Qualità",
            "data_inizio": "2026-10-15", "esclusioni": "Nessuna",
            "imparzialita_deroga_motivo": "Nessun altro auditor disponibile; riesame indipendente delle evidenze.",
        })
        self.assertTrue(form.is_valid(), form.errors)

    @patch("sistema_gestione.services.audit.reparto_auditor", return_value="Magazzino")
    def test_processi_vuoto_e_errore_del_campo_non_di_imparzialita(self, _reparto):
        form = AuditForm(data={
            "tipo": Audit.TIPO_SISTEMA, "en9100": "on", "lead_auditor": self.auditor.pk,
            "processi": "", "data_inizio": "2026-10-15", "esclusioni": "Nessuna",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("processi", form.errors)
        self.assertNotIn("imparzialita_deroga_motivo", form.errors)

    @patch("sistema_gestione.services.audit.reparto_auditor", return_value="IT")
    def test_imparzialita_non_usa_sottostringhe(self, _reparto):
        self.assertEqual(service.conflitti_imparzialita(
            processi="Gestione delle attivitÃ  di produzione", lead=self.auditor, auditor=[],
        ), [])

    @patch("sistema_gestione.services.audit.reparto_auditor", return_value="Magazzino")
    def test_imparzialita_riconosce_token_intero(self, _reparto):
        conflitti = service.conflitti_imparzialita(
            processi="Magazzino e spedizioni", lead=self.auditor, auditor=[],
        )
        self.assertEqual(len(conflitti), 1)

    def test_ofi_nc_crea_una_sola_voce_mod174(self):
        audit = self.make_audit()
        _modello, _sezione, domanda = self.make_checklist()
        esito = AuditEsito.objects.create(
            audit=audit, domanda=domanda, esito=AuditEsito.ESITO_NC,
            evidenze="Evidenza sintetica di mancata conformità.",
        )
        prima = service.sincronizza_ofi(esito)
        seconda = service.sincronizza_ofi(esito)
        self.assertEqual(prima.pk, seconda.pk)
        self.assertEqual(prima.tipo, "NC")
        self.assertTrue(prima.norma_en9100)
        self.assertEqual(prima.rif_norma, "4.1")
        self.assertEqual(prima.modulo_origine, "sistema_gestione")

    def test_numerazione_ofi_riprova_dopo_integrity_error(self):
        from gestione_specifiche.models import RegistroOFI

        audit = self.make_audit()
        _modello, _sezione, domanda = self.make_checklist()
        esito = AuditEsito.objects.create(
            audit=audit, domanda=domanda, esito=AuditEsito.ESITO_OFI,
            evidenze="Evidenza sintetica per il retry.",
        )
        create_reale = RegistroOFI.objects.create
        tentativi = []

        def create_instabile(*args, **kwargs):
            tentativi.append(kwargs.get("numero"))
            if len(tentativi) == 1:
                raise IntegrityError("collisione sintetica")
            return create_reale(*args, **kwargs)

        with patch.object(RegistroOFI.objects, "create", side_effect=create_instabile), patch(
            "sistema_gestione.services.audit._prossimo_numero_ofi", side_effect=[101, 102],
        ):
            voce = service.sincronizza_ofi(esito)
        self.assertEqual(tentativi, [101, 102])
        self.assertEqual(voce.numero, 102)


class WorkflowAuditTest(AuditBase):
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_firma_blocca_rapporto_esito_domanda_e_car(self, _perm):
        from sistema_gestione.audit_views import (
            audit_car_sezione,
            audit_domanda_aggiuntiva,
            audit_esito_salva,
            audit_rapporto_salva,
        )

        audit = self.make_audit(
            stato=Audit.STATO_RAPPORTO,
            giudizio="Giudizio originale",
            rapporto_firmato_auditor_da=self.user,
            rapporto_firmato_auditor_il=timezone.now(),
        )
        _modello, sezione, domanda = self.make_checklist()
        esito = AuditEsito.objects.create(
            audit=audit, domanda=domanda, esito=AuditEsito.ESITO_CONFORME, evidenze="Originale",
        )
        car = AuditSezioneCar.objects.create(audit=audit, sezione=sezione, car_aperta=False)

        audit_rapporto_salva(_request(self.user, data={"giudizio": "Alterato"}), audit.pk)
        audit_esito_salva(_request(self.user, data={"esito": "NC", "evidenze": "Alterata"}), audit.pk, esito.pk)
        audit_domanda_aggiuntiva(_request(self.user, data={
            "sezione": sezione.pk, "testo_aggiuntivo": "Nuova domanda",
        }), audit.pk)
        audit_car_sezione(_request(self.user, data={"car_aperta": "1"}), audit.pk, car.pk)

        audit.refresh_from_db()
        esito.refresh_from_db()
        car.refresh_from_db()
        self.assertEqual(audit.giudizio, "Giudizio originale")
        self.assertEqual(esito.esito, AuditEsito.ESITO_CONFORME)
        self.assertEqual(esito.evidenze, "Originale")
        self.assertFalse(car.car_aperta)
        self.assertEqual(audit.esiti.filter(domanda__isnull=True).count(), 0)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_riapertura_azzera_firma_e_riabilita_modifica(self, _perm):
        from sistema_gestione.audit_views import audit_rapporto_salva, audit_riapri_rapporto

        audit = self.make_audit(
            stato=Audit.STATO_RAPPORTO,
            giudizio="Prima",
            rapporto_firmato_auditor_da=self.user,
            rapporto_firmato_auditor_il=timezone.now(),
        )
        audit_riapri_rapporto(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.rapporto_firmato_auditor_da)
        self.assertIsNone(audit.rapporto_firmato_auditor_il)

        audit_rapporto_salva(_request(self.user, data={"giudizio": "Dopo riapertura"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.giudizio, "Dopo riapertura")

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_riapertura_negata_dopo_convalida_ente(self, _perm):
        from sistema_gestione.audit_views import audit_riapri_rapporto

        firmato_il = timezone.now()
        audit = self.make_audit(
            stato=Audit.STATO_RAPPORTO,
            rapporto_firmato_auditor_da=self.user,
            rapporto_firmato_auditor_il=firmato_il,
            rapporto_convalidato_ente_da=self.direzione,
            rapporto_convalidato_ente_il=timezone.now(),
        )
        audit_riapri_rapporto(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.rapporto_firmato_auditor_il, firmato_il)

    def test_responsabile_processo_con_view_puo_convalidare(self):
        from sistema_gestione.audit_views import audit_convalida_ente

        self.user.email = "responsabile@example.com"
        self.user.save(update_fields=["email"])
        audit = self.make_audit(
            stato=Audit.STATO_RAPPORTO,
            rapporto_firmato_auditor_da=self.user,
            rapporto_firmato_auditor_il=timezone.now(),
        )
        AuditPersona.objects.create(
            audit=audit, nome="Responsabile Sintetico", funzione_ente="Processo test",
            email="RESPONSABILE@example.com", ruolo=AuditPersona.RUOLO_PROCESSO,
        )
        with patch("sistema_gestione.audit_views._has_perm") as has_perm:
            has_perm.side_effect = lambda _request, code: code == PERM_AUDIT_VIEW
            response = audit_convalida_ente(_request(self.user), audit.pk)
        self.assertEqual(response.status_code, 302)
        audit.refresh_from_db()
        self.assertEqual(audit.rapporto_convalidato_ente_da, self.user)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_anno_non_numerico_ripiega_su_anno_corrente(self, _perm):
        from sistema_gestione.audit_views import audit_index

        response = audit_index(_request(self.user, method="get", data={"anno": "non-valido"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(timezone.localdate().year))

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views.service.comunica_audit")
    def test_comunicazione_negata_dopo_avvio(self, comunica, _perm):
        from sistema_gestione.audit_views import audit_comunica

        audit = self.make_audit(stato=Audit.STATO_IN_CORSO)
        response = audit_comunica(_request(self.user, data={"metodo": Audit.COM_EMAIL}), audit.pk)
        self.assertEqual(response.status_code, 302)
        comunica.assert_not_called()

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views.log_action")
    def test_download_copie_firmate_tracciati_e_nosniff(self, log_action, _perm):
        from sistema_gestione.audit_views import audit_copia_firmata, programma_copia_firmata

        programma = ProgrammaAudit.objects.create(anno=2026, copia_firmata="firmati/mod034.pdf")
        audit = self.make_audit(copia_firmata_rapporto="firmati/mod035b.pdf")
        with patch.object(FieldFile, "open", side_effect=[io.BytesIO(b"%PDF-programma"), io.BytesIO(b"%PDF-audit")]):
            response_programma = programma_copia_firmata(_request(self.user, method="get"), programma.pk)
            response_audit = audit_copia_firmata(_request(self.user, method="get"), audit.pk, "rapporto")
        self.assertEqual(response_programma["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response_audit["X-Content-Type-Options"], "nosniff")
        self.assertEqual(log_action.call_count, 2)


class ImportMod035BTest(TestCase):
    def test_parser_legge_sezione_e_domande_da_pdf_sintetico(self):
        sezioni = leggi_folder_b(_pdf_folder_b())
        self.assertEqual(len(sezioni), 1)
        self.assertEqual(sezioni[0].codice, "§4")
        self.assertEqual(len(sezioni[0].domande), 5)
        self.assertNotIn("Domanda sintetica", __import__("sistema_gestione.models", fromlist=["__doc__"]).__doc__ or "")


class AclAuditTest(AuditBase):
    def test_tutte_le_route_audit_hanno_binding_canonico(self):
        from sistema_gestione.urls import urlpatterns

        nomi = {
            f"sistema_gestione:{p.name}" for p in urlpatterns
            if p.name and (p.name.startswith("audit") or p.name.startswith("auditor") or p.name.startswith("programma"))
        }
        self.assertFalse(nomi - set(_ROUTE_BINDINGS), nomi - set(_ROUTE_BINDINGS))
        self.assertEqual(
            {PERM_AUDIT_VIEW, PERM_AUDIT_EDIT, PERM_AUDIT_ESEGUI, PERM_AUDIT_APPROVA}
            - set(_ROUTE_BINDINGS.values()), set(),
        )

    @patch("sistema_gestione.audit_views._has_perm")
    def test_esegui_senza_approva_puo_avviare_solo_audit_assegnato(self, has_perm):
        from sistema_gestione.audit_views import audit_avvia

        has_perm.side_effect = lambda _request, code: code in {PERM_AUDIT_VIEW, PERM_AUDIT_ESEGUI}
        audit = self.make_audit(stato=Audit.STATO_PIANO_APPROVATO)
        response = audit_avvia(_request(self.user), audit.pk)
        self.assertEqual(response.status_code, 302)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_IN_CORSO)

    @patch("sistema_gestione.audit_views._has_perm", return_value=False)
    def test_approvazione_negata_senza_permesso(self, _has_perm):
        from sistema_gestione.audit_views import audit_approva_direzione

        audit = self.make_audit()
        with patch("sistema_gestione.audit_views._deny", return_value=HttpResponseForbidden()):
            response = audit_approva_direzione(_request(self.direzione), audit.pk)
        self.assertEqual(response.status_code, 403)
        audit.refresh_from_db()
        self.assertIsNone(audit.piano_approvato_direzione_il)


class PdfReportViewAuditTest(AuditBase):
    def test_pdf_mod034_035a_035b(self):
        programma = ProgrammaAudit.objects.create(anno=2026, rif_riesame="MOD.062 sintetico")
        riga = RigaProgramma.objects.create(programma=programma, area="Supporto", punti_9100="7")
        CellaProgramma.objects.create(riga=riga, mese=5)
        audit = self.make_audit(programma=programma)
        audit.righe.add(riga)
        _modello, _sezione, domanda = self.make_checklist()
        AuditEsito.objects.create(audit=audit, domanda=domanda, esito=AuditEsito.ESITO_CONFORME)
        documenti = (
            programma_pdf(programma),
            piano_audit_pdf(audit),
            rapporto_audit_pdf(audit),
        )
        for contenuto in documenti:
            self.assertTrue(contenuto.startswith(b"%PDF"))
            with fitz.open(stream=contenuto, filetype="pdf") as documento:
                testo = "\n".join(pagina.get_text() for pagina in documento)
            self.assertNotIn("<br/>", testo)
        with fitz.open(stream=documenti[2], filetype="pdf") as rapporto:
            testo_rapporto = "\n".join(pagina.get_text() for pagina in rapporto)
        with fitz.open(stream=documenti[1], filetype="pdf") as piano:
            testo_piano = "\n".join(pagina.get_text() for pagina in piano)
        self.assertIn("Sistema SGI (RAIS)", testo_piano)
        self.assertIn("Mandatorio Cliente (RAI)", testo_piano)
        self.assertIn("Straordinario", testo_piano)
        self.assertIn("\u2612", testo_piano)
        self.assertIn("\u2612", testo_rapporto)
        self.assertNotIn("[X]", testo_rapporto)

    def test_report_audit_interni_su_db_vuoto(self):
        params = ReportParams(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), today=date(2026, 9, 25))
        result = get_report("audit-interni").build(params)
        self.assertTrue(result.kpis)
        self.assertEqual(result.rows, [])
        self.assertTrue(any("Nessun programma approvato" in nota for nota in result.notes))

    def test_report_conta_solo_revisione_approvata_e_mesi_del_periodo(self):
        rev0 = ProgrammaAudit.objects.create(anno=2026, stato=ProgrammaAudit.STATO_APPROVATO)
        riga0 = RigaProgramma.objects.create(programma=rev0, area="Processo sintetico")
        CellaProgramma.objects.create(riga=riga0, mese=2)
        CellaProgramma.objects.create(riga=riga0, mese=6)
        nuova = service.nuova_revisione_programma(rev0, motivo="Riprogrammazione sintetica", utente=self.user)
        rev0.stato = ProgrammaAudit.STATO_SUPERATO
        rev0.save(update_fields=["stato"])
        nuova.stato = ProgrammaAudit.STATO_APPROVATO
        nuova.save(update_fields=["stato"])
        bozza = ProgrammaAudit.objects.create(anno=2026, revisione=2, stato=ProgrammaAudit.STATO_BOZZA)
        riga_bozza = RigaProgramma.objects.create(programma=bozza, area="Bozza non vigente")
        CellaProgramma.objects.create(riga=riga_bozza, mese=6)

        params = ReportParams(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), today=date(2026, 9, 25))
        result = get_report("audit-interni").build(params)
        kpi = {voce.label: voce.value for voce in result.kpis}
        self.assertEqual(kpi["Verifiche programmate"], 2)

        params.date_from = date(2026, 5, 1)
        result_parziale = get_report("audit-interni").build(params)
        kpi_parziali = {voce.label: voce.value for voce in result_parziale.kpis}
        self.assertEqual(kpi_parziali["Verifiche programmate"], 1)

    def test_report_audit_interni_con_dati_sintetici(self):
        programma = ProgrammaAudit.objects.create(anno=2026, stato=ProgrammaAudit.STATO_APPROVATO)
        riga = RigaProgramma.objects.create(programma=programma, area="Produzione", punti_9100="8.5")
        audit = self.make_audit(programma=programma, stato=Audit.STATO_CHIUSO)
        audit.righe.add(riga)
        CellaProgramma.objects.create(riga=riga, mese=10, audit=audit)
        _modello, _sezione, domanda = self.make_checklist()
        AuditEsito.objects.create(
            audit=audit,
            domanda=domanda,
            esito=AuditEsito.ESITO_OFI,
            evidenze="Evidenza sintetica per il report.",
        )
        params = ReportParams(
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 31),
            today=date(2026, 12, 31),
        )
        result = get_report("audit-interni").build(params)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0][0], "RAIS-2026-01")
        self.assertEqual(result.rows[0][7:9], [1, 0])

    @patch("sistema_gestione.views._has_perm", return_value=True)
    def test_pagine_renderizzate_non_contengono_commenti_django(self, _perm):
        from sistema_gestione.views import index

        response = index(_request(self.user, method="get"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "{#")

    def test_dateinput_usa_formato_iso(self):
        form = AuditForm(instance=Audit(data_inizio=date(2026, 10, 15), lead_auditor=self.auditor))
        self.assertIn('value="2026-10-15"', str(form["data_inizio"]))
