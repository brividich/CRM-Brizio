"""Robustezza del modulo visite mediche: integrità dei dati sanitari, permessi, audit.

Dati sintetici: id e nomi inventati, nessun dato reale.
"""
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from .models import (
    AnagraficaVisiteMedichePermission,
    DipendenteAnagraficaCivile,
    TipoVisitaMedica,
    VisitaMedica,
    VisitaSessione,
)

_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _crea_dipendenti(*ids):
    """Righe sintetiche nella tabella legacy anagrafica_dipendenti, con id espliciti."""
    from .tests import _ensure_anagrafica_table

    _ensure_anagrafica_table()
    with connection.cursor() as cursor:
        for i in ids:
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (id, aliasusername, nome, cognome, attivo)"
                " VALUES (%s, %s, %s, %s, %s)",
                [i, f"sint.{i}", "Nome", f"Sintetico{i}", 1],
            )


def _pdf(nome="referto.pdf"):
    return SimpleUploadedFile(nome, _PDF, content_type="application/pdf")


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            username="vr_admin", email="vr_admin@example.test", password="x",
        )
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica VR", durata_mesi=12, categoria="Visita VR")
        self.tipo_bis = TipoVisitaMedica.objects.create(nome="Biennale VR", durata_mesi=24, categoria="Visita VR")
        self.tipo_altro = TipoVisitaMedica.objects.create(nome="Audiometria VR", durata_mesi=12)
        _crea_dipendenti(9101, 9102)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ctx = override_settings(ANAGRAFICA_PRIVATE_ROOT=self.tmp.name)
        ctx.enable()
        self.addCleanup(ctx.disable)


class RefertoSostituitoTests(_Base):
    def test_nuovo_referto_conserva_il_precedente(self):
        add = self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[9101]),
            {"tipo": self.tipo.pk, "data_svolgimento": (self.oggi - timedelta(days=3)).isoformat(),
             "esito": "IDONEO", "referto_file": _pdf("primo.pdf")},
        )
        self.assertEqual(add.status_code, 302)
        visita = VisitaMedica.objects.get(legacy_anagrafica_id=9101)
        vecchio = visita.referto_documento
        self.assertIsNotNone(vecchio)
        nome_file = vecchio.file.name

        self.client.post(
            reverse("anagrafica:dipendente_visita_edit", args=[9101, visita.pk]),
            {"tipo": self.tipo.pk, "data_svolgimento": visita.data_svolgimento.isoformat(),
             "esito": "IDONEO", "referto_file": _pdf("secondo.pdf")},
        )
        visita.refresh_from_db()
        self.assertNotEqual(visita.referto_documento_id, vecchio.pk)
        vecchio.refresh_from_db()  # esiste ancora
        self.assertTrue(vecchio.file.storage.exists(nome_file))
        self.assertEqual(vecchio.oggetto_riferimento_id, visita.pk)
        self.assertTrue(vecchio.descrizione.startswith("[Sostituito"))
        audit = AuditLog.objects.get(azione="REFERTO_SOSTITUITO")
        self.assertEqual(audit.dettaglio["referto_sostituito_id"], vecchio.pk)

    def test_modifica_registra_le_differenze_senza_copiare_i_testi(self):
        visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=self.oggi - timedelta(days=5),
        )
        self.client.post(
            reverse("anagrafica:dipendente_visita_edit", args=[9101, visita.pk]),
            {"tipo": self.tipo.pk, "data_svolgimento": visita.data_svolgimento.isoformat(),
             "esito": "IDONEO_PRESCR", "prescrizioni": "Testo clinico sintetico"},
        )
        audit = AuditLog.objects.get(azione="VISITA_MEDICA_MODIFICATA")
        modifiche = audit.dettaglio["modifiche"]
        self.assertEqual(modifiche["esito"], {"prima": "IDONEO", "dopo": "IDONEO_PRESCR"})
        self.assertEqual(modifiche["prescrizioni"], "modificato")
        self.assertNotIn("Testo clinico sintetico", str(audit.dettaglio))


