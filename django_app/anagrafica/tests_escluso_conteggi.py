"""Flag «Escludi dai conteggi dell'organico» e dati anagrafici modificabili.

La persona resta in anagrafica ma non entra in persone in forza, turnover,
organico per reparto e indici. Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_anagrafica import fetch_anagrafica_rows
from core.models import AuditLog

from anagrafica.forms import AnagraficaAziendaleForm
from anagrafica.models import DipendenteAnagraficaAziendale
from anagrafica.reportistica import sezioni as catalogo
from anagrafica.reportistica.dati import Contesto, Dipendente, Perimetro
from anagrafica.services.conteggi_organico import esclusi_dai_conteggi_ids, righe_in_organico
from anagrafica.tests import _ensure_anagrafica_table

User = get_user_model()

OGGI = timezone.localdate()


def _persone() -> list[Dipendente]:
    vecchio = OGGI - timedelta(days=3000)
    return [
        Dipendente(id=951, nominativo="ALFA UNO", reparto="Produzione", contratto="INDETERMINATO",
                   data_assunzione=vecchio, genere="F"),
        Dipendente(id=952, nominativo="BETA DUE", reparto="Produzione", contratto="INDETERMINATO",
                   data_assunzione=vecchio, genere="M"),
        # Amministratore: in anagrafica, fuori dai conteggi.
        Dipendente(id=953, nominativo="GAMMA TRE", reparto="Direzione", contratto="ALTRO",
                   data_assunzione=OGGI - timedelta(days=20), genere="M", escluso_conteggi=True),
    ]


class ReportisticaEsclusiTest(TestCase):
    def setUp(self):
        p = patch("anagrafica.reportistica.dati.carica_dipendenti", side_effect=_persone)
        p.start()
        self.addCleanup(p.stop)

    def ctx(self) -> Contesto:
        return Contesto(date_from=OGGI - timedelta(days=365), date_to=OGGI,
                        perimetro=Perimetro.from_dict({}), today=OGGI)

    def test_organico_e_turnover_senza_esclusi(self):
        res = catalogo.get("organico_indicatori").calcola(self.ctx())
        kpi = {k.label: k.value for k in res.kpis}
        self.assertEqual(kpi["Persone in forza"], 2)
        self.assertEqual(kpi["Assunzioni nel periodo"], 0)
        self.assertTrue(any("Escluse dai conteggi" in n and "1 persone" in n for n in res.note))
        reparti = {r["voce"] for r in res.righe if r["dimensione"] == "Reparto"}
        self.assertNotIn("Direzione", reparti)

    def test_parita_genere_senza_esclusi(self):
        res = catalogo.get("pdr125_indicatori").calcola(self.ctx())
        organico = next(r for r in res.righe if r["indicatore"] == "Persone in forza")
        self.assertEqual(organico["totale"], 2)

    def test_escluso_resta_negli_elenchi(self):
        self.assertIn(953, self.ctx().ids())


class ConteggiOrganicoServiceTest(TestCase):
    def test_righe_legacy_escluse_anche_via_id_fuso(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=962, escluso_dai_conteggi=True)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=963)
        self.assertEqual(esclusi_dai_conteggi_ids(), {962})
        rows = [{"id": 961, "_merged_ids": [962]}, {"id": 963}, {"id": 964}]
        self.assertEqual([r["id"] for r in righe_in_organico(rows)], [963, 964])

    def test_nessun_escluso_lascia_tutto(self):
        rows = [{"id": 1}, {"id": 2}]
        self.assertEqual(righe_in_organico(rows, set()), rows)


class FormEsclusioneTest(TestCase):
    def test_motivo_svuotato_se_non_escluso(self):
        form = AnagraficaAziendaleForm(data={"motivo_esclusione_conteggi": "RSPP esterno"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["motivo_esclusione_conteggi"], "")

    def test_flag_e_motivo_salvati(self):
        form = AnagraficaAziendaleForm(data={"escluso_dai_conteggi": "on", "motivo_esclusione_conteggi": "Amministratore"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["escluso_dai_conteggi"])
        self.assertEqual(form.cleaned_data["motivo_esclusione_conteggi"], "Amministratore")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DatiBaseModificabiliTest(TestCase):
    """Nome, cognome ed email per le notifiche si correggono dalla scheda."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(username="db_admin", email="db_admin@x.local", password="x")
        cls.semplice = User.objects.create_user(username="db_semplice", email="db_semplice@x.local", password="x")

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) VALUES (%s, %s, %s, %s)",
                ["m.prova", "MARIO", "PROVA", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["m.prova"])
            self.legacy_id = int(cursor.fetchone()[0])
        self.url = reverse("anagrafica:dipendente_dati_base_set", args=[self.legacy_id])

    def _riga(self) -> dict:
        return fetch_anagrafica_rows(ids=[self.legacy_id])[0]

    def test_admin_corregge_nome_e_cognome(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {"nome": "Marco", "cognome": "Prova Rossi"})
        self.assertEqual(resp.status_code, 302)
        riga = self._riga()
        self.assertEqual((riga["nome"], riga["cognome"]), ("MARCO", "PROVA ROSSI"))
        self.assertTrue(AuditLog.objects.filter(azione="DIPENDENTE_DATI_ANAGRAFICI_MODIFICATI").exists())

    def test_nome_vuoto_rifiutato(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {"nome": "  ", "cognome": "Prova"})
        self.assertEqual(self._riga()["nome"], "MARIO")

    def test_email_notifica_validata_e_salvata(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {"email_notifica": "non-una-mail"})
        self.assertFalse(self._riga().get("email_notifica"))
        self.client.post(self.url, {"email_notifica": "m.prova@example.com"})
        self.assertEqual(self._riga()["email_notifica"], "m.prova@example.com")

    def test_senza_permessi_non_modifica(self):
        self.client.force_login(self.semplice)
        self.client.post(self.url, {"nome": "Hacker"})
        self.assertEqual(self._riga()["nome"], "MARIO")

    def test_matricola_dal_blocco_identita(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {"nome": "Mario", "cognome": "Prova", "matricola": "CNO 0042"})
        self.assertIn("#anagrafica-aziendale", resp["Location"])
        self.assertEqual(self._riga()["matricola"], "CNO 0042")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PannelloModificaAziendaleTest(TestCase):
    """Il pannello «Modifica» salva in un colpo dati aziendali, nome, matricola e username."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(username="pan_admin", email="pan_admin@x.local", password="x")
        cls.semplice = User.objects.create_user(username="pan_semplice", email="pan_semplice@x.local", password="x")

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) VALUES (%s, %s, %s, %s)",
                ["m.prova", "MARIO", "PROVA", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["m.prova"])
            self.legacy_id = int(cursor.fetchone()[0])
        self.az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.legacy_id, badge="412", taglia_scarpe="43", capo_eccezione_legacy_id=77,
        )
        self.url = reverse("anagrafica:dipendente_aziendale_save", args=[self.legacy_id])

    def _dati(self, **extra) -> dict:
        dati = {"nome": "Mario", "cognome": "Prova", "matricola": "", "aliasusername": "m.prova",
                "email_notifica": "", "badge": "412", "taglia_scarpe": "43"}
        dati.update(extra)
        return dati

    def test_salva_tutto_insieme(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, self._dati(
            nome="Marco", matricola="CNO 0042", aliasusername="m.prova2", taglia_scarpe="44",
        ))
        self.assertIn("#anagrafica-aziendale", resp["Location"])
        riga = fetch_anagrafica_rows(ids=[self.legacy_id])[0]
        # Nome e username scritti in due passi: nessuno dei due annulla l'altro.
        self.assertEqual((riga["nome"], riga["matricola"], riga["aliasusername"]), ("MARCO", "CNO 0042", "m.prova2"))
        self.az.refresh_from_db()
        self.assertEqual((self.az.taglia_scarpe, self.az.badge), ("44", "412"))
        self.assertEqual(self.az.capo_eccezione_legacy_id, 77)
        log = AuditLog.objects.get(azione="DIPENDENTE_ANAGRAFICA_AZIENDALE_MODIFICATA")
        self.assertEqual(set(log.dettaglio["modifiche"]), {"taglia_scarpe"})

    def test_nome_vuoto_non_salva_niente(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, self._dati(nome=" ", taglia_scarpe="44"))
        self.az.refresh_from_db()
        self.assertEqual(self.az.taglia_scarpe, "43")
        self.assertEqual(fetch_anagrafica_rows(ids=[self.legacy_id])[0]["nome"], "MARIO")

    def test_schede_coprono_tutto_il_form(self):
        from anagrafica.forms import AZIENDALE_SCHEDE
        campi_schede = [c for _titolo, campi in AZIENDALE_SCHEDE.values() for c in campi]
        self.assertCountEqual(campi_schede, list(AnagraficaAziendaleForm().fields))

    def test_campi_tecnici_e_cessazione_fuori_dal_form(self):
        campi = set(AnagraficaAziendaleForm().fields)
        for campo in ("capo_eccezione_legacy_id", "capo_eccezione_motivo", "utente_id_pre_offboarding", "data_cessazione"):
            self.assertNotIn(campo, campi)

    def test_pannello_nella_scheda(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertContains(resp, 'id="dp-az-pannello"')
        self.assertContains(resp, 'data-dp-scheda="organico"')
        self.assertNotContains(resp, 'id="id_data_cessazione"')

    def test_senza_permessi_non_modifica(self):
        self.client.force_login(self.semplice)
        self.client.post(self.url, self._dati(taglia_scarpe="99"))
        self.az.refresh_from_db()
        self.assertEqual(self.az.taglia_scarpe, "43")
