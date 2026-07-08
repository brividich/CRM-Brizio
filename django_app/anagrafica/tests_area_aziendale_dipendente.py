"""Collegamento anagrafica lavorativa <-> AreaAziendale (Fase 2 dell'inversione
gerarchia Reparto/AreaAziendale, spec 2026-07-08-anagrafica-lavorativa-area-aziendale).

Copre: la FK area_aziendale sul dipendente, la sincronizzazione centralizzata in
_sync_aziendale_from_reparto (invariante area<->reparto), le due viste che la
scrivono (mini-form rapido + form completo), il context/markup del cascading in
dipendente_detail, il match per ID in training_eligibility, e il report di sola
lettura sulle regole di formazione per area.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteAreaAziendaleFieldTests(TestCase):
    """Il dipendente si collega alla nuova AreaAziendale con una FK vera (non più
    il CharField area_aziendale_nome, rimosso con l'inversione gerarchia)."""

    def test_dipendente_ha_fk_area_aziendale_non_piu_charfield(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=901, area="UT", area_aziendale=area,
        )
        self.assertFalse(hasattr(az, "area_aziendale_nome"))
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_area_aziendale_nullable(self):
        az = DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=902)
        self.assertIsNone(az.area_aziendale_id)

    def test_elimina_area_aziendale_azzera_riferimento_dipendente(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        az = DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=903, area_aziendale=area,
        )
        area.delete()
        az.refresh_from_db()
        self.assertIsNone(az.area_aziendale_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SyncAziendaleFromRepartoTests(TestCase):
    """_sync_aziendale_from_reparto valida che l'Area aziendale assegnata
    appartenga sempre al Reparto risolto, azzerandola in caso contrario."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="sync_az_admin", email="sync_az_admin@x.local", password="x"
        )

    def test_area_appartenente_al_reparto_viene_salvata(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT", caporeparto_legacy_id=401)
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        _sync_aziendale_from_reparto(910, "UT", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=910)
        self.assertEqual(az.area_aziendale_id, area.pk)
        self.assertEqual(az.caporeparto_legacy_id, 401)

    def test_area_di_un_altro_reparto_viene_azzerata(self):
        from .views import _sync_aziendale_from_reparto
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        _sync_aziendale_from_reparto(911, "UT", area_aziendale_id=area_mag.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=911)
        self.assertIsNone(az.area_aziendale_id)

    def test_reparto_vuoto_azzera_anche_area(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        _sync_aziendale_from_reparto(912, "", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=912)
        self.assertIsNone(az.area_aziendale_id)
        self.assertEqual(az.area, "")

    def test_area_disattivata_ma_ancora_del_reparto_resta_valida(self):
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep, is_active=False)
        _sync_aziendale_from_reparto(913, "UT", area_aziendale_id=area.pk, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=913)
        self.assertEqual(az.area_aziendale_id, area.pk)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteRepartoSetAreaAziendaleTests(TestCase):
    """Il mini-form rapido 'Cambia reparto' può impostare anche l'Area aziendale."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="rep_set_admin", email="rep_set_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) "
                "VALUES (%s, %s, %s, %s)",
                ["l.verdi", "Luca", "Verdi", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["l.verdi"])
            self.legacy_id = int(cursor.fetchone()[0])

    def test_post_con_area_del_reparto_selezionato_viene_salvata(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_post_con_area_di_un_altro_reparto_viene_ignorata(self):
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area_mag.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNone(az.area_aziendale_id)

    def test_post_senza_area_non_genera_errore(self):
        Reparto.objects.create(nome="UT")
        resp = self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT"},
        )
        self.assertEqual(resp.status_code, 302)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnagraficaAziendaleFormAreaAziendaleTests(TestCase):
    """Il form completo 'Modifica dati aziendali' include ora la FK area_aziendale,
    corretta/azzerata da _sync_aziendale_from_reparto se incoerente col reparto."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="az_form_admin", email="az_form_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_form_include_campo_area_aziendale_non_piu_nome(self):
        from .forms import AnagraficaAziendaleForm
        form = AnagraficaAziendaleForm()
        self.assertIn("area_aziendale", form.fields)
        self.assertNotIn("area_aziendale_nome", form.fields)

    def test_save_con_area_coerente_persiste_la_fk(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[920]),
            {"area": "UT", "area_aziendale": str(area.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=920)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_save_con_area_incoerente_viene_azzerata(self):
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[921]),
            {"area": "UT", "area_aziendale": str(area_mag.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=921)
        self.assertIsNone(az.area_aziendale_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteDetailAreaAziendaleUITests(TestCase):
    """dipendente_detail espone il cascading Reparto->Area aziendale in pagina."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="dd_area_admin", email="dd_area_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["p.bianchi", "Paolo", "Bianchi", "UT", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["p.bianchi"])
            self.legacy_id = int(cursor.fetchone()[0])

    def test_pagina_espone_select_area_aziendale_e_blob_json(self):
        rep = Reparto.objects.create(nome="UT")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        AreaAziendale.objects.create(nome="IN2", reparto=rep)
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('id="mini-area-select"', content)
        self.assertIn('id_area_aziendale', content)
        self.assertIn('"UT"', content)
        self.assertIn('"IN1"', content)
        self.assertIn('"IN2"', content)
        self.assertNotIn("az-area-autofill", content)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TrainingEligibilityAreaAziendaleFkTests(TestCase):
    """Le regole di formazione obbligatoria per Area aziendale matchano per FK,
    non più per nome sul CharField rimosso."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, attivo) VALUES "
                "(931, 'Anna', 'Verdi', 1), (932, 'Bruno', 'Neri', 1)"
            )

    def test_pertinenza_per_area_aziendale_match_per_fk(self):
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
        from .services.training_eligibility import candidati_corso
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=931, area_aziendale=area)
        # 932 resta senza area assegnata: non deve risultare pertinente.
        piano = TrainingPlan.objects.create(codice="PSIC", nome="Piano sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="CS1", titolo="Corso sicurezza area", durata_ore_teorica=4,
        )
        TrainingRequirementRule.objects.create(
            corso=corso, area=area, is_active=True, is_mandatory=True,
        )
        res = candidati_corso(corso)
        ids = {c["legacy_id"] for c in res["idonei"]} | {c["legacy_id"] for c in res["non_idonei"]}
        self.assertIn(931, ids)
        self.assertNotIn(932, ids)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportRegoleFormazioneAreaCommandTests(TestCase):
    """Comando di sola lettura: elenca le TrainingRequirementRule per area con
    il conteggio dei dipendenti oggi assegnati (via FK)."""

    def test_elenca_regole_area_con_conteggio_dipendenti(self):
        from io import StringIO
        from django.core.management import call_command
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule

        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        piano = TrainingPlan.objects.create(codice="PF", nome="Piano F")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="C1", titolo="Corso sicurezza", durata_ore_teorica=8,
        )
        TrainingRequirementRule.objects.create(corso=corso, area=area, is_active=True, is_mandatory=True)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=940, area_aziendale=area)

        out = StringIO()
        call_command("report_regole_formazione_area", stdout=out)
        output = out.getvalue()
        self.assertIn("IN1", output)
        self.assertIn("UT", output)
        self.assertIn("Corso sicurezza", output)

    def test_nessuna_regola_stampa_messaggio(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("report_regole_formazione_area", stdout=out)
        self.assertIn("Nessuna regola", out.getvalue())