class RegistrazioneAtomicaTests(_Base):
    def test_errore_sul_referto_non_lascia_visite_orfane(self):
        with patch("anagrafica.views._salva_referto_visita", side_effect=RuntimeError("storage giù")):
            self.client.post(
                reverse("anagrafica:dipendente_visita_add", args=[9101]),
                {"tipo": self.tipo.pk, "data_svolgimento": self.oggi.isoformat(),
                 "esito": "IDONEO", "referto_file": _pdf()},
            )
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).exists())

    def test_dipendente_inesistente_rifiutato(self):
        self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[999999]),
            {"tipo": self.tipo.pk, "data_svolgimento": self.oggi.isoformat(), "esito": "IDONEO"},
        )
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=999999).exists())

    def test_data_anteriore_alla_nascita_rifiutata(self):
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=9101, data_nascita=date(2000, 5, 1))
        self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[9101]),
            {"tipo": self.tipo.pk, "data_svolgimento": "1999-01-01", "esito": "IDONEO"},
        )
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).exists())

    def test_stessa_famiglia_stesso_giorno_e_un_doppione(self):
        giorno = self.oggi - timedelta(days=2)
        VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=giorno)
        self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[9101]),
            {"tipo": self.tipo_bis.pk, "data_svolgimento": giorno.isoformat(), "esito": "IDONEO"},
        )
        self.assertEqual(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).count(), 1)


class VincoloUnicoTests(_Base):
    def test_doppione_attivo_vietato_dal_database(self):
        giorno = self.oggi - timedelta(days=1)
        VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=giorno)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=giorno)

    def test_superata_non_conta_e_non_si_ripristina_sopra_l_attiva(self):
        giorno = self.oggi - timedelta(days=1)
        superata = VisitaMedica.objects.create(
            legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=giorno,
            superata_il=timezone.now(), superata_motivo="doppione sintetico",
        )
        VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=giorno)
        self.client.post(reverse("anagrafica:visita_medica_superata", args=[superata.pk]), {"azione": "ripristina"})
        superata.refresh_from_db()
        self.assertIsNotNone(superata.superata_il)


class GiornataVisiteTests(_Base):
    def _post(self, righe: dict):
        data = {"data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(), "medico_competente": "Dr. Sintetico"}
        data.update(righe)
        return self.client.post(reverse("anagrafica:visite_mediche_nuova_sessione"), data)

    def test_limitazioni_senza_note_non_registrate(self):
        t = self.tipo_altro.pk
        self._post({f"sel_9101_{t}": "1", f"esito_9101_{t}": "IDONEO_LIM", f"note_9101_{t}": ""})
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).exists())
        self.assertFalse(VisitaSessione.objects.exists())

    def test_id_inesistente_scartato_gli_altri_registrati(self):
        t = self.tipo_altro.pk
        self._post({f"sel_9101_{t}": "1", f"esito_9101_{t}": "IDONEO",
                    f"sel_888888_{t}": "1", f"esito_888888_{t}": "IDONEO"})
        self.assertTrue(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).exists())
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=888888).exists())

    def test_due_tipi_della_stessa_famiglia_nello_stesso_invio(self):
        a, b = self.tipo.pk, self.tipo_bis.pk
        self._post({f"sel_9101_{a}": "1", f"esito_9101_{a}": "IDONEO",
                    f"sel_9101_{b}": "1", f"esito_9101_{b}": "IDONEO"})
        self.assertEqual(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).count(), 1)


class PartecipanteGiornataTests(_Base):
    def setUp(self):
        super().setUp()
        self.sess = VisitaSessione.objects.create(data_svolgimento=self.oggi - timedelta(days=1))
        self.url = reverse("anagrafica:visite_mediche_sessione_partecipante_add", args=[self.sess.pk])

    def test_id_vuoto_o_inesistente_rifiutato(self):
        self.client.post(self.url, {"legacy_id": "", "tipo_id": self.tipo.pk, "esito": "IDONEO"})
        self.client.post(self.url, {"legacy_id": "777777", "tipo_id": self.tipo.pk, "esito": "IDONEO"})
        self.assertFalse(VisitaMedica.objects.exists())

    def test_aggiunta_valida_con_audit(self):
        self.client.post(self.url, {"legacy_id": "9102", "tipo_id": self.tipo.pk, "esito": "IDONEO"})
        visita = VisitaMedica.objects.get(legacy_anagrafica_id=9102)
        self.assertEqual(visita.sessione_id, self.sess.pk)
        self.assertTrue(AuditLog.objects.filter(azione="VISITA_MEDICA_CREATA", oggetto_id=str(visita.pk)).exists())

    def test_limitazioni_richiedono_note(self):
        self.client.post(self.url, {"legacy_id": "9102", "tipo_id": self.tipo.pk, "esito": "IDONEO_LIM"})
        self.assertFalse(VisitaMedica.objects.exists())


