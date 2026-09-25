from __future__ import annotations

import io
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .acl_bootstrap import PERM_SOA_APPROVA, PERM_SOA_EDIT, PERM_SOA_VIEW, PERM_VIEW, _bootstrap_canonical
from .forms import SoaVoceForm
from .models import ControlloIso27002, SoaRevisione, SoaVoce, ThreatIntelligence
from .services import soa
from .services.mod165_import import _intero, _separa_obblighi, leggi_control_matrix

User = get_user_model()


def _pdf_control_matrix() -> bytes:
    """PDF sintetico con la stessa disposizione della Control Matrix del MOD.165 (pagina non ruotata)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=1200, height=842)
    for x, testo in ((19, "ISO 27001:2022"), (133, "APPLIED?"), (206, "VULNERABILITY"),
                     (376, "References"), (523, "Justification for inclusion/exclusion"),
                     (906, "CONTROL OBJECTIVE")):
        page.insert_text((x, 125), testo, fontsize=8)
    righe = (
        (206, "5.1", "4", "1", "Procedura sintetica A", "Giustificazione sintetica. (Required by: Legislative, Customer)"),
        (260, "8.4", "0", "", "Non applicato sintetico", "EXCLUSION sintetica"),
    )
    for y, codice, livello, vuln, rif, giust in righe:
        page.insert_text((19, y), f"ISO 27002:2022 - {codice}", fontsize=8)
        page.insert_text((154, y), livello, fontsize=8)
        if vuln:
            page.insert_text((242, y), vuln, fontsize=8)
        page.insert_text((304, y), rif, fontsize=8)
        page.insert_text((532, y - 10), giust, fontsize=7)
        page.insert_text((700, y), "Old: 00.0.0", fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


class CatalogoTest(TestCase):
    def test_93_controlli_nei_quattro_temi(self):
        self.assertEqual(ControlloIso27002.objects.count(), 93)
        conteggi = {t: ControlloIso27002.objects.filter(tema=t).count() for t in ("ORG", "PER", "FIS", "TEC")}
        self.assertEqual(conteggi, {"ORG": 37, "PER": 8, "FIS": 14, "TEC": 34})
        self.assertEqual(soa.assicura_catalogo(), 0)


class CicloRevisioniTest(TestCase):
    def setUp(self):
        self.utente = User.objects.create_user(username="sg_ciso", password="x")

    def test_nuova_revisione_copia_la_precedente(self):
        r0 = soa.nuova_revisione(utente=self.utente, motivo="Prima emissione")
        self.assertEqual(r0.numero, 0)
        self.assertEqual(r0.voci.count(), 93)
        voce = r0.voci.get(controllo__codice="5.1")
        voce.livello, voce.giustificazione = 3, "Motivo sintetico"
        voce.save()
        with self.assertRaises(soa.TransizioneNonAmmessa):
            soa.nuova_revisione(utente=self.utente)
        soa.proponi(r0, utente=self.utente)
        soa.approva(r0, utente=self.utente)
        r1 = soa.nuova_revisione(utente=self.utente, motivo="Riesame annuale")
        copiata = r1.voci.get(controllo__codice="5.1")
        self.assertEqual((copiata.livello, copiata.giustificazione), (3, "Motivo sintetico"))

    def test_approvazione_supera_la_precedente(self):
        r0 = soa.nuova_revisione(utente=self.utente)
        with self.assertRaises(soa.TransizioneNonAmmessa):
            soa.approva(r0, utente=self.utente)
        soa.proponi(r0)
        soa.approva(r0, utente=self.utente)
        r1 = soa.nuova_revisione(utente=self.utente)
        soa.proponi(r1)
        soa.approva(r1, utente=self.utente)
        r0.refresh_from_db()
        self.assertEqual(r0.stato, SoaRevisione.STATO_SUPERATA)
        self.assertEqual(soa.revisione_in_vigore(), r1)

    def test_statistiche_e_differenze(self):
        r0 = soa.nuova_revisione(utente=self.utente)
        r0.voci.update(livello=4, giustificazione="ok")
        r0.voci.filter(controllo__codice="8.4").update(livello=0)
        r0.voci.filter(controllo__codice="5.13").update(
            livello=2, azione="Etichettatura sintetica", scadenza=timezone.localdate() - timedelta(days=1), livello_atteso=4,
        )
        s = soa.statistiche(r0)
        self.assertEqual((s.totale, s.esclusi, s.parziali, s.pieni), (93, 1, 1, 91))
        self.assertEqual((s.azioni_aperte, s.azioni_scadute), (1, 1))
        soa.proponi(r0)
        soa.approva(r0, utente=self.utente)
        r1 = soa.nuova_revisione(utente=self.utente)
        r1.voci.filter(controllo__codice="5.13").update(livello=4)
        diff = soa.differenze(r1, r0)
        self.assertEqual(list(diff.values()), [["livello"]])


class FormTest(TestCase):
    def test_esclusione_richiede_giustificazione_e_azione_la_scadenza(self):
        r0 = soa.nuova_revisione()
        voce = r0.voci.first()
        form = SoaVoceForm(data={"livello": 0, "vulnerabilita": 0, "azione": "Sintetica"}, instance=voce)
        self.assertFalse(form.is_valid())
        self.assertIn("giustificazione", form.errors)
        self.assertIn("scadenza", form.errors)


class ParserMod165Test(TestCase):
    def test_utilita(self):
        self.assertEqual(_intero("(0-4) 4"), 4)
        self.assertIsNone(_intero(""))
        testo, obblighi = _separa_obblighi("Motivo. (Required by: Normative, Best Practice)")
        self.assertEqual(testo, "Motivo.")
        self.assertTrue(obblighi["obbligo_normativo"] and obblighi["buona_pratica"])
        self.assertFalse(obblighi["obbligo_cliente"])

    def test_legge_pdf_sintetico(self):
        righe = {r.codice: r for r in leggi_control_matrix(_pdf_control_matrix())}
        self.assertEqual(set(righe), {"5.1", "8.4"})
        self.assertEqual((righe["5.1"].livello, righe["5.1"].vulnerabilita), (4, 1))
        self.assertEqual(righe["5.1"].riferimenti, "Procedura sintetica A")
        self.assertTrue(righe["5.1"].obblighi["obbligo_legislativo"])
        self.assertNotIn("Old:", righe["5.1"].giustificazione)
        self.assertEqual(righe["8.4"].livello, 0)

    def test_comando_import_dry_run_e_apply(self):
        cartella = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cartella, True)
        percorso = f"{cartella}/mod165_sintetico.pdf"
        with open(percorso, "wb") as fh:
            fh.write(_pdf_control_matrix())
        call_command("importa_soa_mod165", percorso, stdout=io.StringIO())
        self.assertFalse(SoaRevisione.objects.exists())
        call_command("importa_soa_mod165", percorso, "--numero", "3", "--apply", stdout=io.StringIO())
        revisione = SoaRevisione.objects.get(numero=3)
        self.assertEqual(revisione.stato, SoaRevisione.STATO_BOZZA)
        voce = revisione.voci.get(controllo__codice="8.4")
        self.assertEqual((voce.livello, voce.giustificazione), (0, "EXCLUSION sintetica"))


class AclBootstrapTest(TestCase):
    def test_permessi_binding_menu(self):
        from core.models import NavigationItem, PermissionDefinition, RoutePermissionBinding

        _bootstrap_canonical()
        _bootstrap_canonical()
        for code in (PERM_VIEW, PERM_SOA_VIEW, PERM_SOA_EDIT, PERM_SOA_APPROVA):
            self.assertTrue(PermissionDefinition.objects.filter(code=code).exists())
        self.assertEqual(
            RoutePermissionBinding.objects.get(route_name="sistema_gestione:soa_approva").permission_id, PERM_SOA_APPROVA,
        )
        self.assertEqual(RoutePermissionBinding.objects.filter(route_name="sistema_gestione:soa_voce").count(), 1)
        self.assertEqual(NavigationItem.objects.get(code="sistema-gestione").required_permission_code, PERM_VIEW)


class ViewsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="sg_admin", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_anonimo_al_login(self):
        self.client.logout()
        resp = self.client.get(reverse("sistema_gestione:index"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())

    def test_senza_permessi(self):
        utente = User.objects.create_user(username="sg_nessuno", password="x")
        self.client.force_login(utente)
        self.assertNotEqual(self.client.get(reverse("sistema_gestione:soa")).status_code, 200)

    def test_flusso_completo(self):
        self.assertEqual(self.client.get(reverse("sistema_gestione:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sistema_gestione:soa")).status_code, 200)
        self.client.post(reverse("sistema_gestione:soa_nuova_revisione"), {"motivo": "Prima emissione"})
        revisione = SoaRevisione.objects.get()
        pagina = self.client.get(reverse("sistema_gestione:soa_revisione", args=[revisione.numero]))
        self.assertContains(pagina, "Proponi alla Direzione")
        self.assertNotContains(pagina, "{#")

        voce = revisione.voci.get(controllo__codice="5.9")
        form_url = reverse("sistema_gestione:soa_voce", args=[voce.pk])
        self.assertEqual(self.client.get(form_url).status_code, 200)
        resp = self.client.post(form_url, {
            "livello": 4, "vulnerabilita": 1, "riferimenti": "Inventario sintetico", "giustificazione": "Motivo sintetico",
            "obbligo_normativo": "on",
        })
        self.assertEqual(resp.status_code, 302)
        voce.refresh_from_db()
        self.assertEqual((voce.livello, voce.riferimenti), (4, "Inventario sintetico"))

        self.client.post(reverse("sistema_gestione:soa_proponi", args=[revisione.numero]))
        self.client.post(reverse("sistema_gestione:soa_approva", args=[revisione.numero]))
        revisione.refresh_from_db()
        self.assertEqual(revisione.stato, SoaRevisione.STATO_APPROVATA)
        self.assertEqual(revisione.approvata_da, self.admin)

        bloccata = self.client.post(form_url, {"livello": 1, "vulnerabilita": 4, "giustificazione": "x"})
        self.assertEqual(bloccata.status_code, 302)
        voce.refresh_from_db()
        self.assertEqual(voce.livello, 4)

        pdf = self.client.get(reverse("sistema_gestione:soa_revisione", args=[revisione.numero]), {"formato": "pdf"})
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        xlsx = self.client.get(reverse("sistema_gestione:soa_revisione", args=[revisione.numero]), {"formato": "xlsx"})
        self.assertTrue(xlsx.content.startswith(b"PK"))

        from core.models import AuditLog

        azioni = set(AuditLog.objects.filter(modulo="sistema_gestione").values_list("azione", flat=True))
        self.assertTrue({"soa_revisione_creata", "soa_voce_modificata", "soa_revisione_approvata", "soa_download"} <= azioni)

    def test_approvazione_senza_permesso_negata(self):
        revisione = soa.nuova_revisione()
        soa.proponi(revisione)
        consentiti = {PERM_VIEW, PERM_SOA_VIEW, PERM_SOA_EDIT}
        with patch("sistema_gestione.views._has_perm", side_effect=lambda req, code: code in consentiti):
            pagina = self.client.get(reverse("sistema_gestione:soa_revisione", args=[revisione.numero]))
            self.assertNotContains(pagina, "Approva la revisione")
            self.client.post(reverse("sistema_gestione:soa_approva", args=[revisione.numero]))
        revisione.refresh_from_db()
        self.assertEqual(revisione.stato, SoaRevisione.STATO_PROPOSTA)

    def test_copia_firmata(self):
        from cryptography.fernet import Fernet

        cartella = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cartella, True)
        revisione = soa.nuova_revisione()
        soa.proponi(revisione)
        soa.approva(revisione, utente=self.admin)
        pdf = SimpleUploadedFile("firmata.pdf", b"%PDF-1.4\n%sintetico\n", content_type="application/pdf")
        with override_settings(TASKS_PRIVATE_ROOT=cartella, DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()), \
                patch("sistema_gestione.forms.validate_extension_and_mime", return_value="application/pdf"):
            self.client.post(reverse("sistema_gestione:soa_carica_firmata", args=[revisione.numero]), {"file": pdf})
            revisione.refresh_from_db()
            self.assertTrue(revisione.copia_firmata)
            resp = self.client.get(reverse("sistema_gestione:soa_copia_firmata", args=[revisione.numero]))
            self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4\n%sintetico\n")

    def test_threat_intelligence(self):
        resp = self.client.post(reverse("sistema_gestione:threat_intelligence_nuova"), {
            "data": timezone.localdate().isoformat(), "fonte": "Fonte sintetica", "informazione": "Campagna sintetica",
            "esito": ThreatIntelligence.ESITO_ACQUISITA,
        })
        self.assertEqual(resp.status_code, 302)
        lista = self.client.get(reverse("sistema_gestione:threat_intelligence"))
        self.assertContains(lista, "Campagna sintetica")


class ReportConformitaSoaTest(TestCase):
    def test_report_soa_con_e_senza_revisione(self):
        from report_conformita.registry import ReportParams, get_report

        report = get_report("dichiarazione-applicabilita")
        self.assertIsNotNone(report)
        oggi = timezone.localdate()
        params = ReportParams(date_from=oggi - timedelta(days=365), date_to=oggi, today=oggi)
        vuoto = report.build(params)
        self.assertEqual(vuoto.kpis[0].value, "nessuna")
        revisione = soa.nuova_revisione()
        revisione.voci.update(livello=4)
        revisione.voci.filter(controllo__codice="5.13").update(livello=2)
        soa.proponi(revisione)
        soa.approva(revisione, utente=User.objects.create_user(username="sg_dir", password="x"))
        pieno = report.build(params)
        self.assertEqual([r[0] for r in pieno.rows], ["5.13"])
        self.assertEqual(pieno.row_tones, ["warn"])
