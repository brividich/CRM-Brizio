"""Test di CN-SGI · modifiche ai documenti: ciclo, permessi, bozze, confronto, emissione, solleciti."""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import modifiche as mod
from .models import (
    AssignmentStatus,
    CampaignStatus,
    ChangeRequestStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureChangeRequest,
    ProcedureRevision,
    SgiFirmeTipo,
    SgiModifica,
    SgiModificaStato as S,
    SgiPassaggio,
    SgiTestoEstratto,
    SourceType,
)
from .test_libreria import _doc

User = get_user_model()
TESTO_IN_VIGORE = "1 Scopo\nDefinire la gestione delle non conformità.\n2 Responsabilità\nIl responsabile qualità chiude l'azione."


def _docx(*paragrafi) -> bytes:
    import docx

    d = docx.Document()
    for stile, testo in paragrafi:
        if stile:
            d.add_heading(testo, level=int(stile))
        else:
            d.add_paragraph(testo)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _gestore_se_superuser(request):
    return bool(getattr(request.user, "is_superuser", False))


class _Base(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cnsgi_bozze_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        ov = override_settings(PRIVATE_ATTACHMENTS_ROOT=self._tmp)
        ov.enable()
        self.addCleanup(ov.disable)
        for target in ("procedure_refresh.views_modifiche._can_manage", "procedure_refresh.views_libreria._can_manage"):
            p = mock.patch(target, side_effect=_gestore_se_superuser)
            p.start()
            self.addCleanup(p.stop)
        # Il middleware ACL è provato altrove: qui contano i controlli della pagina (gestore / partecipante).
        acl = mock.patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
        acl.start()
        self.addCleanup(acl.stop)
        n = mock.patch("core.notifiche.invia_notifica")
        self.notifica = n.start()
        self.addCleanup(n.stop)
        self.gestore = User.objects.create_user(username="mod_gestore", password="pw", is_superuser=True)
        self.redattore = User.objects.create_user(username="mod_redattore", password="pw", first_name="Rita", last_name="Redige")
        self.verificatore = User.objects.create_user(username="mod_verifica", password="pw", first_name="Vera", last_name="Verifica")
        self.approvatore = User.objects.create_user(username="mod_approva", password="pw", first_name="Aldo", last_name="Approva")
        self.estraneo = User.objects.create_user(username="mod_estraneo", password="pw")
        self.lettore = User.objects.create_user(username="mod_lettore", password="pw")
        from core.models import UserOnboarding

        for u in (self.redattore, self.verificatore, self.approvatore, self.estraneo, self.lettore):
            UserOnboarding.objects.create(user=u, completed=True)
        self.doc = _doc("MT CN 06", "Gestione delle non conformità", testo=TESTO_IN_VIGORE)
        self.rev = self.doc.revisions.get(is_current=True)

    def _apri(self, **extra):
        self.client.force_login(self.gestore)
        dati = {
            "tipo": "revisione", "documento": self.doc.pk, "oggetto": "Firma della chiusura",
            "motivo": "Non è chiaro chi firma.", "origine": "segnalazione",
            "redattore": self.redattore.pk, "verificatore": self.verificatore.pk, "approvatore": self.approvatore.pk,
            "rilettura_automatica": "1",
        }
        dati.update(extra)
        r = self.client.post(reverse("procedure_refresh:modifica_nuova"), dati)
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:400])
        return SgiModifica.objects.latest("pk")

    def _carica(self, m, utente, contenuto=None, nome="MT CN 06 rev3.docx"):
        self.client.force_login(utente)
        contenuto = contenuto or _docx(("1", "Scopo"), ("", "Definire la gestione delle non conformità."),
                                       ("1", "Responsabilità"), ("", "Il responsabile qualità firma e chiude l'azione entro 30 giorni."))
        return self.client.post(reverse("procedure_refresh:modifica_carica", args=[m.pk]),
                                {"file": SimpleUploadedFile(nome, contenuto), "sintesi": "§2 firma"})

    def _azione(self, m, utente, azione, **extra):
        self.client.force_login(utente)
        return self.client.post(reverse("procedure_refresh:modifica_azione", args=[m.pk]), {"azione": azione, **extra})