class PermessoModificaTests(TestCase):
    def setUp(self):
        self.utente = get_user_model().objects.create_user(username="vr_lettore", password="x")
        self.rf = RequestFactory()

    def _req(self):
        request = self.rf.get("/")
        request.user = self.utente
        return request

    def test_default_storico_chi_vede_modifica(self):
        from .views import _can_edit_visite_mediche

        with patch("anagrafica.views._can_view_visite_mediche", return_value=True), \
                patch("anagrafica.views._has_canonical_grant", return_value=False):
            self.assertTrue(_can_edit_visite_mediche(self._req()))

    def test_con_permesso_separato_serve_il_grant(self):
        from .views import _can_edit_visite_mediche

        perm = AnagraficaVisiteMedichePermission.get_instance()
        perm.richiedi_permesso_modifica = True
        perm.save()
        with patch("anagrafica.views._can_view_visite_mediche", return_value=True), \
                patch("anagrafica.views._has_canonical_grant", return_value=False):
            self.assertFalse(_can_edit_visite_mediche(self._req()))
        with patch("anagrafica.views._can_view_visite_mediche", return_value=True), \
                patch("anagrafica.views._has_canonical_grant", return_value=True):
            self.assertTrue(_can_edit_visite_mediche(self._req()))

    def test_senza_accesso_niente_modifica(self):
        from .views import _can_edit_visite_mediche

        with patch("anagrafica.views._can_view_visite_mediche", return_value=False):
            self.assertFalse(_can_edit_visite_mediche(self._req()))


class AuditConsultazioneTests(_Base):
    def test_dettaglio_tracciato_una_volta_all_ora(self):
        visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=9101, tipo=self.tipo, data_svolgimento=self.oggi - timedelta(days=4),
        )
        url = reverse("anagrafica:visita_medica_dettaglio", args=[visita.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            AuditLog.objects.filter(azione="VISITA_MEDICA_VISUALIZZATA", oggetto_id=str(visita.pk)).count(), 1,
        )

    def test_eliminazione_giornata_tracciata(self):
        sess = VisitaSessione.objects.create(data_svolgimento=self.oggi - timedelta(days=1))
        self.client.post(reverse("anagrafica:visite_mediche_sessione_delete", args=[sess.pk]))
        self.assertTrue(AuditLog.objects.filter(azione="VISITA_SESSIONE_ELIMINATA").exists())


class CatalogoTipiTests(_Base):
    def test_periodicita_fuori_intervallo_rifiutata(self):
        self.client.post(reverse("anagrafica:tipo_visita_medica_create"), {"nome": "Fuori scala VR", "durata_mesi": "999"})
        self.assertFalse(TipoVisitaMedica.objects.filter(nome="Fuori scala VR").exists())
        self.client.post(reverse("anagrafica:tipo_visita_medica_create"), {"nome": "Testo VR", "durata_mesi": "dodici"})
        self.assertFalse(TipoVisitaMedica.objects.filter(nome="Testo VR").exists())

    def test_modifica_massiva_chiede_il_ricalcolo(self):
        with patch("anagrafica.services.scadenze.ricalcola_dopo_commit") as ricalcola:
            self.client.post(reverse("anagrafica:tipo_visita_medica_bulk_edit"),
                             {"ids": [self.tipo_altro.pk], "obbligatoria": "0"})
        ricalcola.assert_any_call(None)


class ServiziTests(_Base):
    def test_ultime_visite_per_tipo(self):
        from .services.visite import ultime_visite_per_tipo

        vecchia = VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo_altro,
                                              data_svolgimento=self.oggi - timedelta(days=400))
        recente = VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo_altro,
                                              data_svolgimento=self.oggi - timedelta(days=10))
        self.assertEqual(ultime_visite_per_tipo(9101)[self.tipo_altro.pk].pk, recente.pk)
        self.assertNotEqual(vecchia.pk, recente.pk)

    def test_save_con_update_fields_non_tocca_la_nota_di_scadenza(self):
        visita = VisitaMedica.objects.create(legacy_anagrafica_id=9101, tipo=self.tipo_altro,
                                             data_svolgimento=self.oggi - timedelta(days=10))
        VisitaMedica.objects.filter(pk=visita.pk).update(scadenza_nota="anticipata dalla mansione")
        visita.refresh_from_db()
        visita.note = "nota sintetica"
        visita.save(update_fields=["note", "updated_at"])
        self.assertEqual(visita.scadenza_nota, "anticipata dalla mansione")


class ValidateDeploymentVisiteTests(TestCase):
    def test_accesso_tutti_segnalato(self):
        from core.management.commands.validate_deployment import DeploymentValidator, OK

        perm = AnagraficaVisiteMedichePermission.get_instance()
        perm.accesso = AnagraficaVisiteMedichePermission.ACCESSO_TUTTI
        perm.save()
        validator = DeploymentValidator()
        validator.check_security()
        voce = next(r for r in validator.results if r.name == "VISITE_MEDICHE_ACCESSO")
        self.assertNotEqual(voce.severity, OK)
