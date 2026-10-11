"""Esecuzione da tablet e rete instabile (prompt 08, fase 4)."""
import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from . import automation_views as views
from .models import Audit, AuditEsito
from .tests_audit import AuditBase, _request
from .tests_audit_pro import _StoragePrivato


def _ajax(user, data=None):
    request = _request(user, data=data)
    request.META["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
    request.META["HTTP_ACCEPT"] = "application/json"
    return request


class EsecuzioneBase(AuditBase):
    def setUp(self):
        super().setUp()
        self.audit = self.make_audit(stato=Audit.STATO_IN_CORSO, data_inizio=timezone.localdate(), data_fine=timezone.localdate())
        self.esiti = [AuditEsito.objects.create(audit=self.audit, testo_aggiuntivo=f"Verifica {n}", punti_aggiuntivi=f"8.{n}")
                      for n in range(1, 4)]


@patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
class AutosalvataggioIdempotenteTests(EsecuzioneBase):
    def test_stesso_tentativo_ripetuto_non_da_conflitto(self, _executor):
        esito = self.esiti[0]
        dati = {"versione": 0, "esito": "CONFORME", "evidenze": "Prima stesura", "salvataggio_id": "tentativo-1"}
        primo = views.esito_bozza(_ajax(self.user, dati), self.audit.pk, esito.pk)
        self.assertEqual(json.loads(primo.content)["versione"], 1)
        # La risposta si è persa: il client ripete lo stesso tentativo con la versione vecchia.
        ripetuto = views.esito_bozza(_ajax(self.user, dati), self.audit.pk, esito.pk)
        self.assertEqual(ripetuto.status_code, 200)
        corpo = json.loads(ripetuto.content)
        self.assertTrue(corpo["ripetuto"])
        self.assertEqual(corpo["versione"], 1)
        esito.refresh_from_db()
        self.assertEqual(esito.versione, 1)

    def test_tentativo_nuovo_con_versione_vecchia_resta_conflitto(self, _executor):
        esito = self.esiti[0]
        views.esito_bozza(_ajax(self.user, {"versione": 0, "esito": "CONFORME", "evidenze": "A", "salvataggio_id": "t1"}), self.audit.pk, esito.pk)
        altro = views.esito_bozza(_ajax(self.user, {"versione": 0, "esito": "CONFORME", "evidenze": "B", "salvataggio_id": "t2"}), self.audit.pk, esito.pk)
        self.assertEqual(altro.status_code, 409)


@patch("sistema_gestione.automation_views._has_perm", return_value=True)
@patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
class EditorTabletTests(EsecuzioneBase):
    def test_navigazione_in_ordine_ed_esiti_a_pulsanti(self, _executor, _perm):
        centrale = self.esiti[1]
        response = views.esito_editor(_request(self.user, method="get"), self.audit.pk, centrale.pk)
        self.assertContains(response, "Verifica <strong>2</strong> di 3", html=False)
        self.assertContains(response, f"/verifica/{self.esiti[0].pk}/")
        self.assertContains(response, f"/verifica/{self.esiti[2].pk}/")
        self.assertContains(response, 'type="radio"')
        self.assertContains(response, 'capture="environment"')
        self.assertContains(response, "informazioni da completare")


@patch("sistema_gestione.automation_views._assigned_executor", return_value=True)
class UploadAsincronoTests(EsecuzioneBase):
    def _pdf(self, nome="campione.pdf", contenuto=b"%PDF-1.4\nfixture sintetica"):
        return SimpleUploadedFile(nome, contenuto, content_type="application/pdf")

    def test_risposta_json_e_rilievo_nc_emesso_al_caricamento(self, _executor):
        esito = self.esiti[0]
        AuditEsito.objects.filter(pk=esito.pk).update(esito="NC", gravita="MINORE", evidenze="Registrazione mancante")
        with _StoragePrivato():
            response = views.allegato_carica(_ajax(self.user, {"file": self._pdf()}), self.audit.pk, esito.pk)
            self.assertEqual(response.status_code, 200)
            corpo = json.loads(response.content)
            self.assertEqual(corpo["nome"], "campione.pdf")
            self.assertTrue(corpo["rilievo_emesso"])
            duplicato = views.allegato_carica(_ajax(self.user, {"file": self._pdf()}), self.audit.pk, esito.pk)
        self.assertEqual(duplicato.status_code, 409)
        esito.refresh_from_db()
        self.assertIsNotNone(esito.ofi_id)

    def test_file_non_valido_400_json(self, _executor):
        with _StoragePrivato():
            response = views.allegato_carica(_ajax(self.user, {"file": self._pdf("falso.pdf", b"<html>x</html>")}), self.audit.pk, self.esiti[0].pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errore", json.loads(response.content))

    def test_primo_file_scelto_tra_foto_e_file(self, _executor):
        vuoto = SimpleUploadedFile("foto.jpg", b"", content_type="image/jpeg")
        with _StoragePrivato():
            response = views.allegato_carica(_ajax(self.user, {"file": [vuoto, self._pdf()]}), self.audit.pk, self.esiti[0].pk)
        self.assertEqual(response.status_code, 200)


class UploadPermessiJsonTests(EsecuzioneBase):
    def test_anonimo_401_e_non_assegnato_403_in_json(self):
        request = _ajax(self.user, {})
        request.user = AnonymousUser()
        self.assertEqual(views.allegato_carica(request, self.audit.pk, self.esiti[0].pk).status_code, 401)
        with patch("sistema_gestione.automation_views._assigned_executor", return_value=False):
            negato = views.allegato_carica(_ajax(self.user, {}), self.audit.pk, self.esiti[0].pk)
        self.assertEqual(negato.status_code, 403)
        self.assertEqual(negato["Content-Type"], "application/json")
