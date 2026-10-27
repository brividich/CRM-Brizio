"""Fase 3: audit ISMS (MT CN 276, MOD.171 e MOD.168). Solo dati sintetici."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from gestione_specifiche.models import RegistroOFI

from .acl_bootstrap import _ROUTE_BINDINGS, PERM_AUDIT_ESEGUI, PERM_SOA_EDIT
from .audit_exports import piano_isms_pdf, rapporto_isms_pdf
from .audit_forms import AuditForm, AuditIsmsControlloForm
from .models import (
    RILIEVO_ISMS_AP,
    RILIEVO_ISMS_COM,
    RILIEVO_ISMS_NC,
    Audit,
    AuditIsmsControllo,
    AuditIsmsRequisito,
    ControlloIso27002,
    SoaRevisione,
)
from .services import audit as service
from .services import audit_isms
from .services import soa as soa_service
from .tests_audit import AuditBase, _request

User = get_user_model()


class IsmsBase(AuditBase):
    def setUp(self):
        super().setUp()
        soa_service.assicura_catalogo()
        self.soa = soa_service.nuova_revisione(numero=3, motivo="Sintetica")
        self.soa.voci.update(livello=2)
        self.soa.voci.filter(controllo__codice="8.28").update(livello=0)
        self.soa.stato = SoaRevisione.STATO_APPROVATA
        self.soa.save(update_fields=["stato"])

    def make_isms(self, **kwargs):
        dati = {"numero": "RAIS-2026-09", "modulo": Audit.MODULO_ISMS, "en9100": False, "iso27001": True,
                "sede": "Sede sintetica"}
        dati.update(kwargs)
        audit = self.make_audit(**dati)
        audit_isms.assicura_isms(audit)
        return audit

    def compila(self, audit):
        dati = audit.isms
        dati.campo_date = "15/10/2026"
        dati.campo_ore = "8"
        dati.modifiche_sistema = dati.modifiche_campo = dati.modifiche_addetti = "NO"
        dati.efficacia_ncmi = "NON_PRESENTI"
        dati.report_precedenti = "NA"
        dati.commenti_precedenti = "NON_PRESENTI"
        dati.save()
        audit.isms_requisiti.update(evidenze="Evidenza sintetica")


class AssicuraIsmsTest(IsmsBase):
    def test_crea_requisiti_e_93_controlli_con_livelli_della_soa(self):
        audit = self.make_isms()
        self.assertEqual(audit.isms_requisiti.count(), len(audit_isms.REQUISITI_MOD168))
        self.assertEqual(audit.isms_controlli.count(), ControlloIso27002.objects.count())
        self.assertEqual(audit.isms_controlli.count(), 93)
        riga = audit.isms_controlli.get(controllo__codice="8.28")
        self.assertEqual((riga.livello_soa, riga.livello), (0, 0))
        self.assertEqual(audit.isms.soa_revisione, self.soa)
        self.assertEqual(audit.isms.sito_campo, "Sede sintetica")

    def test_idempotente_e_non_sovrascrive_le_valutazioni(self):
        audit = self.make_isms()
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.livello = 4
        riga.save()
        audit_isms.assicura_isms(audit)
        riga.refresh_from_db()
        self.assertEqual(riga.livello, 4)
        self.assertEqual(audit.isms_controlli.count(), 93)

    def test_audit_sgi_non_crea_dati_isms(self):
        audit = self.make_audit()
        self.assertIsNone(audit_isms.assicura_isms(audit))
        self.assertFalse(AuditIsmsControllo.objects.filter(audit=audit).exists())

    def test_senza_soa_approvata_i_livelli_restano_da_valutare(self):
        SoaRevisione.objects.update(stato=SoaRevisione.STATO_BOZZA)
        audit = self.make_isms()
        self.assertFalse(audit.isms_controlli.exclude(livello=None).exists())
        self.assertIsNone(audit.isms.soa_revisione)

    def test_form_audit_isms_imposta_sempre_iso27001(self):
        form = AuditForm(data={
            "modulo": Audit.MODULO_ISMS, "tipo": Audit.TIPO_SISTEMA, "lead_auditor": self.auditor.pk,
            "processi_catalogo": [self.processo.pk], "data_inizio": "2026-10-15", "data_fine": "2026-10-15",
            "sede": "Sede", "esclusioni": "Nessuna", "en9100": "", "metodo_intervista": "on",
        })
        form.is_valid()
        self.assertTrue(form.cleaned_data.get("iso27001"))
        self.assertNotIn("__all__", form.errors)


class RilieviIsmsTest(IsmsBase):
    def test_nc_su_controllo_crea_una_sola_voce_mod174(self):
        audit = self.make_isms()
        riga = audit.isms_controlli.get(controllo__codice="5.15")
        riga.rilievo, riga.gravita, riga.evidenze = RILIEVO_ISMS_NC, "MINORE", "Accessi non riesaminati"
        audit_isms.salva_riga(riga, utente=self.user)
        audit_isms.salva_riga(riga, utente=self.user)
        voce = RegistroOFI.objects.get()
        self.assertEqual(voce.tipo, RegistroOFI.TIPO_NC)
        self.assertTrue(voce.norma_iso27001)
        self.assertEqual(voce.rif_norma, "ISO/IEC 27002:2022 5.15")
        self.assertIn("[NC minore]", voce.opportunita)
        riga.refresh_from_db()
        self.assertEqual(riga.ofi, voce)

    def test_ap_diventa_ofi_e_com_resta_commento(self):
        audit = self.make_isms()
        req = audit.isms_requisiti.get(codice="9.2")
        req.rilievo, req.evidenze = RILIEVO_ISMS_AP, "Programma da estendere"
        audit_isms.salva_riga(req, utente=self.user)
        com = audit.isms_requisiti.get(codice="9.3")
        com.rilievo, com.evidenze = RILIEVO_ISMS_COM, "Verbale sintetico"
        audit_isms.salva_riga(com, utente=self.user)
        voce = RegistroOFI.objects.get()
        self.assertEqual(voce.tipo, RegistroOFI.TIPO_OFI)
        self.assertEqual(voce.rif_norma, "ISO/IEC 27001:2022 9.2")
        com.refresh_from_db()
        self.assertIsNone(com.ofi_id)
        conteggi = service.contatori_rilievi(audit)
        self.assertEqual((conteggi["ofi"], conteggi["osservazioni"]), (1, 1))

    def test_rilievo_registrato_non_cambia_tipo(self):
        audit = self.make_isms()
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.rilievo, riga.evidenze = RILIEVO_ISMS_AP, "Politica da rivedere"
        audit_isms.salva_riga(riga, utente=self.user)
        riga.rilievo = RILIEVO_ISMS_COM
        with self.assertRaises(ValidationError):
            audit_isms.salva_riga(riga, utente=self.user)

    def test_nc_senza_gravita_o_rilievo_senza_evidenze_rifiutati(self):
        audit = self.make_isms()
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.rilievo = RILIEVO_ISMS_NC
        with self.assertRaises(ValidationError):
            audit_isms.salva_riga(riga, utente=self.user)
        self.assertFalse(RegistroOFI.objects.exists())

    def test_livello_diverso_dalla_soa_richiede_commento(self):
        audit = self.make_isms()
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        form = AuditIsmsControlloForm(data={"livello": "4", "evidenze": "", "rilievo": "", "gravita": ""}, instance=riga)
        self.assertFalse(form.is_valid())
        self.assertIn("evidenze", form.errors)
        form = AuditIsmsControlloForm(data={"livello": "4", "evidenze": "Verificato su campione", "rilievo": "", "gravita": ""}, instance=riga)
        self.assertTrue(form.is_valid(), form.errors)


class CompletezzaIsmsTest(IsmsBase):
    def test_rapporto_isms_non_richiede_checklist_ma_tutte_le_righe(self):
        audit = self.make_isms(stato=Audit.STATO_IN_CORSO, giudizio="Giudizio")
        testi = [v["testo"] for v in service.verifica_completezza(audit)["rapporto"]]
        self.assertNotIn("Carica una checklist prima di firmare il rapporto.", testi)
        self.assertTrue(any("MOD.168" in t for t in testi))
        self.compila(audit)
        self.assertEqual(service.verifica_completezza(audit)["rapporto"], [])
        self.assertEqual(service.verifica_completezza(audit)["percentuale"], 100)

    def test_azioni_non_efficaci_richiedono_nc_maggiore(self):
        audit = self.make_isms(stato=Audit.STATO_IN_CORSO, giudizio="Giudizio")
        self.compila(audit)
        audit.isms.efficacia_ncmi = "NON_EFFICACI"
        audit.isms.save()
        self.assertTrue(any("NC maggiore" in p["testo"] for p in audit_isms.problemi_rapporto_isms(audit)))
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.rilievo, riga.gravita, riga.evidenze = RILIEVO_ISMS_NC, "MAGGIORE", "Azioni precedenti inefficaci"
        audit_isms.salva_riga(riga, utente=self.user)
        self.assertFalse(any("NC maggiore" in p["testo"] for p in audit_isms.problemi_rapporto_isms(audit)))

    def test_chiusura_richiede_car_approvata_per_le_nc_isms(self):
        audit = self.make_isms(stato=Audit.STATO_RAPPORTO)
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.rilievo, riga.gravita, riga.evidenze = RILIEVO_ISMS_NC, "MINORE", "Scostamento"
        audit_isms.salva_riga(riga, utente=self.user)
        self.assertTrue(any("CAR" in p for p in service.problemi_chiusura_audit(audit)))


class SoaDaAuditTest(IsmsBase):
    def test_audit_chiuso_apre_revisione_soa_con_i_livelli_emersi(self):
        audit = self.make_isms(stato=Audit.STATO_CHIUSO)
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        riga.livello, riga.evidenze = 4, "Politica approvata e diffusa"
        riga.save()
        revisione, variazioni = audit_isms.proponi_aggiornamento_soa(audit, utente=self.user)
        self.assertEqual(variazioni, 1)
        self.assertEqual(revisione.stato, SoaRevisione.STATO_BOZZA)
        voce = revisione.voci.get(controllo__codice="5.1")
        self.assertEqual(voce.livello, 4)
        self.assertIn(audit.numero, voce.giustificazione)
        self.assertEqual(revisione.voci.get(controllo__codice="5.2").livello, 2)
        audit.isms.refresh_from_db()
        self.assertEqual(audit.isms.soa_proposta, revisione)
        with self.assertRaises(soa_service.TransizioneNonAmmessa):
            audit_isms.proponi_aggiornamento_soa(audit, utente=self.user)

    def test_proposta_negata_se_audit_non_chiuso_o_senza_variazioni(self):
        audit = self.make_isms(stato=Audit.STATO_RAPPORTO)
        with self.assertRaises(soa_service.TransizioneNonAmmessa):
            audit_isms.proponi_aggiornamento_soa(audit, utente=self.user)
        audit.stato = Audit.STATO_CHIUSO
        audit.save()
        with self.assertRaises(soa_service.TransizioneNonAmmessa):
            audit_isms.proponi_aggiornamento_soa(audit, utente=self.user)


class PdfIsmsTest(IsmsBase):
    def _testo(self, corpo: bytes) -> str:
        self.assertTrue(corpo.startswith(b"%PDF"))
        return "".join(p.get_text() for p in fitz.open(stream=corpo, filetype="pdf"))

    def test_piano_mod171(self):
        audit = self.make_isms()
        service.prepara_nuovo_audit(audit)
        testo = self._testo(piano_isms_pdf(audit))
        self.assertIn("M-AUD-01 Audit Plan", testo)
        self.assertIn("Elenco siti oggetto di audit", testo)
        self.assertIn("Riunione di apertura", testo)

    def test_rapporto_mod168_con_93_controlli_e_rilievi(self):
        audit = self.make_isms(stato=Audit.STATO_IN_CORSO)
        riga = audit.isms_controlli.get(controllo__codice="5.15")
        riga.rilievo, riga.gravita, riga.evidenze = RILIEVO_ISMS_NC, "MINORE", "Accessi non riesaminati"
        audit_isms.salva_riga(riga, utente=self.user)
        testo = self._testo(rapporto_isms_pdf(audit, bozza=True))
        self.assertIn("M-AUD-02 Rapporto di Audit", testo)
        self.assertIn("ISO 27002:2022 - 8.34", testo)
        self.assertIn("Elenco azioni correttive", testo)
        self.assertIn("MOD.174 n.", testo)

    def test_emissione_alla_chiusura_usa_il_mod168(self):
        from .services.rapporto import emetti_rapporto

        audit = self.make_isms(stato=Audit.STATO_CHIUSO)
        versione = emetti_rapporto(audit, autore=self.user)
        with versione.pdf.open("rb") as file:
            self.assertIn("M-AUD-02", self._testo(file.read()))
        versione.pdf.delete(save=False)


class VisteIsmsTest(IsmsBase):
    def test_tutte_le_route_isms_hanno_un_binding(self):
        for nome in ("audit_isms", "audit_isms_piano", "audit_isms_testata", "audit_isms_requisito",
                     "audit_isms_controllo", "audit_isms_proponi_soa"):
            self.assertIn(f"sistema_gestione:{nome}", _ROUTE_BINDINGS)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:audit_isms_controllo"], PERM_AUDIT_ESEGUI)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:audit_isms_proponi_soa"], PERM_SOA_EDIT)

    @patch("sistema_gestione.isms_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_pagina_isms_si_apre_senza_commenti_django(self, _p1, _p2):
        from .isms_views import audit_isms as vista

        audit = self.make_isms(stato=Audit.STATO_IN_CORSO)
        risposta = vista(_request(self.user, method="get"), audit.pk)
        self.assertEqual(risposta.status_code, 200)
        html = risposta.content.decode()
        self.assertNotIn("{#", html)
        self.assertIn("Controlli ISO/IEC 27002:2022", html)
        self.assertIn(reverse("sistema_gestione:audit_isms_controllo", args=[audit.pk, audit.isms_controlli.first().pk]), html)

    @patch("sistema_gestione.isms_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_solo_il_team_assegnato_compila(self, _p1, _p2):
        from .isms_views import audit_isms_controllo

        audit = self.make_isms(stato=Audit.STATO_IN_CORSO)
        riga = audit.isms_controlli.get(controllo__codice="5.1")
        dati = {f"ctrl{riga.pk}-livello": "3", f"ctrl{riga.pk}-evidenze": "Campione verificato",
                f"ctrl{riga.pk}-rilievo": "", f"ctrl{riga.pk}-gravita": ""}
        audit_isms_controllo(_request(self.direzione, data=dati), audit.pk, riga.pk)
        riga.refresh_from_db()
        self.assertEqual(riga.livello, 2)
        audit_isms_controllo(_request(self.user, data=dati), audit.pk, riga.pk)
        riga.refresh_from_db()
        self.assertEqual((riga.livello, riga.aggiornato_da), (3, self.user))

    @patch("sistema_gestione.isms_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_rapporto_firmato_non_si_modifica(self, _p1, _p2):
        from .isms_views import audit_isms_requisito

        audit = self.make_isms(stato=Audit.STATO_RAPPORTO, rapporto_firmato_auditor_da=self.user,
                               rapporto_firmato_auditor_il=timezone.now())
        req = audit.isms_requisiti.first()
        audit_isms_requisito(_request(self.user, data={f"req{req.pk}-evidenze": "Alterata"}), audit.pk, req.pk)
        req.refresh_from_db()
        self.assertEqual(req.evidenze, "")

    @patch("sistema_gestione.isms_views._has_perm", return_value=True)
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_export_usa_i_moduli_isms(self, _p1, _p2):
        from .audit_views import audit_export

        audit = self.make_isms(data_inizio=date(2026, 10, 15))
        risposta = audit_export(_request(self.user, method="get"), audit.pk, "piano")
        self.assertIn("MOD171_", risposta["Content-Disposition"])
        risposta = audit_export(_request(self.user, method="get"), audit.pk, "rapporto")
        self.assertIn("MOD168_", risposta["Content-Disposition"])
