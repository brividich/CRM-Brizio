"""Audit interni professionali (prompt 08): integrità del rapporto, firme separate, evidenze per audit."""
import tempfile
from hashlib import sha256
from unittest.mock import patch

import fitz
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from . import audit_views
from . import automation_views
from .acl_bootstrap import PERM_AUDIT_APPROVA, PERM_AUDIT_VIEW
from .audit_exports import rapporto_audit_pdf
from .models import Audit, AuditAllegato, AuditEsito, AuditPreparazione, AuditRapportoVersione
from .procedure_forms import PreparazioneForm
from .storage import PrivateSistemaGestioneStorage
from .tests_audit import AuditBase, _request

User = get_user_model()


def _testo_pdf(corpo: bytes) -> str:
    with fitz.open(stream=corpo, filetype="pdf") as doc:
        return "".join(p.get_text() for p in doc)


class _StoragePrivato:
    """Storage su cartella temporanea per i FileField del modulo."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(dir=settings.BASE_DIR / ".tmp_tests")
        root = self._tmp.__enter__()
        storage = PrivateSistemaGestioneStorage()
        storage._location = root
        self._patches = [
            patch.object(AuditRapportoVersione._meta.get_field("pdf"), "storage", storage),
            patch.object(Audit._meta.get_field("copia_firmata_rapporto"), "storage", storage),
            patch.object(AuditAllegato._meta.get_field("file"), "storage", storage),
        ]
        for p in self._patches:
            p.start()
        return storage

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        self._tmp.__exit__(*exc)


class RapportoEmessoTests(AuditBase):
    def setUp(self):
        super().setUp()
        self.rdd = User.objects.create_user(username="rdd-test", password="x")

    def _audit_da_chiudere(self):
        return self.make_audit(
            stato=Audit.STATO_RAPPORTO, giudizio="Giudizio originale", riepilogo_generato="Riepilogo sintetico R-1",
            rapporto_firmato_auditor_da=self.user, rapporto_firmato_auditor_il=timezone.now(),
            rapporto_convalidato_ente_da=self.direzione, rapporto_convalidato_ente_il=timezone.now(),
        )

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_chiusura_congela_pdf_con_impronta_e_lo_riconsegna_identico(self, _perm):
        audit = self._audit_da_chiudere()
        with _StoragePrivato():
            with self.captureOnCommitCallbacks(execute=True):
                audit_views.audit_valuta_rdd(_request(self.rdd, data={"valutazione_rdd": "Valutazione sintetica"}), audit.pk)
            audit.refresh_from_db()
            self.assertEqual(audit.stato, Audit.STATO_CHIUSO)
            emissione = audit.versioni_rapporto.get(tipo=AuditRapportoVersione.TIPO_EMISSIONE)
            with emissione.pdf.open("rb") as f:
                archiviato = f.read()
            self.assertEqual(emissione.sha256, sha256(archiviato).hexdigest())
            # Un dato collegato cambia dopo la chiusura: il rapporto emesso non deve cambiare.
            Audit.objects.filter(pk=audit.pk).update(giudizio="Giudizio riscritto dopo")
            response = audit_views.audit_export(_request(self.user, method="get"), audit.pk, "rapporto")
            consegnato = b"".join(response.streaming_content)
            response.file_to_stream.close()
        self.assertEqual(consegnato, archiviato)
        testo = _testo_pdf(consegnato)
        self.assertIn("Giudizio originale", testo)
        self.assertNotIn("riscritto", testo)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_anteprima_prima_della_chiusura_ha_la_filigrana(self, _perm):
        audit = self._audit_da_chiudere()
        response = audit_views.audit_export(_request(self.user, method="get"), audit.pk, "rapporto")
        self.assertIn("BOZZA", response["Content-Disposition"])
        self.assertIn("BOZZA - NON EMESSO", _testo_pdf(response.content))

    def test_pdf_riporta_convalida_ente_e_riepilogo(self):
        testo = _testo_pdf(rapporto_audit_pdf(self._audit_da_chiudere()))
        self.assertIn("Convalida responsabile ente: approvato digitalmente", testo)
        self.assertIn("Riepilogo sintetico R-1", testo)
        self.assertNotIn("BOZZA - NON EMESSO", testo)

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_rdd_non_puo_essere_chi_ha_firmato_il_rapporto(self, _perm):
        audit = self._audit_da_chiudere()
        audit_views.audit_valuta_rdd(_request(self.user, data={"valutazione_rdd": "Autovalutazione"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_RAPPORTO)
        self.assertFalse(audit.versioni_rapporto.exists())

    @patch("sistema_gestione.automation_views._has_perm", return_value=True)
    def test_revisione_archivia_con_impronta(self, _perm):
        audit = self._audit_da_chiudere()
        with _StoragePrivato():
            automation_views.revisiona_rapporto(_request(self.direzione, data={"motivo": "Nuove evidenze"}), audit.pk)
            versione = audit.versioni_rapporto.get()
            with versione.pdf.open("rb") as f:
                self.assertEqual(versione.sha256, sha256(f.read()).hexdigest())
        self.assertEqual(versione.tipo, AuditRapportoVersione.TIPO_REVISIONE)


class FirmePianoTests(AuditBase):
    @patch("sistema_gestione.audit_views.service.verifica_completezza", return_value={"piano": [], "rapporto": []})
    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_direzione_diversa_dal_lead(self, _perm, _completezza):
        audit = self.make_audit(piano_approvato_lead_da=self.user, piano_approvato_lead_il=timezone.now())
        audit_views.audit_approva_direzione(_request(self.user), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_PIANIFICATO)
        audit_views.audit_approva_direzione(_request(self.direzione), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_PIANO_APPROVATO)


class CopiaFirmataTests(AuditBase):
    def _pdf(self):
        return SimpleUploadedFile("firmato.pdf", b"%PDF-1.4\nfixture sintetica", content_type="application/pdf")

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_rapporto_firmato_solo_dopo_la_chiusura(self, _perm):
        audit = self.make_audit(stato=Audit.STATO_RAPPORTO)
        with _StoragePrivato():
            audit_views.audit_carica_firmata(_request(self.user, data={"file": self._pdf()}), audit.pk, "rapporto")
            audit.refresh_from_db()
            self.assertFalse(audit.copia_firmata_rapporto)
            Audit.objects.filter(pk=audit.pk).update(stato=Audit.STATO_CHIUSO)
            audit_views.audit_carica_firmata(_request(self.user, data={"file": self._pdf()}), audit.pk, "rapporto")
            audit.refresh_from_db()
            self.assertTrue(audit.copia_firmata_rapporto)

    def test_sostituzione_riservata_all_approvatore(self):
        audit = self.make_audit(stato=Audit.STATO_CHIUSO)
        solo_edit = lambda request, perm: perm != PERM_AUDIT_APPROVA  # noqa: E731
        with _StoragePrivato(), patch("sistema_gestione.audit_views._has_perm", side_effect=solo_edit):
            audit_views.audit_carica_firmata(_request(self.user, data={"file": self._pdf()}), audit.pk, "rapporto")
            audit.refresh_from_db()
            primo = audit.copia_firmata_rapporto.name
            audit_views.audit_carica_firmata(_request(self.user, data={"file": self._pdf()}), audit.pk, "rapporto")
            audit.refresh_from_db()
        self.assertTrue(primo)
        self.assertEqual(audit.copia_firmata_rapporto.name, primo)


class EvidenzePerAuditTests(AuditBase):
    def _allegato(self, audit):
        esito = AuditEsito.objects.create(audit=audit, testo_aggiuntivo="Verifica", punti_aggiuntivi="8.1")
        allegato = AuditAllegato(esito=esito, nome="prova.pdf", sha256="0" * 64, dimensione=10, caricato_da=self.user)
        allegato.file.save("prova.pdf", SimpleUploadedFile("prova.pdf", b"%PDF-1.4\nx"), save=False)
        allegato.save()
        return allegato

    def test_solo_consultazione_fuori_dal_team_non_scarica(self):
        estraneo = User.objects.create_user(username="estraneo-test", password="x")
        audit = self.make_audit()
        solo_view = lambda request, perm: perm == PERM_AUDIT_VIEW  # noqa: E731
        with _StoragePrivato(), patch("sistema_gestione.automation_views._has_perm", side_effect=solo_view):
            allegato = self._allegato(audit)
            negato = automation_views.allegato_download(_request(estraneo, method="get"), audit.pk, allegato.pk)
            consentito = automation_views.allegato_download(_request(self.user, method="get"), audit.pk, allegato.pk)
            consentito.file_to_stream.close()
        # Negato: redirect con messaggio (mai il file); senza permesso del modulo si torna alla dashboard.
        self.assertEqual(negato.status_code, 302)
        self.assertFalse(hasattr(negato, "streaming_content"))
        self.assertEqual(consentito.status_code, 200)


class PreparazioneAiTests(AuditBase):
    def test_origine_ai_resta_marcata_e_finisce_nel_pdf(self):
        audit = self.make_audit()
        dati = {"audit_precedenti": "Nessuno", "car_cliente": "Nessuna", "documenti_registrazioni": "PR-TEST",
                "obiettivi_carenze": "Verifica sintetica"}
        form = PreparazioneForm({**dati, "origine_ai": "True"}, instance=AuditPreparazione(audit=audit))
        self.assertTrue(form.is_valid(), form.errors)
        prep = form.save(commit=False)
        prep.verificato_da = self.user
        prep.save()
        riscritta = PreparazioneForm({**dati, "obiettivi_carenze": "Riscritta a mano"}, instance=prep)
        self.assertTrue(riscritta.is_valid(), riscritta.errors)
        self.assertTrue(riscritta.save().origine_ai)
        self.assertIn("Bozza iniziale proposta dall'AI", _testo_pdf(rapporto_audit_pdf(audit)))


# ---------------------------------------------------------------------------
# Fase 2: rilievi classificati, analisi cause, chiusura condizionata, solleciti
# ---------------------------------------------------------------------------

from datetime import timedelta  # noqa: E402

from core.models import SiteConfig  # noqa: E402
from gestione_specifiche.models import RegistroOFI  # noqa: E402

from .models import AzioneCorrettivaAudit  # noqa: E402
from .procedure_forms import CarForm  # noqa: E402
from .services import audit as service  # noqa: E402
from .services.audit_automation import problemi_esito  # noqa: E402


class RilieviClassificatiTests(AuditBase):
    def _nc(self, **kwargs):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO)
        dati = dict(audit=audit, testo_aggiuntivo="Verifica", punti_aggiuntivi="8.5.1", esito="NC",
                    evidenze="Registrazione assente", responsabile_azione=self.direzione)
        dati.update(kwargs)
        return AuditEsito.objects.create(**dati)

    def test_nc_richiede_gravita_ed_evidenza_allegata(self):
        esito = self._nc()
        problemi = " ".join(problemi_esito(esito))
        self.assertIn("maggiore o minore", problemi)
        self.assertIn("evidenza oggettiva", problemi)
        esito.gravita = AuditEsito.GRAVITA_MAGGIORE
        esito.save()
        with _StoragePrivato():
            allegato = AuditAllegato(esito=esito, nome="foto.png", sha256="1" * 64, dimensione=8, caricato_da=self.user)
            allegato.file.save("foto.png", SimpleUploadedFile("foto.png", b"\x89PNG\r\n\x1a\n"), save=False)
            allegato.save()
            self.assertEqual(problemi_esito(esito), [])

    def test_nc_maggiore_nel_registro_con_priorita_alta_e_clausola(self):
        esito = self._nc(gravita=AuditEsito.GRAVITA_MAGGIORE, clausola="8.5.1 c)")
        voce = service.sincronizza_ofi(esito)
        self.assertEqual(voce.tipo, RegistroOFI.TIPO_NC)
        self.assertEqual(voce.priorita, RegistroOFI.PRIORITA_ALTA)
        self.assertEqual(voce.rif_norma, "8.5.1 c)")
        self.assertTrue(voce.opportunita.startswith("[NC maggiore]"))

    def test_osservazione_e_punto_di_forza_non_vanno_nel_registro(self):
        audit = self.make_audit(stato=Audit.STATO_IN_CORSO)
        for codice in (AuditEsito.ESITO_OSSERVAZIONE, AuditEsito.ESITO_PUNTO_FORZA):
            esito = AuditEsito.objects.create(audit=audit, testo_aggiuntivo=codice, punti_aggiuntivi="7.2",
                                              esito=codice, evidenze="Sintetica")
            self.assertIsNone(service.sincronizza_ofi(esito))
        conteggi = service.contatori_rilievi(audit)
        self.assertEqual((conteggi["osservazioni"], conteggi["punti_forza"]), (1, 1))
        self.assertFalse(RegistroOFI.objects.exists())

    def test_gravita_azzerata_se_non_nc(self):
        from .audit_forms import AuditEsitoForm

        esito = self._nc()
        form = AuditEsitoForm({"esito": "OFI", "gravita": "MAGGIORE", "evidenze": "x", "versione": 0}, instance=esito)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["gravita"], "")


class _CarBase(AuditBase):
    def _car(self, **kwargs):
        audit = kwargs.pop("audit", None) or self.make_audit(stato=Audit.STATO_RAPPORTO)
        esito = AuditEsito.objects.create(audit=audit, testo_aggiuntivo="Verifica", punti_aggiuntivi="8.5",
                                          esito="NC", gravita="MINORE", evidenze="Scostamento sintetico")
        voce = service.sincronizza_ofi(esito)
        dati = dict(registro=voce, data_richiesta=timezone.localdate(), responsabile=self.direzione)
        dati.update(kwargs)
        return audit, AzioneCorrettivaAudit.objects.create(**dati)


class AnalisiCauseTests(_CarBase):
    def _dati(self, car, **kwargs):
        dati = {"responsabile": self.direzione.pk, "versione": car.versione, "contenimento": "Blocco lotto",
                "azione": "Aggiorna istruzione", "analizzata_il": timezone.localdate().isoformat()}
        dati.update(kwargs)
        return dati

    def test_cinque_perche_salvati_strutturati(self):
        _audit, car = self._car()
        form = CarForm(self._dati(car, analisi_metodo="CINQUE_PERCHE", perche_1="Manca il controllo",
                                  perche_2="Istruzione non aggiornata"), instance=car)
        self.assertTrue(form.is_valid(), form.errors)
        car = form.save()
        self.assertEqual(car.analisi_perche[:2], ["Manca il controllo", "Istruzione non aggiornata"])
        self.assertTrue(car.analisi_compilata)

    def test_metodo_senza_contenuto_rifiutato(self):
        _audit, car = self._car()
        for metodo, campo in [("CINQUE_PERCHE", "perche_1"), ("ISHIKAWA", "analisi_metodo"), ("ESTERNA", "causa")]:
            form = CarForm(self._dati(car, analisi_metodo=metodo), instance=car)
            self.assertFalse(form.is_valid())
            self.assertIn(campo, form.errors)

    def test_ishikawa_alimenta_la_causa_compilata(self):
        _audit, car = self._car()
        form = CarForm(self._dati(car, analisi_metodo="ISHIKAWA", ishikawa_metodo="Sequenza di controllo assente"), instance=car)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().analisi_ishikawa, {"metodo": "Sequenza di controllo assente"})


class ChiusuraCondizionataTests(_CarBase):
    def _pronto(self):
        rdd = User.objects.create_user(username="rdd-chiusura", password="x")
        audit = self.make_audit(
            stato=Audit.STATO_RAPPORTO, rapporto_firmato_auditor_da=self.user, rapporto_firmato_auditor_il=timezone.now(),
            rapporto_convalidato_ente_da=self.direzione, rapporto_convalidato_ente_il=timezone.now(),
        )
        return rdd, audit

    @patch("sistema_gestione.audit_views._has_perm", return_value=True)
    def test_nc_senza_piano_azioni_approvato_blocca_la_chiusura(self, _perm):
        rdd, audit = self._pronto()
        _audit, car = self._car(audit=audit)
        audit_views.audit_valuta_rdd(_request(rdd, data={"valutazione_rdd": "ok"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_RAPPORTO)
        self.assertTrue(service.problemi_chiusura_audit(audit))
        car.approvata_il, car.approvata_da = timezone.now(), self.direzione
        car.save()
        self.assertEqual(service.problemi_chiusura_audit(audit), [])
        with _StoragePrivato(), self.captureOnCommitCallbacks(execute=True):
            audit_views.audit_valuta_rdd(_request(rdd, data={"valutazione_rdd": "ok"}), audit.pk)
        audit.refresh_from_db()
        self.assertEqual(audit.stato, Audit.STATO_CHIUSO)

    def test_regola_disattivabile(self):
        _rdd, audit = self._pronto()
        self._car(audit=audit)
        SiteConfig.set(service.CHIAVE_CHIUSURA_CAR, "0")
        self.assertEqual(service.problemi_chiusura_audit(audit), [])


class SollecitiCarTests(_CarBase):
    @patch("core.email_utils.send_hub_mail", return_value=1)
    @patch("core.notifiche.invia_notifica")
    def test_un_sollecito_al_giorno_e_una_sola_escalation(self, notifica, mail):
        from . import tasks

        _audit, car = self._car(data_richiesta=timezone.localdate() - timedelta(days=200))
        SiteConfig.set(tasks.CHIAVE_EMAIL_RSGI, "rsgi@example.test")
        primo = tasks.run_car_solleciti()
        secondo = tasks.run_car_solleciti()
        self.assertEqual(primo, {"solleciti": 1, "escalation": 1})
        self.assertEqual(secondo, {"solleciti": 0, "escalation": 0})
        self.assertEqual(notifica.call_count, 1)
        self.assertIn("MOD.174", notifica.call_args.args[2])
        self.assertEqual(mail.call_count, 1)
        car.refresh_from_db()
        self.assertEqual(car.escalation_il, timezone.localdate())

    def test_car_nei_tempi_nessun_ritardo(self):
        from . import tasks

        self._car()
        self.assertEqual(tasks.ritardi_car(), [])
