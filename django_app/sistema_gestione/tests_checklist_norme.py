"""Fase 4: checklist di audit per norma (EN 9100, ISO 45001, UNI/PdR 125). Solo dati sintetici."""
from __future__ import annotations

from unittest.mock import patch

import fitz

from .acl_bootstrap import _ROUTE_BINDINGS, PERM_AUDIT_EDIT
from .audit_exports import rapporto_audit_pdf
from .models import Audit, AuditEsito, ChecklistDomanda, ChecklistModello, ChecklistSezione
from .services import audit as service
from .services import checklist_norme as checklist
from .tests_audit import AuditBase, _request


class BozzeTest(AuditBase):
    def test_bozza_iso45001_e_pdr125_inattive_con_domande(self):
        for codice in (ChecklistModello.CODICE_ISO45001, ChecklistModello.CODICE_PDR125):
            modello = checklist.proponi_bozza(codice, utente=self.user)
            self.assertFalse(modello.attivo)
            self.assertEqual(modello.revisione, 0)
            self.assertGreater(ChecklistDomanda.objects.filter(sezione__modello=modello).count(), 10)
            with self.assertRaises(checklist.ChecklistNonModificabile):
                checklist.proponi_bozza(codice, utente=self.user)

    def test_bozza_non_prevista_per_en9100(self):
        with self.assertRaises(checklist.ChecklistNonModificabile):
            checklist.proponi_bozza(ChecklistModello.CODICE_EN9100_FOLDER_B, utente=self.user)


class RevisioniTest(AuditBase):
    def setUp(self):
        super().setUp()
        self.modello = checklist.proponi_bozza(ChecklistModello.CODICE_ISO45001, utente=self.user)

    def test_attivazione_spegne_la_precedente(self):
        checklist.attiva(self.modello, utente=self.user)
        nuova = checklist.nuova_revisione(self.modello, utente=self.user, motivo="Allineamento procedure")
        self.assertEqual(nuova.revisione, 1)
        self.assertEqual(
            ChecklistDomanda.objects.filter(sezione__modello=nuova).count(),
            ChecklistDomanda.objects.filter(sezione__modello=self.modello).count(),
        )
        checklist.attiva(nuova, utente=self.user)
        self.modello.refresh_from_db()
        self.assertFalse(self.modello.attivo)
        self.assertEqual(checklist.modello_attivo(ChecklistModello.CODICE_ISO45001), nuova)

    def test_revisione_attiva_o_usata_non_si_modifica(self):
        domanda = ChecklistDomanda.objects.filter(sezione__modello=self.modello).first()
        domanda.testo = "Modificata"
        checklist.salva_domanda(domanda)
        checklist.attiva(self.modello, utente=self.user)
        with self.assertRaises(checklist.ChecklistNonModificabile):
            checklist.salva_domanda(domanda)
        checklist.disattiva(self.modello)
        audit = self.make_audit(iso45001=True, en9100=False)
        AuditEsito.objects.create(audit=audit, domanda=domanda)
        with self.assertRaises(checklist.ChecklistNonModificabile):
            checklist.rimuovi_domanda(domanda)

    def test_nuova_revisione_richiede_motivo_e_attivazione_domande(self):
        with self.assertRaises(checklist.ChecklistNonModificabile):
            checklist.nuova_revisione(self.modello, utente=self.user, motivo=" ")
        vuoto = ChecklistModello.objects.create(codice="ISO45001", norma="UNI ISO 45001:2018", revisione=7,
                                                titolo="Vuota", attivo=False)
        with self.assertRaises(checklist.ChecklistNonModificabile):
            checklist.attiva(vuoto, utente=self.user)


