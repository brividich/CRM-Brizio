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

    # -- "non mi esprimo" != "togli l'area" -------------------------------

    def test_parametro_omesso_conserva_l_area_dello_stesso_reparto(self):
        """Regressione: chi rimappa solo il reparto non deve scollegare il dipendente.

        Prima della sentinella, `report_reparti_orfani --apply` e ogni altro
        chiamante che non nominava l'area azzeravano la FK, rendendo la persona
        invisibile ai report che ragionano per reparto.
        """
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=914, area="UT", area_aziendale=area,
        )
        _sync_aziendale_from_reparto(914, "UT", saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=914)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_parametro_omesso_ma_reparto_cambiato_azzera_comunque(self):
        """L'invariante area<->reparto vince sulla conservazione."""
        from .views import _sync_aziendale_from_reparto
        rep_ut = Reparto.objects.create(nome="UT")
        Reparto.objects.create(nome="MAG")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep_ut)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=915, area="UT", area_aziendale=area,
        )
        _sync_aziendale_from_reparto(915, "MAG", saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=915)
        self.assertIsNone(az.area_aziendale_id)

    def test_none_esplicito_toglie_l_area(self):
        """Il form dove l'area e' un campo scelto dall'utente deve poterla togliere."""
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=916, area="UT", area_aziendale=area,
        )
        _sync_aziendale_from_reparto(916, "UT", area_aziendale_id=None, saved_by=self.admin)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=916)
        self.assertIsNone(az.area_aziendale_id)

    def test_area_conservata_non_genera_voce_di_storico(self):
        """Conservare non e' cambiare: nessun periodo nuovo nello storico."""
        from .models import DipendenteCambiamentoOrganizzativo
        from .views import _sync_aziendale_from_reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=917, area="UT", area_aziendale=area,
        )
        _sync_aziendale_from_reparto(917, "UT", saved_by=self.admin)
        self.assertFalse(
            DipendenteCambiamentoOrganizzativo.objects.filter(
                legacy_anagrafica_id=917,
                tipo=DipendenteCambiamentoOrganizzativo.TIPO_AREA_AZIENDALE,
            ).exists()
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteRepartoSetAreaAziendaleTests(TestCase):
    """Lo spostamento organizzativo imposta reparto e Area aziendale insieme.

    (Prima erano il mini-form rapido 'Cambia reparto'; l'invariante area↔reparto
    resta la stessa, cambia solo l'endpoint che la esercita.)"""

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
            reverse("anagrafica:dipendente_assegnazione_create", args=[self.legacy_id]),
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
            reverse("anagrafica:dipendente_assegnazione_create", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area_mag.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNone(az.area_aziendale_id)

    def test_post_senza_area_non_genera_errore(self):
        Reparto.objects.create(nome="UT")
        resp = self.client.post(
            reverse("anagrafica:dipendente_assegnazione_create", args=[self.legacy_id]),
            {"reparto": "UT"},
        )
        self.assertEqual(resp.status_code, 302)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteMatricolaSetTests(TestCase):
    """Modifica della matricola per un dipendente già presente in anagrafica:
    preinserimento prima dell'assegnazione, o candidato importato dal recruiting."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="matricola_set_admin", email="matricola_set_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) "
                "VALUES (%s, %s, %s, %s)",
                ["p.bianchi", "Paolo", "Bianchi", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["p.bianchi"])
            self.legacy_id = int(cursor.fetchone()[0])

    def _matricola(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT matricola FROM anagrafica_dipendenti WHERE id = %s", [self.legacy_id])
            row = cursor.fetchone()
            return row[0] if row else None

    def test_assegna_matricola_a_dipendente_senza_matricola(self):
        resp = self.client.post(
            reverse("anagrafica:dipendente_matricola_set", args=[self.legacy_id]),
            {"matricola": "CNO 0042"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._matricola(), "CNO 0042")

    def test_matricola_registra_storico_cambiamento(self):
        from .models import DipendenteCambiamentoOrganizzativo
        self.client.post(
            reverse("anagrafica:dipendente_matricola_set", args=[self.legacy_id]),
            {"matricola": "CNO 0099"},
        )
        storico = DipendenteCambiamentoOrganizzativo.objects.filter(
            legacy_anagrafica_id=self.legacy_id,
            tipo=DipendenteCambiamentoOrganizzativo.TIPO_MATRICOLA,
        ).first()
        self.assertIsNotNone(storico)
        self.assertEqual(storico.valore_nuovo, "CNO 0099")

    def test_non_admin_non_puo_modificare(self):
        user = User.objects.create_user(username="matricola_plain_user", password="x")
        self.client.force_login(user)
        resp = self.client.post(
            reverse("anagrafica:dipendente_matricola_set", args=[self.legacy_id]),
            {"matricola": "CNO 0001"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self._matricola(), (None, ""))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnagraficaAziendaleFormAreaAziendaleTests(TestCase):
    """Il form 'Modifica dati aziendali' NON governa più l'assetto organizzativo.

    Reparto, area aziendale e ruolo aziendale sono passati agli spostamenti
    (DipendenteAssegnazione): lasciarli editabili anche da qui darebbe due
    scrittori capaci di desincronizzare l'assetto dall'assegnazione in corso.
    L'invariante area↔reparto vive ora nel service, non nel form."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="az_form_admin", email="az_form_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_form_non_espone_piu_assetto_organizzativo(self):
        from .forms import AnagraficaAziendaleForm
        form = AnagraficaAziendaleForm()
        for campo in ("area", "area_aziendale", "ruolo_aziendale"):
            with self.subTest(campo=campo):
                self.assertNotIn(campo, form.fields)
        # I dati aziendali "veri" restano.
        self.assertIn("badge", form.fields)

    def test_save_non_puo_scavalcare_l_assegnazione(self):
        """Un POST che tenta di forzare area/ruolo non deve avere effetto."""
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=920, area="MAG")
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[920]),
            {"area": "UT", "area_aziendale": str(area.pk), "ruolo_aziendale": "Capoturno"},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=920)
        self.assertEqual(az.area, "MAG")
        self.assertIsNone(az.area_aziendale_id)
        self.assertEqual(az.ruolo_aziendale, "")

    def test_save_persiste_gli_altri_dati_aziendali(self):
        resp = self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[921]),
            {"badge": "0042", "telefono_aziendale": "+39 555 0100"},
        )
        self.assertEqual(resp.status_code, 302)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=921)
        self.assertEqual(az.badge, "42")
        self.assertEqual(az.telefono_aziendale, "+39 555 0100")


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
        # Il cascading vive ora nel form di spostamento organizzativo.
        self.assertIn('id="sp-reparto"', content)
        self.assertIn('id="sp-area"', content)
        self.assertIn('"UT"', content)
        self.assertIn('"IN1"', content)
        self.assertIn('"IN2"', content)
        self.assertNotIn("az-area-autofill", content)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendenteCreateFormA2Tests(TestCase):
    """A2 / punto 1.4: il form 'nuovo dipendente' espone Area aziendale (accanto al
    reparto) e Ruolo, e NON mostra più i 'Ruoli operativi di sicurezza'."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="create_a2_admin", email="create_a2_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")

    def test_get_mostra_area_aziendale_e_ruolo_nasconde_ruoli_operativi(self):
        rep = Reparto.objects.create(nome="UT")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.get(reverse("anagrafica:dipendente_create"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('name="area_aziendale"', content)
        self.assertIn('name="ruolo"', content)
        self.assertNotIn("Ruoli operativi di sicurezza", content)

    def test_post_crea_dipendente_con_area_aziendale_del_reparto(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(reverse("anagrafica:dipendente_create"), {
            "nome": "Alfa", "cognome": "Test", "aliasusername": "a.test",
            "reparto": "UT", "area_aziendale": str(area.pk),
            "mansione": "", "ruolo": "Caposquadra",
            # niente "attivo": evita la creazione automatica dell'account portale.
        })
        self.assertEqual(resp.status_code, 302)
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["a.test"])
            legacy_id = int(cur.fetchone()[0])
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=legacy_id)
        self.assertEqual(az.area_aziendale_id, area.pk)

    def test_post_area_di_altro_reparto_viene_azzerata(self):
        Reparto.objects.create(nome="UT")
        rep_mag = Reparto.objects.create(nome="MAG")
        area_mag = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_mag)
        resp = self.client.post(reverse("anagrafica:dipendente_create"), {
            "nome": "Beta", "cognome": "Test", "aliasusername": "b.test",
            "reparto": "UT", "area_aziendale": str(area_mag.pk), "mansione": "", "ruolo": "",
        })
        self.assertEqual(resp.status_code, 302)
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["b.test"])
            legacy_id = int(cur.fetchone()[0])
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=legacy_id)
        self.assertIsNone(az.area_aziendale_id)


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