class CicloTests(_Base):
    def test_ciclo_completo_fino_all_emissione(self):
        vecchia = ProcedureRevision.objects.create(
            document=self.doc, revision_code="1", revision_date=date(2025, 1, 1), effective_date=date(2025, 1, 1),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/o.pdf", file_name="o.pdf", is_current=False,
        )
        camp = ProcedureCampaign.objects.create(name="Vecchia", status=CampaignStatus.CLOSED, start_date=date(2025, 1, 1),
                                                due_date=date(2025, 2, 1), created_by=self.gestore)
        ProcedureAssignment.objects.create(campaign=camp, revision=vecchia, user=self.lettore, status=AssignmentStatus.READ_CONFIRMED)
        cr = ProcedureChangeRequest.objects.create(document=self.doc, revision=self.rev, created_by=self.lettore, testo="Chi firma?")

        m = self._apri(segnalazioni=[cr.pk])
        self.assertEqual(m.stato, S.IN_REDAZIONE)
        self.assertEqual(m.revisione_base, self.rev)
        self.assertEqual(m.revisione_prevista, "3")
        cr.refresh_from_db()
        self.assertEqual(cr.status, ChangeRequestStatus.IN_CARICO)

        # Senza bozza non si invia in verifica.
        self._azione(m, self.redattore, "in_verifica")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_REDAZIONE)

        self.assertEqual(self._carica(m, self.redattore).status_code, 302)
        b = m.bozze.get()
        self.assertEqual(len(b.impronta), 64)
        self.assertIn("2 Responsabilità", b.testo)

        self._azione(m, self.redattore, "in_verifica")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_VERIFICA)

        # Rimandare senza nota non si può; con la nota torna in redazione.
        self._azione(m, self.verificatore, "rimandata")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_VERIFICA)
        self._azione(m, self.verificatore, "rimandata", nota="Manca il termine")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_REDAZIONE)

        self._azione(m, self.redattore, "in_verifica")
        self._azione(m, self.verificatore, "verificata")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_APPROVAZIONE)

        # Chi verifica non può approvare al posto di chi approva.
        self._azione(m, self.verificatore, "approvata", conferma="1")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_APPROVAZIONE)
        # Senza la spunta di conferma la firma non vale.
        self._azione(m, self.approvatore, "approvata")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_APPROVAZIONE)
        self._azione(m, self.approvatore, "approvata", conferma="1")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.APPROVATA)
        firma = m.passaggi.get(azione="approvata")
        self.assertEqual(firma.impronta, b.impronta)
        self.assertEqual(firma.utente_nome.lower(), "aldo approva")
        self.assertEqual(firma.ruolo, "approvatore")

        # La qualità copia il PDF: la sincronizzazione porta la Rev.3 e la modifica si chiude.
        nuova = ProcedureRevision.objects.create(
            document=self.doc, revision_code="3", revision_date=date(2026, 11, 10), effective_date=date(2026, 11, 10),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/n.pdf", file_name="n.pdf", is_current=True,
        )
        self.assertEqual(mod.riconosci_emissioni(), 1)
        m.refresh_from_db()
        self.assertEqual(m.stato, S.EMESSA)
        self.assertEqual(m.revisione_emessa, nuova)
        cr.refresh_from_db()
        self.assertEqual(cr.status, ChangeRequestStatus.RECEPITA)
        self.assertEqual(cr.recepita_in_revisione, nuova)
        self.assertTrue(ProcedureAssignment.objects.filter(revision=nuova, user=self.lettore).exists())
        self.assertEqual(
            list(m.passaggi.values_list("azione", flat=True)),
            ["aperta", "bozza", "in_verifica", "rimandata", "in_verifica", "verificata", "approvata", "emessa"],
        )
        # Una seconda sincronizzazione non fa nulla.
        self.assertEqual(mod.riconosci_emissioni(), 0)

    def test_avvisi_a_chi_deve_agire(self):
        m = self._apri()
        self._carica(m, self.redattore)
        self.notifica.reset_mock()
        with mock.patch("procedure_refresh.tasks._legacy_id_map", side_effect=lambda ids: {i: 1000 + i for i in ids}):
            self._azione(m, self.redattore, "in_verifica")
        destinatari = [c.args[0] for c in self.notifica.call_args_list]
        self.assertEqual(destinatari, [1000 + self.verificatore.pk])
        self.assertIn("Da verificare", self.notifica.call_args.args[2])

    def test_documento_nuovo_riconosciuto_dal_codice(self):
        self.client.force_login(self.gestore)
        r = self.client.post(reverse("procedure_refresh:modifica_nuova"), {
            "tipo": "nuovo", "nuovo_codice": "MOD 173", "nuovo_titolo": "Registro tarature",
            "oggetto": "Nuovo modulo", "motivo": "Serve un registro.", "redattore": self.redattore.pk,
            "approvatore": self.approvatore.pk,
        })
        self.assertEqual(r.status_code, 302)
        m = SgiModifica.objects.latest("pk")
        self.assertIsNone(m.documento)
        SgiModifica.objects.filter(pk=m.pk).update(stato=S.APPROVATA)
        _doc("MOD.173", "Registro tarature")
        self.assertEqual(mod.riconosci_emissioni(), 1)
        m.refresh_from_db()
        self.assertEqual(m.stato, S.EMESSA)
        self.assertEqual(m.documento.code, "MOD.173")

    def test_codice_nuovo_gia_esistente(self):
        self.client.force_login(self.gestore)
        r = self.client.post(reverse("procedure_refresh:modifica_nuova"), {
            "tipo": "nuovo", "nuovo_codice": "MT CN 06", "nuovo_titolo": "Doppione",
            "oggetto": "x", "motivo": "y", "redattore": self.redattore.pk,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(SgiModifica.objects.exists())

    def test_annulla_richiede_il_motivo(self):
        m = self._apri()
        self._azione(m, self.gestore, "annullata")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.IN_REDAZIONE)
        self._azione(m, self.gestore, "annullata", nota="Superata dalla revisione del manuale")
        m.refresh_from_db()
        self.assertEqual(m.stato, S.ANNULLATA)

    def test_emissione_a_mano(self):
        m = self._apri()
        SgiModifica.objects.filter(pk=m.pk).update(stato=S.APPROVATA)
        nuova = ProcedureRevision.objects.create(
            document=self.doc, revision_code="3", revision_date=date(2026, 11, 10), effective_date=date(2026, 11, 10),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/n.pdf", file_name="n.pdf", is_current=True,
        )
        r = self.client.get(reverse("procedure_refresh:modifica_dettaglio", args=[m.pk]))
        self.assertContains(r, "Segna come emessa")
        self._azione(m, self.gestore, "emessa", revisione=nuova.pk)
        m.refresh_from_db()
        self.assertEqual(m.stato, S.EMESSA)


class AccessoTests(_Base):
    def test_chi_non_partecipa_non_vede_la_modifica_ne_la_bozza(self):
        m = self._apri()
        self._carica(m, self.redattore)
        b = m.bozze.get()
        self.client.force_login(self.estraneo)
        self.assertEqual(self.client.get(reverse("procedure_refresh:modifica_dettaglio", args=[m.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("procedure_refresh:modifica_bozza", args=[b.pk])).status_code, 404)
        r = self.client.get(reverse("procedure_refresh:modifiche"))
        self.assertNotContains(r, "Firma della chiusura")

    def test_chi_partecipa_scarica_la_bozza(self):
        m = self._apri()
        self._carica(m, self.redattore)
        b = m.bozze.get()
        self.client.force_login(self.verificatore)
        r = self.client.get(reverse("procedure_refresh:modifica_bozza", args=[b.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertTrue(b"".join(r.streaming_content).startswith(b"PK"))

    def test_solo_chi_gestisce_apre_una_modifica(self):
        self.client.force_login(self.redattore)
        r = self.client.get(reverse("procedure_refresh:modifica_nuova"))
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("procedure_refresh:modifiche_firme"))
        self.assertEqual(r.status_code, 302)

    def test_formato_non_ammesso(self):
        m = self._apri()
        self._carica(m, self.redattore, contenuto=b"MZ", nome="virus.exe")
        self.assertFalse(m.bozze.exists())

    def test_registro_non_modificabile_dall_admin(self):
        from django.contrib.admin.sites import site

        admin_registro = site._registry[SgiPassaggio]
        self.assertFalse(admin_registro.has_change_permission(None))
        self.assertFalse(admin_registro.has_delete_permission(None))


class PagineTests(_Base):
    def test_elenco_e_letture_mostrano_cosa_tocca_a_me(self):
        m = self._apri()
        self.client.force_login(self.redattore)
        r = self.client.get(reverse("procedure_refresh:modifiche"))
        self.assertContains(r, "Firma della chiusura")
        self.assertContains(r, "<b>Tu</b>", html=False)
        r = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertContains(r, "Documenti da lavorare")
        self.assertContains(r, reverse("procedure_refresh:modifica_dettaglio", args=[m.pk]))

    def test_confronto_con_la_revisione_in_vigore(self):
        m = self._apri()
        self._carica(m, self.redattore)
        r = self.client.get(reverse("procedure_refresh:modifica_dettaglio", args=[m.pk]))
        self.assertContains(r, "Cosa cambia")
        self.assertContains(r, "Cambiato")
        self.assertContains(r, "entro 30 giorni")

    def test_scheda_del_documento(self):
        self.client.force_login(self.gestore)
        url = reverse("procedure_refresh:libreria_documento", args=[self.doc.pk])
        self.assertContains(self.client.get(url, HTTP_HX_REQUEST="true"), "Avvia una modifica")
        self._apri()
        r = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(r, "Modifica in corso")
        self.assertContains(r, "Nuova revisione in redazione")
        self.client.force_login(self.lettore)
        self.assertContains(self.client.get(url, HTTP_HX_REQUEST="true"), "Nuova revisione in preparazione")

    def test_segnalazioni_portano_alla_modifica(self):
        cr = ProcedureChangeRequest.objects.create(document=self.doc, revision=self.rev, created_by=self.lettore, testo="Refuso")
        self.client.force_login(self.gestore)
        with mock.patch("procedure_refresh.views._can_manage", return_value=True):
            r = self.client.get(reverse("procedure_refresh:change_request_list"))
        self.assertContains(r, f"?segnalazione={cr.pk}")
        r = self.client.get(reverse("procedure_refresh:modifica_nuova") + f"?segnalazione={cr.pk}")
        self.assertContains(r, "Refuso")
        self.assertContains(r, "MT CN 06")

    def test_firme_per_tipo_proposte_all_apertura(self):
        self.client.force_login(self.gestore)
        self.client.post(reverse("procedure_refresh:modifiche_firme"), {
            "mt_verificatore": self.verificatore.pk, "altro_approvatore": self.approvatore.pk,
        })
        self.assertEqual(SgiFirmeTipo.objects.get(tipo="mt").verificatore, self.verificatore)
        self.assertEqual(mod.firme_per(self.doc), {"verificatore": self.verificatore.pk, "approvatore": self.approvatore.pk})
        r = self.client.get(reverse("procedure_refresh:modifica_nuova") + f"?doc={self.doc.pk}")
        self.assertContains(r, f'<option value="{self.verificatore.pk}" selected>', html=False)


class ServiziTests(_Base):
    def test_titoli_word_numerati(self):
        testo = mod.testo_di("b.docx", _docx(("1", "Scopo"), ("2", "Campo"), ("1", "Responsabilità"), ("", "Testo")))
        self.assertEqual(testo.splitlines()[:3], ["1 Scopo", "1.1 Campo", "2 Responsabilità"])

    def test_solleciti_una_volta(self):
        m = self._apri()
        SgiModifica.objects.filter(pk=m.pk).update(stato_dal=timezone.now() - timedelta(days=6))
        self.notifica.reset_mock()
        self.assertEqual(mod.solleciti(), 1)
        self.assertIn("da 6 giorni", self.notifica.call_args.args[2])
        self.assertEqual(mod.solleciti(), 0)

    def test_prossimi_codici(self):
        _doc("MOD 171", "a")
        _doc("MOD 172", "b")
        self.assertIn(("MOD", "MOD 173"), mod.prossimi_codici())