class AvvioAuditTest(AuditBase):
    def test_audit_integrato_carica_le_checklist_di_ogni_norma(self):
        _modello, _sezione, _domanda = self.make_checklist()
        iso = checklist.proponi_bozza(ChecklistModello.CODICE_ISO45001, utente=self.user)
        checklist.attiva(iso, utente=self.user)
        pdr = checklist.proponi_bozza(ChecklistModello.CODICE_PDR125, utente=self.user)  # non attiva: non si carica
        audit = self.make_audit(en9100=True, iso45001=True, pdr125=True)
        service.inizializza_checklist(audit)
        attese = 1 + ChecklistDomanda.objects.filter(sezione__modello=iso, attiva=True).count()
        self.assertEqual(audit.esiti.filter(domanda__isnull=False).count(), attese)
        self.assertFalse(audit.esiti.filter(domanda__sezione__modello=pdr).exists())
        esito = audit.esiti.filter(domanda__sezione__modello=iso).first()
        self.assertEqual(esito.domanda_snapshot["norma"], "UNI ISO 45001:2018")
        self.assertEqual(service.inizializza_checklist(audit), 0)

    def test_rapporto_intesta_le_norme_della_checklist(self):
        iso = checklist.proponi_bozza(ChecklistModello.CODICE_ISO45001, utente=self.user)
        checklist.attiva(iso, utente=self.user)
        audit = self.make_audit(en9100=False, iso45001=True)
        service.inizializza_checklist(audit)
        testo = "".join(p.get_text() for p in fitz.open(stream=rapporto_audit_pdf(audit, bozza=True), filetype="pdf"))
        self.assertIn("AUDIT DI SISTEMA ISO 45001:2018", testo)


class VisteChecklistTest(AuditBase):
    def test_binding_delle_route(self):
        for nome in ("checklist_norme", "checklist_modello", "checklist_proponi", "checklist_revisione"):
            self.assertIn(f"sistema_gestione:{nome}", _ROUTE_BINDINGS)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:checklist_revisione"], PERM_AUDIT_EDIT)

    @patch("sistema_gestione.checklist_views._has_perm", return_value=True)
    def test_pagine_e_modifica_di_una_domanda(self, _perm):
        from .checklist_views import checklist_modello, checklist_norme, checklist_proponi

        checklist_proponi(_request(self.user), ChecklistModello.CODICE_PDR125)
        modello = ChecklistModello.objects.get(codice=ChecklistModello.CODICE_PDR125)
        html = checklist_norme(_request(self.user, method="get")).content.decode()
        self.assertIn("Audit di sistema UNI/PdR 125:2022", html)
        self.assertNotIn("{#", html)
        html = checklist_modello(_request(self.user, method="get"), modello.pk).content.decode()
        self.assertIn("Attiva questa revisione", html)
        self.assertNotIn("{#", html)
        domanda = ChecklistDomanda.objects.filter(sezione__modello=modello).first()
        checklist_modello(_request(self.user, data={
            "azione": "domanda", "id": domanda.pk, f"d{domanda.pk}-punti": "Politica",
            f"d{domanda.pk}-testo": "Domanda sintetica aggiornata", f"d{domanda.pk}-ordine": "10", f"d{domanda.pk}-attiva": "on",
        }), modello.pk)
        domanda.refresh_from_db()
        self.assertEqual(domanda.testo, "Domanda sintetica aggiornata")

    @patch("sistema_gestione.checklist_views._has_perm")
    def test_senza_permesso_di_modifica_nessuna_scrittura(self, has_perm):
        from .checklist_views import checklist_modello

        modello = checklist.proponi_bozza(ChecklistModello.CODICE_PDR125, utente=self.user)
        has_perm.side_effect = lambda request, code: code != PERM_AUDIT_EDIT
        sezione = modello.sezioni.first()
        checklist_modello(_request(self.user, data={"azione": "rimuovi_sezione", "id": sezione.pk}), modello.pk)
        self.assertTrue(ChecklistSezione.objects.filter(pk=sezione.pk).exists())

    def test_audit_senza_norme_con_checklist_attiva_non_carica_nulla(self):
        audit = self.make_audit(en9100=False, iso27001=True, modulo=Audit.MODULO_SGI)
        self.assertEqual(service.inizializza_checklist(audit), 0)
