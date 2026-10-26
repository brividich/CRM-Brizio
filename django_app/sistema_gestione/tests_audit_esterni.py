"""Certificazioni e audit esterni: rilievi nel Registro OFI, chiusura, scadenze. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gestione_specifiche.models import RegistroOFI

from .models import AuditEsterno, Certificazione
from .services import audit_esterni as S


def _audit(**kw):
    dati = {"tipo": "SORVEGLIANZA", "ente": "Ente Prova", "data_inizio": timezone.localdate(), "en9100": True,
            "iso45001": True, "risposta_entro": timezone.localdate() + timedelta(days=30)}
    dati.update(kw)
    return AuditEsterno.objects.create(**dati)


class RilieviTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("est_u", password="x")

    def test_nc_maggiore_diventa_nc_alta_nel_registro(self):
        a = _audit()
        voce = S.crea_rilievo(a, classificazione="NC_MAGGIORE", descrizione="Taratura scaduta", utente=self.u,
                              rif_norma="7.1.5", responsabile=self.u)
        self.assertEqual((voce.tipo, voce.priorita, voce.fonte), (RegistroOFI.TIPO_NC, "ALTA", "Ente Prova"))
        self.assertTrue(voce.norma_en9100 and voce.norma_iso45001 and not voce.norma_iso27001)
        self.assertEqual(voce.data_richiesta, a.risposta_entro)
        self.assertTrue(voce.opportunita.startswith("[Non conformità maggiore]"))
        self.assertEqual(voce.modulo_origine, "sistema_gestione")
        self.assertEqual(list(S.rilievi(a)), [voce])
        self.assertTrue(voce.eventi.filter(tipo="CREATA").exists())
        a.refresh_from_db()
        self.assertEqual(a.stato, AuditEsterno.STATO_SVOLTO)

    def test_osservazione_diventa_ofi(self):
        voce = S.crea_rilievo(_audit(), classificazione="OSSERVAZIONE", descrizione="x", utente=self.u)
        self.assertEqual((voce.tipo, voce.priorita), (RegistroOFI.TIPO_OFI, "MEDIA"))

    def test_chiusura_richiede_esito_rapporto_e_nc_chiuse(self):
        a = _audit()
        S.crea_rilievo(a, classificazione="NC_MINORE", descrizione="x", utente=self.u)
        problemi = S.problemi_chiusura(a)
        self.assertEqual(len(problemi), 3)
        v = S.rilievi(a).get()
        v.fase, v.data_chiusura, v.verifica = RegistroOFI.FASE_CHIUSO, timezone.localdate(), "ok"
        v.save()
        a.esito = "CONFERMATO"
        a.rapporto.name = "sistema_gestione/audit_esterni/x.pdf"
        self.assertEqual(S.problemi_chiusura(a), [])


class ScadenzeTests(TestCase):
    def test_certificati_sorveglianze_e_risposte(self):
        oggi = timezone.localdate()
        Certificazione.objects.create(norma="EN9100", ente="E", scade_il=oggi + timedelta(days=60),
                                      prossima_sorveglianza=oggi + timedelta(days=10))
        Certificazione.objects.create(norma="ISO45001", ente="E", scade_il=oggi + timedelta(days=400))
        Certificazione.objects.create(norma="ISO14001", ente="E", scade_il=oggi - timedelta(days=1), attiva=False)
        _audit(risposta_entro=oggi + timedelta(days=3))
        _audit(risposta_entro=oggi + timedelta(days=3), stato=AuditEsterno.STATO_CHIUSO)
        d = S.scadenze(oggi)
        self.assertEqual([c.norma for c in d["certificati"]], ["EN9100"])
        self.assertEqual(len(d["sorveglianze"]), 1)
        self.assertEqual(len(d["risposte"]), 1)

    def test_job_settimanale(self):
        from . import tasks
        Certificazione.objects.create(norma="EN9100", ente="E", scade_il=timezone.localdate() - timedelta(days=1))
        with patch.object(tasks, "_email_rsgi", return_value=["rsgi@example.com"]), \
                patch("core.email_utils.send_hub_mail") as invia:
            esito = tasks.run_scadenze_audit_esterni()
        self.assertEqual(esito, {"voci": 1, "inviata": True})
        self.assertIn("SCADUTO", invia.call_args.kwargs["body_text"])


class VisteTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("est_su", "s@example.com", "x")
        self.client.force_login(self.su)

    def test_flusso_completo(self):
        oggi = timezone.localdate()
        r = self.client.post(reverse("sistema_gestione:esterni_certificazione_nuova"), {
            "norma": "EN9100", "ente": "Ente Prova", "scade_il": (oggi + timedelta(days=50)).isoformat(),
            "emesso_il": (oggi - timedelta(days=1000)).isoformat(), "attiva": "on"})
        self.assertEqual(r.status_code, 302)
        cert = Certificazione.objects.get()
        r = self.client.get(reverse("sistema_gestione:esterni_audit_nuovo") + f"?certificazione={cert.pk}")
        self.assertContains(r, "Ente Prova")
        r = self.client.post(reverse("sistema_gestione:esterni_audit_nuovo"), {
            "tipo": "SORVEGLIANZA", "certificazione": cert.pk, "ente": "Ente Prova", "data_inizio": oggi.isoformat(),
            "en9100": "on", "stato": "PIANIFICATO"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        audit = AuditEsterno.objects.get()
        r = self.client.post(reverse("sistema_gestione:esterni_rilievo", args=[audit.pk]), {
            "classificazione": "NC_MINORE", "descrizione": "Registrazioni incomplete", "rif_norma": "8.5.2"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(S.rilievi(audit).count(), 1)
        with patch("core.upload_mime.sniff_upload_mime", return_value="application/pdf"):
            r = self.client.post(reverse("sistema_gestione:esterni_rapporto_carica", args=[audit.pk]),
                                 {"file": SimpleUploadedFile("rapporto.pdf", b"%PDF-1.4 prova")})
        audit.refresh_from_db()
        self.assertEqual(len(audit.rapporto_sha256), 64)
        r = self.client.get(reverse("sistema_gestione:esterni_rapporto", args=[audit.pk]))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 prova")
        # NC aperta: la chiusura è rifiutata.
        self.client.post(reverse("sistema_gestione:esterni_chiudi", args=[audit.pk]))
        audit.refresh_from_db()
        self.assertNotEqual(audit.stato, AuditEsterno.STATO_CHIUSO)
        r = self.client.get(reverse("sistema_gestione:esterni_audit", args=[audit.pk]))
        self.assertContains(r, "Registrazioni incomplete")
        r = self.client.get(reverse("sistema_gestione:esterni_elenco"))
        self.assertContains(r, "Scade tra")
        voce = S.rilievi(audit).get()
        r = self.client.get(reverse("registro_ofi:dettaglio", args=[voce.pk]))
        self.assertContains(r, "Rilievo dell'audit esterno")
        audit.rapporto.delete(save=False)

    def test_audit_senza_norme_rifiutato(self):
        r = self.client.post(reverse("sistema_gestione:esterni_audit_nuovo"), {
            "tipo": "CLIENTE", "ente": "Cliente", "data_inizio": timezone.localdate().isoformat(), "stato": "PIANIFICATO"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AuditEsterno.objects.exists())

    def test_senza_permesso_negato(self):
        u = get_user_model().objects.create_user("est_no", password="x")
        from core.models import UserOnboarding
        UserOnboarding.objects.create(user=u, completed=True)
        self.client.force_login(u)
        with patch("sistema_gestione.esterni_views._has_perm", return_value=False), \
                patch("core.middleware.resolve_acl_access", return_value={"allowed": True}):
            r = self.client.get(reverse("sistema_gestione:esterni_elenco"))
        self.assertIn(r.status_code, (302, 403))
