from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import RegistroRifiuti

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriWriteAuthorizationTests(TestCase):
    """SEC-PREPROD-02 (M3): scrittura del registro RENTRI riservata ai gestori."""

    def setUp(self):
        self.basic = User.objects.create_user(
            username="rentri-basic", email="rentri-basic@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.basic, completed=True, completed_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            username="rentri-admin", email="rentri-admin@example.com", password="pwd12345",
        )

    def test_basic_user_cannot_create_via_carico(self):
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RegistroRifiuti.objects.count(), 0)

    def test_admin_can_create_via_carico(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RegistroRifiuti.objects.filter(tipo="C").count(), 1)

    def test_basic_user_cannot_modify(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_modifica", args=[registro.pk]),
            data='{"data": "2026-06-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_admin_can_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_delete_rejects_get(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_basic_user_cannot_import_confirm(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_import_confirm"))
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_trigger_sync_pull(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_api_sync_pull"))
        self.assertEqual(response.status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriScadenzarioTests(TestCase):
    """#7 — scadenzario adempimenti RENTRI (FIR mancanti / da comunicare / bozze)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="rentri-sc", email="rentri-sc@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now(),
        )
        self.client.force_login(self.user)
        # scarico senza FIR → finisce in "FIR mancante"
        self.fir_mancante = RegistroRifiuti.objects.create(
            tipo="O", data=date(2026, 5, 1), salva=True, rentri_si_no=True, arrivo_fir="",
        )
        # scarico CON FIR → NON deve comparire tra i FIR mancanti
        RegistroRifiuti.objects.create(
            tipo="O", data=date(2026, 5, 2), salva=True, rentri_si_no=True, arrivo_fir="FIR-2026-1",
        )
        # carico senza FIR → escluso (il FIR riguarda gli scarichi)
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 3), salva=True, arrivo_fir="")
        # consolidato ma non trasmesso → "da comunicare"
        self.da_comunicare = RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 5, 4), salva=True, rentri_si_no=False, arrivo_fir="x",
        )
        # bozza non salvata → "bozze"
        self.bozza = RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 5, 5), salva=False, arrivo_fir="x",
        )

    def _bucket(self, sections, key):
        return next(s for s in sections if s["key"] == key)

    def test_buckets_classify_records(self):
        from rentri.views import _scadenzario_buckets

        sections = _scadenzario_buckets(date(2026, 6, 1))
        fir_pks = [r["pk"] for r in self._bucket(sections, "fir")["rows"]]
        com_pks = [r["pk"] for r in self._bucket(sections, "comunicare")["rows"]]
        boz_pks = [r["pk"] for r in self._bucket(sections, "bozze")["rows"]]

        self.assertEqual(fir_pks, [self.fir_mancante.pk])
        self.assertIn(self.da_comunicare.pk, com_pks)
        self.assertIn(self.bozza.pk, boz_pks)

    def test_page_renders(self):
        response = self.client.get(reverse("rentri_scadenzario"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scadenzario adempimenti RENTRI")
        self.assertContains(response, "FIR mancante")

    def test_csv_export(self):
        response = self.client.get(reverse("rentri_scadenzario"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Adempimento", body)
        self.assertIn("FIR mancante", body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriGiacenzeTests(TestCase):
    """R1 — giacenze per CER + semaforo deposito temporaneo."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="rentri-gi", email="rentri-gi@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            username="rentri-gi-admin", email="rentri-gi-admin@example.com", password="pwd12345",
        )

    def _g(self, codice):
        from rentri.giacenze import giacenze_per_cer
        return next(g for g in giacenze_per_cer() if g.codice == codice)

    def test_giacenza_carico_meno_scarico(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 2, 5), codice="150106", quantita=30)
        g = self._g("150106")
        self.assertEqual(g.entrate, 100)
        self.assertEqual(g.uscite, 30)
        self.assertEqual(g.giacenza, 70)
        self.assertTrue(g.aperta)

    def test_rettifica_riduce_giacenza(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="160601", quantita=50)
        RegistroRifiuti.objects.create(tipo="R", data=date(2026, 2, 5), codice="160601", quantita=20)
        self.assertEqual(self._g("160601").giacenza, 30)

    def test_scarico_originale_non_muove_giacenza(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="170405", quantita=80)
        RegistroRifiuti.objects.create(tipo="O", data=date(2026, 2, 5), codice="170405", quantita=80)
        # O è pianificato: la giacenza resta pari al solo carico
        self.assertEqual(self._g("170405").giacenza, 80)

    def test_pericoloso_flag(self):
        RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 1, 5), codice="150202", quantita=10, pericolosita="HP04",
        )
        self.assertTrue(self._g("150202").pericoloso)

    def test_semaforo_oltre_soglia(self):
        vecchio = timezone.localdate() - timedelta(days=120)
        RegistroRifiuti.objects.create(tipo="C", data=vecchio, codice="080111", quantita=40)
        from rentri.giacenze import soglie_deposito
        g = self._g("080111")
        self.assertGreaterEqual(g.giorni_giacenza, 120)
        self.assertEqual(g.tono(soglie_deposito()), "rosso")

    def test_giacenza_azzerata_e_chiusa(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="200101", quantita=25)
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 2, 5), codice="200101", quantita=25)
        from rentri.giacenze import soglie_deposito
        g = self._g("200101")
        self.assertFalse(g.aperta)
        self.assertIsNone(g.giorni_giacenza)
        self.assertEqual(g.tono(soglie_deposito()), "chiuso")

    def test_view_renders(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        self.client.force_login(self.user)
        response = self.client.get(reverse("rentri_giacenze"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Giacenze per CER")
        self.assertContains(response, "150106")

    def test_view_csv_export(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        self.client.force_login(self.user)
        response = self.client.get(reverse("rentri_giacenze"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Codice EER", body)
        self.assertIn("150106", body)

    def test_provider_include_deposito(self):
        vecchio = timezone.localdate() - timedelta(days=100)
        RegistroRifiuti.objects.create(tipo="C", data=vecchio, codice="080111", quantita=40)
        from dashboard.scadenze_providers import ScadenzeContext, collect_rentri

        req = RequestFactory().get("/")
        req.user = self.admin
        items = collect_rentri(ScadenzeContext.build(req))
        depositi = [it for it in items if it.kind == "deposito"]
        self.assertTrue(any(it.soggetto == "080111" for it in depositi))


class RentriCsvParsingTests(TestCase):
    @staticmethod
    def _csv_content(delimiter: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter)
        writer.writerow([
            "Data", "ID", "Codice", "Pericolosita", "Quantita",
            "Rettifica", "Tipo", "Note", "Modificato da", "Rif.Op",
        ])
        writer.writerow([
            "01/09/2026", "REG-1", "15 02 02", '["HP04 - Irritante","HP05 - Nocivo","HP04"]',
            "1.234,5", "", "C - Carico", "Nota", "utente", "OP/1",
        ])
        return output.getvalue()

    def test_parser_accetta_csv_con_virgola_e_lista_hp(self):
        from rentri.views import _parse_csv_rows

        rows, errors = _parse_csv_rows(self._csv_content(","))

        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pericolosita"], "HP04, HP05")
        self.assertEqual(rows[0]["quantita"], "1234.5")

    def test_parser_conserva_compatibilita_con_punto_e_virgola(self):
        from rentri.views import _parse_csv_rows

        rows, errors = _parse_csv_rows(self._csv_content(";"))

        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["id_reg"], "REG-1")

    def test_helper_cli_rilevano_delimitatore_e_codici_hp(self):
        from rentri.management.commands.import_rentri_csv import (
            _detect_delimiter,
            _parse_pericolosita,
        )

        self.assertEqual(_detect_delimiter("Data,ID,Codice"), ",")
        self.assertEqual(_detect_delimiter("Data;ID;Codice"), ";")
        self.assertEqual(_detect_delimiter("intestazione"), ";")
        self.assertEqual(_parse_pericolosita('["HP04 - x","HP05 - y","HP04"]'), "HP04, HP05")


class RentriFamiglieTests(TestCase):
    """Vista famiglie: risalita della catena rif_op, fusione e stato aperta/chiusa."""

    def _rec(self, tipo, giorno, id_reg, rif_op="", codice="12.01.01"):
        return RegistroRifiuti.objects.create(
            tipo=tipo, data=date(2026, 1, giorno), id_registrazione=id_reg,
            rif_op=rif_op, codice=codice,
        )

    def _famiglie(self):
        from .views import _build_families
        return _build_families(list(RegistroRifiuti.objects.order_by("data", "id_registrazione")))

    def test_catena_indiretta_resta_nella_famiglia(self):
        """M ed R possono referenziare il genitore (O / M) invece del carico."""
        self._rec("C", 1, "2026/001")
        self._rec("O", 2, "2026/002", rif_op="2026/001")
        self._rec("M", 3, "2026/003", rif_op="2026/002")
        self._rec("R", 4, "2026/004", rif_op="2026/003")

        famiglie = self._famiglie()
        self.assertEqual(len(famiglie), 1)
        self.assertEqual(len(famiglie[0]["carichi"]), 1)
        self.assertEqual(len(famiglie[0]["operazioni"]), 3)
        self.assertTrue(famiglie[0]["chiusa"])

    def test_riferimento_multiplo_fonde_le_famiglie(self):
        """Un rif_op parziale e uno multiplo sullo stesso carico restano una famiglia."""
        self._rec("C", 1, "2026/001")
        self._rec("C", 1, "2026/002")
        self._rec("O", 2, "2026/003", rif_op="2026/001")
        self._rec("R", 3, "2026/004", rif_op="2026/001, 2026/002")

        famiglie = self._famiglie()
        self.assertEqual(len(famiglie), 1)
        self.assertEqual(len(famiglie[0]["carichi"]), 2)
        self.assertEqual(len(famiglie[0]["operazioni"]), 2)

    def test_operazione_senza_carico_resta_orfana(self):
        self._rec("O", 2, "2026/010", rif_op="2026/999")

        famiglie = self._famiglie()
        self.assertEqual(len(famiglie), 1)
        self.assertEqual(famiglie[0]["carichi"], [])
        self.assertFalse(famiglie[0]["chiusa"])

    def test_famiglia_chiusa_va_in_fondo(self):
        self._rec("C", 1, "2026/001")
        self._rec("O", 2, "2026/002", rif_op="2026/001")
        self._rec("M", 3, "2026/003", rif_op="2026/002")
        self._rec("C", 5, "2026/004", codice="12.01.03")

        famiglie = self._famiglie()
        self.assertEqual([f["chiusa"] for f in famiglie], [False, True])
        self.assertEqual(famiglie[0]["codice"], "12.01.03")

    def test_catena_ciclica_non_va_in_ricorsione(self):
        self._rec("C", 1, "2026/001")
        self._rec("O", 2, "2026/002", rif_op="2026/003")
        self._rec("M", 3, "2026/003", rif_op="2026/002")

        famiglie = self._famiglie()
        self.assertEqual(sum(len(f["carichi"]) + len(f["operazioni"]) for f in famiglie), 3)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriElencoFiltroStatoTests(TestCase):
    """Filtro `stato` dell'elenco (solo vista famiglie)."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="rentri-stato", email="rentri-stato@example.com", password="pwd12345",
        )
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 1), id_registrazione="2026/001", codice="12.01.01")
        RegistroRifiuti.objects.create(tipo="O", data=date(2026, 1, 2), id_registrazione="2026/002", rif_op="2026/001", codice="12.01.01")
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 1, 3), id_registrazione="2026/003", rif_op="2026/002", codice="12.01.01")
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), id_registrazione="2026/004", codice="12.01.03")
        self.client.force_login(self.user)

    def test_conteggi_aperte_chiuse(self):
        response = self.client.get(reverse("rentri_elenco"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["n_aperte"], 1)
        self.assertEqual(response.context["n_chiuse"], 1)

    def test_filtro_solo_aperte(self):
        response = self.client.get(reverse("rentri_elenco"), {"stato": "aperte"})
        famiglie = response.context["families"]
        self.assertEqual(len(famiglie), 1)
        self.assertFalse(famiglie[0]["chiusa"])

    def test_filtro_solo_chiuse(self):
        response = self.client.get(reverse("rentri_elenco"), {"stato": "chiuse"})
        famiglie = response.context["families"]
        self.assertEqual(len(famiglie), 1)
        self.assertTrue(famiglie[0]["chiusa"])


class RentriNumerazioneTests(TestCase):
    """Il progressivo del registro si alloca da un contatore, non da COUNT(*)."""

    def _rec(self, giorno, id_reg=""):
        return RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 3, giorno), id_registrazione=id_reg, codice="12.01.01",
        )

    def test_numeri_progressivi_consecutivi(self):
        self.assertEqual(self._rec(1).id_registrazione, "2026/001")
        self.assertEqual(self._rec(2).id_registrazione, "2026/002")
        self.assertEqual(self._rec(3).id_registrazione, "2026/003")

    def test_eliminazione_non_fa_riciclare_il_numero(self):
        self._rec(1)
        secondo = self._rec(2)
        self._rec(3)
        secondo.delete()

        nuovo = self._rec(4)
        self.assertEqual(nuovo.id_registrazione, "2026/004")
        self.assertEqual(RegistroRifiuti.objects.filter(id_registrazione="2026/002").count(), 0)

    def test_contatore_riparte_dal_massimo_storico(self):
        """Con storico importato il contatore non deve ripartire da 1."""
        self._rec(1, id_reg="2026/1847")

        self.assertEqual(self._rec(2).id_registrazione, "2026/1848")

    def test_non_riempie_i_buchi_e_salta_gli_occupati(self):
        """La sequenza riparte dal massimo: un buco non si riempie, un numero occupato si salta."""
        self._rec(1, id_reg="2026/002")
        self.assertEqual(self._rec(2).id_registrazione, "2026/003")

        RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 3, 4), id_registrazione="2026/004", codice="12.01.01",
        )
        self.assertEqual(self._rec(5).id_registrazione, "2026/005")

    def test_anteprima_non_consuma_il_numero(self):
        from .numerazione import anteprima_id_registrazione

        self._rec(1)
        self.assertEqual(anteprima_id_registrazione(2026), "2026/002")
        self.assertEqual(anteprima_id_registrazione(2026), "2026/002")
        self.assertEqual(self._rec(2).id_registrazione, "2026/002")

    def test_id_esplicito_resta_intatto(self):
        """L'import CSV impone il proprio id: non deve essere riscritto."""
        self.assertEqual(self._rec(1, id_reg="STORICO-9").id_registrazione, "STORICO-9")

    def test_anni_diversi_hanno_sequenze_indipendenti(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2025, 12, 31), codice="12.01.01")
        nuovo = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 2), codice="12.01.01")
        self.assertEqual(nuovo.id_registrazione, "2026/001")


class RentriIdDuplicatiTests(TestCase):
    """Audit dei numeri duplicati: coppia R+M voluta vs anomalia."""

    def setUp(self):
        RegistroRifiuti.objects.create(tipo="R", data=date(2026, 4, 1), id_registrazione="2026/010", codice="12.01.01")
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 4, 1), id_registrazione="2026/010", codice="12.01.01")
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 4, 2), id_registrazione="2026/011", codice="13.02.08")
        RegistroRifiuti.objects.create(tipo="O", data=date(2026, 5, 9), id_registrazione="2026/011", codice="12.01.09")
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 4, 3), id_registrazione="2026/012", codice="12.01.01")

    def test_classifica_coppie_e_anomalie(self):
        from .numerazione import id_duplicati

        gruppi = id_duplicati()
        self.assertEqual(len(gruppi), 2)
        anomalie = [g for g in gruppi if not g["coppia_rm"]]
        self.assertEqual([g["id_registrazione"] for g in anomalie], ["2026/011"])
        self.assertEqual(anomalie[0]["codici"], ["12.01.09", "13.02.08"])

    def test_comando_solo_anomalie(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("rentri_id_duplicati", "--solo-anomalie", stdout=out)
        testo = out.getvalue()
        self.assertIn("2026/011", testo)
        self.assertNotIn("2026/010", testo)
