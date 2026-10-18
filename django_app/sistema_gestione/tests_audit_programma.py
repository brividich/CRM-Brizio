"""Programma basato sul rischio (prompt 08, fase 3): ciclo triennale, frequenza, calendario,
rifiuto del programma, qualifica e deroga d'indipendenza configurabile."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import SiteConfig

from . import programma_views
from .audit_forms import AuditForm, AuditorForm
from .models import Audit, AuditEsito, CellaProgramma, CicloAudit, ProgrammaAudit, Processo, RigaProgramma
from .services import audit as service
from .services import programma as programma_service
from .services.audit_automation import priorita_processi
from .tests_audit import AuditBase, _request

User = get_user_model()


class FrequenzaRaccomandataTests(AuditBase):
    def test_il_rischio_avvicina_la_verifica_ma_mai_oltre_12_mesi(self):
        self.processo.frequenza_mesi = 12
        self.processo.criticita = 3
        mesi, motivi = programma_service.frequenza_raccomandata(self.processo, nc=0, ofi=0, non_efficaci=0)
        self.assertEqual(mesi, 6)
        self.assertTrue(motivi)
        self.processo.criticita = 1
        self.assertEqual(programma_service.frequenza_raccomandata(self.processo, nc=0, ofi=3, non_efficaci=0)[0], 9)
        self.assertEqual(programma_service.frequenza_raccomandata(self.processo, nc=0, ofi=0, non_efficaci=0)[0], 12)

    def test_priorita_conta_ofi_requisiti_cliente_e_mesi_dall_ultimo(self):
        self.processo.requisiti_cliente = "Audit annuale richiesto dal cliente"
        self.processo.save()
        chiuso = self.make_audit(numero="RAIS-2025-01", stato=Audit.STATO_CHIUSO,
                                 data_inizio=timezone.localdate() - timedelta(days=420))
        chiuso.processi_catalogo.add(self.processo)
        AuditEsito.objects.create(audit=chiuso, processo=self.processo, testo_aggiuntivo="x", esito="OFI", evidenze="y")
        # Costante: processi, audit, rilievi e (solo se ci sono rilievi) le loro verifiche di efficacia.
        with self.assertNumQueries(4):
            riga = priorita_processi(Processo.objects.filter(pk=self.processo.pk))[0]
        self.assertTrue(any("OFI" in m for m in riga["motivi"]))
        self.assertTrue(any("Requisiti cliente" in m for m in riga["motivi"]))
        self.assertGreaterEqual(riga["mesi_dall_ultimo"], 13)
        self.assertTrue(riga["oltre_frequenza"])


class CicloTriennaleTests(AuditBase):
    def test_copertura_per_anno_e_clausole_mai_programmate(self):
        anno = timezone.localdate().year
        self.processo.punti_9100 = "8.1, 8.5"
        self.processo.save()
        ciclo = CicloAudit.objects.create(nome="Ciclo EN 9100", anno_inizio=anno, anno_fine=anno + 2)
        programma = ProgrammaAudit.objects.create(anno=anno, stato=ProgrammaAudit.STATO_APPROVATO)
        riga = RigaProgramma.objects.create(programma=programma, processo=self.processo, area="QA", punti_9100="8.1")
        CellaProgramma.objects.create(riga=riga, mese=3)
        copertura = programma_service.copertura_ciclo(ciclo)
        mia = next(r for r in copertura["righe"] if r["processo"] == self.processo)
        self.assertEqual([a["stato"] for a in mia["anni"]], ["programmato", "", ""])
        self.assertEqual(mia["clausole_scoperte"], ["EN 9100 8.5"])
        self.assertTrue(mia["mai_verificato"])

    def test_ciclo_al_massimo_triennale(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            CicloAudit(nome="Troppo lungo", anno_inizio=2026, anno_fine=2029).full_clean()


class CalendarioTests(AuditBase):
    def test_audit_nei_giorni_e_celle_da_pianificare(self):
        self.make_audit(data_inizio=date(2026, 10, 14), data_fine=date(2026, 10, 15))
        programma = ProgrammaAudit.objects.create(anno=2026)
        riga = RigaProgramma.objects.create(programma=programma, processo=self.processo, area="QA")
        CellaProgramma.objects.create(riga=riga, mese=10)
        cal = programma_service.calendario_mese(2026, 10)
        giorni = {g["giorno"]: g["audit"] for s in cal["settimane"] for g in s}
        self.assertEqual(len(giorni[date(2026, 10, 14)]), 1)
        self.assertEqual(len(giorni[date(2026, 10, 15)]), 1)
        self.assertEqual(giorni[date(2026, 10, 16)], [])
        self.assertEqual(len(cal["da_pianificare"]), 1)

    @patch("sistema_gestione.programma_views._has_perm", return_value=True)
    def test_pagina_calendario_e_cicli(self, _perm):
        self.assertContains(programma_views.calendario(_request(self.user, method="get")), "Calendario audit")
        self.assertContains(programma_views.cicli(_request(self.user, method="get")), "Cicli di audit")


class ProgrammaApprovazioneTests(AuditBase):
    def _proposto(self):
        programma = ProgrammaAudit.objects.create(anno=2026, stato=ProgrammaAudit.STATO_PROPOSTA,
                                                  proposto_da=self.user, proposto_il=timezone.now())
        return programma

    @patch("sistema_gestione.services.audit._verifica_copertura_procedurale")
    def test_approvatore_diverso_dal_proponente(self, _cop):
        programma = self._proposto()
        with self.assertRaises(service.TransizioneNonAmmessa):
            service.approva_programma(programma, utente=self.user)
        service.approva_programma(programma, utente=self.direzione)
        self.assertEqual(programma.approvato_da, self.direzione)

    @patch("sistema_gestione.programma_views._has_perm", return_value=True)
    def test_rifiuto_con_motivo_riporta_in_bozza(self, _perm):
        programma = self._proposto()
        programma_views.programma_rifiuta(_request(self.direzione, data={"motivo": ""}), programma.pk)
        programma.refresh_from_db()
        self.assertEqual(programma.stato, ProgrammaAudit.STATO_PROPOSTA)
        programma_views.programma_rifiuta(_request(self.direzione, data={"motivo": "Manca il processo acquisti"}), programma.pk)
        programma.refresh_from_db()
        self.assertEqual(programma.stato, ProgrammaAudit.STATO_BOZZA)
        self.assertEqual(programma.motivo_rifiuto, "Manca il processo acquisti")
        self.assertIsNone(programma.proposto_da)


class QualificaAuditorTests(AuditBase):
    def test_qualifica_scaduta_non_qualifica(self):
        self.assertTrue(self.auditor.qualificato)
        self.auditor.qualifica_scadenza = timezone.localdate() - timedelta(days=1)
        self.assertFalse(self.auditor.qualificato)

    def test_norme_abilitate_bloccano_il_piano(self):
        form = AuditorForm({"interno": True, "user": self.user.pk, "requisiti_verificati_il": "2026-01-10",
                            "audit_svolti_pregressi": 4, "attivo": True, "norme": ["iso45001"]}, instance=self.auditor)
        self.assertTrue(form.is_valid(), form.errors)
        auditor = form.save()
        self.assertEqual(auditor.norme_abilitate, "iso45001")
        audit = self.make_audit(en9100=True)
        testi = " ".join(v["testo"] for v in service.verifica_completezza(audit)["piano"])
        self.assertIn("non è abilitato", testi)


class DerogaImparzialitaTests(AuditBase):
    def _dati_form(self, **kwargs):
        dati = {"tipo": Audit.TIPO_SISTEMA, "en9100": True, "lead_auditor": self.auditor.pk,
                "processi_catalogo": [self.processo.pk], "data_inizio": "2026-10-15", "sede": "Sede sintetica",
                "metodo_intervista": True, "esclusioni": "Nessuna"}
        dati.update(kwargs)
        return dati

    def test_blocco_di_default_deroga_solo_se_ammessa_e_motivata(self):
        # L'auditor è responsabile del processo: conflitto di indipendenza.
        self.processo.responsabile = self.user
        self.processo.save()
        self.assertIn("imparzialita_deroga_motivo", AuditForm(self._dati_form(imparzialita_deroga_motivo="Unico esperto")).errors)
        SiteConfig.set("sistema_gestione.audit_deroga_imparzialita_ammessa", "1")
        self.assertIn("imparzialita_deroga_motivo", AuditForm(self._dati_form()).errors)
        self.assertNotIn("imparzialita_deroga_motivo", AuditForm(self._dati_form(imparzialita_deroga_motivo="Unico esperto")).errors)

    @patch("sistema_gestione.programma_views._has_perm", return_value=True)
    def test_approvazione_rdd_esterna_al_team_e_tracciata(self, _perm):
        SiteConfig.set("sistema_gestione.audit_deroga_imparzialita_ammessa", "1")
        self.processo.responsabile = self.user
        self.processo.save()
        audit = self.make_audit(imparzialita_deroga_motivo="Unico esperto del processo speciale")
        audit.processi_catalogo.add(self.processo)
        testi = lambda: " ".join(v["testo"] for v in service.verifica_completezza(audit)["piano"])  # noqa: E731
        self.assertIn("in attesa dell'approvazione RDD", testi())
        programma_views.audit_approva_deroga(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertIsNone(audit.imparzialita_deroga_approvata_il)
        programma_views.audit_approva_deroga(_request(self.direzione), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.imparzialita_deroga_approvata_da, self.direzione)
        self.assertNotIn("indipendenza", testi())
        service.invalida_approvazione_piano(audit)
        self.assertIsNone(audit.imparzialita_deroga_approvata_il)


class Iso14001Tests(AuditBase):
    def test_norma_14001_nel_piano_e_nei_punti(self):
        self.processo.punti_14001 = "6.1.2"
        self.processo.save()
        form = AuditForm({"tipo": Audit.TIPO_SISTEMA, "iso14001": True, "lead_auditor": self.auditor.pk,
                          "processi_catalogo": [self.processo.pk], "data_inizio": "2026-10-15", "sede": "Sede",
                          "metodo_intervista": True, "esclusioni": "Nessuna"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn("ISO 14001: 6.1.2", form.cleaned_data["punti_norma"])
        self.assertIn("ISO 14001:2015", Audit(iso14001=True).norme_label)

    @patch("sistema_gestione.programma_views._has_perm", return_value=True)
    def test_impostazioni_salvate_e_tracciate(self, _perm):
        dati = {"sistema_gestione__audit_chiusura_richiede_car_approvate": "", "sistema_gestione__car_escalation_giorni": "20",
                "sistema_gestione__audit_email_rsgi": "rsgi@example.test"}
        programma_views.impostazioni(_request(self.direzione, data=dati))
        self.assertEqual(SiteConfig.get("sistema_gestione.audit_chiusura_richiede_car_approvate"), "0")
        self.assertEqual(SiteConfig.get("sistema_gestione.car_escalation_giorni"), "20")
        self.assertFalse(service.chiusura_richiede_car_approvate())
