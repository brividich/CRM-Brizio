from __future__ import annotations

import io
from datetime import date, timedelta

import fitz
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
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


def _request(user, *, method="post", path="/"):
    factory = RequestFactory()
    request = getattr(factory, method)(path)
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
        self.assertIn("[X]", testo_rapporto)

    def test_report_audit_interni_su_db_vuoto(self):
        params = ReportParams(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), today=date(2026, 9, 25))
        result = get_report("audit-interni").build(params)
        self.assertTrue(result.kpis)
        self.assertEqual(result.rows, [])

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
