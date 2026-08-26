"""Ruoli: assegnazioni multiple e un ruolo principale coerente con la scheda.

Il ruolo vive in due posti — le assegnazioni (`DipendenteRuoloOperativo`, N per
persona) e il campo testuale singolo `ruolo_aziendale` della scheda, che è il
**principale**. Qui si verifica che restino allineati senza mai schiacciare il
multiruolo, e che nessuno risulti responsabile di sé stesso.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Reparto,
    RuoloOperativo,
)
from .services.ruoli_sync import (
    assicura_assegnazione,
    dopo_assegnazione,
    dopo_rimozione,
    ruolo_principale,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RuoloPrincipaleTests(TestCase):
    """Le quattro regole del ruolo principale."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="rsync_admin", email="rsync_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ["m.multi", "Marco", "Multi", "UT", "Tecnico", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["m.multi"])
            self.legacy_id = int(cur.fetchone()[0])
        self.capocommessa = RuoloOperativo.objects.create(nome="Capocommessa")
        self.preposto = RuoloOperativo.objects.create(nome="Preposto")

    def _assegna(self, ruolo):
        return self.client.post(
            reverse("anagrafica:dipendente_ruolo_assegna", args=[self.legacy_id]),
            {"ruolo_id": ruolo.pk},
        )

    def test_primo_ruolo_assegnato_diventa_principale(self):
        self._assegna(self.capocommessa)
        self.assertEqual(ruolo_principale(self.legacy_id), "Capocommessa")

    def test_secondo_ruolo_non_ribalta_il_principale(self):
        self._assegna(self.capocommessa)
        self._assegna(self.preposto)
        self.assertEqual(ruolo_principale(self.legacy_id), "Capocommessa")
        self.assertEqual(
            DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.legacy_id).count(), 2
        )

    def test_rimuovere_il_principale_promuove_il_ruolo_rimasto(self):
        self._assegna(self.capocommessa)
        self._assegna(self.preposto)
        ass = DipendenteRuoloOperativo.objects.get(
            legacy_anagrafica_id=self.legacy_id, ruolo=self.capocommessa
        )
        self.client.post(
            reverse("anagrafica:dipendente_ruolo_rimuovi", args=[self.legacy_id, ass.pk])
        )
        self.assertEqual(ruolo_principale(self.legacy_id), "Preposto")

    def test_rimuovere_l_ultimo_ruolo_svuota_il_principale(self):
        self._assegna(self.capocommessa)
        ass = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.client.post(
            reverse("anagrafica:dipendente_ruolo_rimuovi", args=[self.legacy_id, ass.pk])
        )
        self.assertEqual(ruolo_principale(self.legacy_id), "")

    def test_rimuovere_un_ruolo_non_principale_lascia_tutto_com_e(self):
        self._assegna(self.capocommessa)
        self._assegna(self.preposto)
        ass = DipendenteRuoloOperativo.objects.get(
            legacy_anagrafica_id=self.legacy_id, ruolo=self.preposto
        )
        self.client.post(
            reverse("anagrafica:dipendente_ruolo_rimuovi", args=[self.legacy_id, ass.pk])
        )
        self.assertEqual(ruolo_principale(self.legacy_id), "Capocommessa")

    def test_badge_principale_marcato_nella_scheda(self):
        self._assegna(self.capocommessa)
        self._assegna(self.preposto)
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        principali = {a.ruolo.nome: a.is_principale for a in resp.context["ruoli_assegnati"]}
        self.assertEqual(principali, {"Capocommessa": True, "Preposto": False})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RuoloAziendaleCreaAssegnazioneTests(TestCase):
    """Il percorso inverso: lo spostamento nomina un ruolo, l'assegnazione segue."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["s.spost", "Sara", "Spost", "UT", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["s.spost"])
            self.legacy_id = int(cur.fetchone()[0])
        self.ruolo = RuoloOperativo.objects.create(nome="Capocommessa")

    def test_ruolo_in_catalogo_crea_l_assegnazione(self):
        self.assertTrue(assicura_assegnazione(self.legacy_id, "capocommessa"))
        self.assertTrue(
            DipendenteRuoloOperativo.objects
            .filter(legacy_anagrafica_id=self.legacy_id, ruolo=self.ruolo).exists()
        )

    def test_ruolo_fuori_catalogo_non_inventa_assegnazioni(self):
        self.assertFalse(assicura_assegnazione(self.legacy_id, "Ruolo storico mai censito"))
        self.assertFalse(
            DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.legacy_id).exists()
        )

    def test_chiamata_ripetuta_non_duplica(self):
        assicura_assegnazione(self.legacy_id, "Capocommessa")
        assicura_assegnazione(self.legacy_id, "Capocommessa")
        self.assertEqual(
            DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.legacy_id).count(), 1
        )

    def test_le_altre_assegnazioni_restano(self):
        altro = RuoloOperativo.objects.create(nome="Preposto")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.legacy_id, ruolo=altro)
        assicura_assegnazione(self.legacy_id, "Capocommessa")
        nomi = set(
            DipendenteRuoloOperativo.objects
            .filter(legacy_anagrafica_id=self.legacy_id)
            .values_list("ruolo__nome", flat=True)
        )
        self.assertEqual(nomi, {"Preposto", "Capocommessa"})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ResponsabileDiSeStessoTests(TestCase):
    """Il caporeparto non è responsabile di sé stesso."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["c.capo", "Carla", "Capo", "UT", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["c.capo"])
            self.capo_id = int(cur.fetchone()[0])

    def test_il_caporeparto_non_diventa_responsabile_di_se_stesso(self):
        from .views import _sync_aziendale_from_reparto

        Reparto.objects.create(nome="UT", caporeparto_legacy_id=self.capo_id, is_active=True)
        _sync_aziendale_from_reparto(self.capo_id, "UT", saved_by=None)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.capo_id)
        self.assertIsNone(az.caporeparto_legacy_id)

    def test_gli_altri_del_reparto_mantengono_il_caporeparto(self):
        from .views import _sync_aziendale_from_reparto

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["a.altro", "Aldo", "Altro", "UT", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["a.altro"])
            altro_id = int(cur.fetchone()[0])

        Reparto.objects.create(nome="UT", caporeparto_legacy_id=self.capo_id, is_active=True)
        _sync_aziendale_from_reparto(altro_id, "UT", saved_by=None)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=altro_id)
        self.assertEqual(az.caporeparto_legacy_id, self.capo_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportRuoliDisallineatiTests(TestCase):
    """Il comando di riparazione: dry-run per default, multiruolo mai indovinato."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            for alias, nome, cognome, reparto in (
                ("u.uno", "Uno", "Solo", "UT"),
                ("d.due", "Due", "Ruoli", "UT"),
                ("s.senza", "Senza", "Reparto", ""),
            ):
                cur.execute(
                    "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [alias, nome, cognome, reparto, 1],
                )
            cur.execute("SELECT id, aliasusername FROM anagrafica_dipendenti")
            self.ids = {alias: int(pk) for pk, alias in cur.fetchall()}
        self.capo = RuoloOperativo.objects.create(nome="Capocommessa")
        self.prep = RuoloOperativo.objects.create(nome="Preposto")

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("report_ruoli_disallineati", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive_nulla(self):
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"], ruolo=self.capo
        )
        self._run()
        self.assertEqual(ruolo_principale(self.ids["u.uno"]), "")

    def test_apply_promuove_chi_ha_un_solo_ruolo(self):
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"], ruolo=self.capo
        )
        self._run("--apply")
        self.assertEqual(ruolo_principale(self.ids["u.uno"]), "Capocommessa")

    def test_apply_salta_chi_ha_piu_ruoli(self):
        for ruolo in (self.capo, self.prep):
            DipendenteRuoloOperativo.objects.create(
                legacy_anagrafica_id=self.ids["d.due"], ruolo=ruolo
            )
        out = self._run("--apply")
        self.assertEqual(ruolo_principale(self.ids["d.due"]), "")
        self.assertIn("Saltati 1", out)

    def test_apply_crea_l_assegnazione_mancante(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"], ruolo_aziendale="Capocommessa",
        )
        self._run("--apply")
        self.assertTrue(
            DipendenteRuoloOperativo.objects
            .filter(legacy_anagrafica_id=self.ids["u.uno"], ruolo=self.capo).exists()
        )

    def test_apply_azzera_il_responsabile_di_se_stesso(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"],
            caporeparto_legacy_id=self.ids["u.uno"],
        )
        self._run("--apply")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertIsNone(az.caporeparto_legacy_id)

    def test_apply_NON_azzera_il_responsabile_di_chi_e_solo_senza_reparto(self):
        """Il dato mancante è la collocazione, non il responsabile: si segnala."""
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["s.senza"],
            caporeparto_legacy_id=self.ids["u.uno"],
        )
        out = self._run("--apply")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["s.senza"])
        self.assertEqual(az.caporeparto_legacy_id, self.ids["u.uno"])
        self.assertIn("Senza alcuna collocazione", out)

    def test_flag_esplicito_azzera_i_responsabili_scollegati(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["s.senza"],
            caporeparto_legacy_id=self.ids["u.uno"],
        )
        self._run("--apply", "--azzera-responsabili-scollegati")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["s.senza"])
        self.assertIsNone(az.caporeparto_legacy_id)

    def test_chi_ha_area_aziendale_non_e_considerato_scollegato(self):
        from .models import AreaAziendale, Reparto

        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["s.senza"],
            caporeparto_legacy_id=self.ids["u.uno"],
            area_aziendale=area,
        )
        out = self._run()
        self.assertIn("Senza alcuna collocazione (né reparto, né area) ma con responsabile: 0", out)

    def test_chi_ha_reparto_e_un_responsabile_diverso_non_viene_toccato(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"],
            caporeparto_legacy_id=self.ids["d.due"],
        )
        self._run("--apply")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(az.caporeparto_legacy_id, self.ids["d.due"])
