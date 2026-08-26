"""Import ruoli dal gestionale: catalogo, assegnazioni datate, gerarchia.

Le garanzie che il comando deve dare, e che qui si verificano riga per riga:
le persone si riconoscono dal **codice fiscale**; il ruolo `Principale`
diventa il «Ruolo aziendale» della scheda senza toccare gli altri; le date
arrivano sulle assegnazioni; la gerarchia fra ruoli si scrive solo dove il
file è univoco; il dry-run non lascia traccia e rilanciare non duplica.
"""
from __future__ import annotations

import datetime
from io import StringIO
from pathlib import Path
from tempfile import mkdtemp

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteRuoloOperativo,
    RuoloOperativo,
    RuoloQualifica,
    TipoQualifica,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()

CF_UNO = "RSSMRA80A01H501U"
CF_DUE = "VRDLGU85B02H501W"
CF_IGNOTO = "XXXXXX00X00X000X"

ROLES_HEADER = ["id", "Nome", "Descrizione", "Scopo", "Staff/Line"]
PEOPLE_HEADER = [
    "id", "Dipendente", "Codice fiscale", "Ruolo", "Responsabile", "Ruolo responsabile",
    "Cod. Fiscale Responsabile", "Tipologia associazione", "Data di assunzione", "Fte",
    "Data inizio", "Data fine",
]


def _xlsx(tmp: Path, nome: str, header: list[str], righe: list[list]) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in righe:
        ws.append(r)
    percorso = tmp / nome
    wb.save(percorso)
    return str(percorso)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImportRuoliTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.tmp = Path(mkdtemp())
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            for alias, nome, cognome in (("u.uno", "Mario", "Rossi"), ("d.due", "Luigi", "Verdi")):
                cur.execute(
                    "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [alias, nome, cognome, "UT", 1],
                )
            cur.execute("SELECT id, aliasusername FROM anagrafica_dipendenti")
            self.ids = {alias: int(pk) for pk, alias in cur.fetchall()}
        DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"], codice_fiscale=CF_UNO,
        )
        DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=self.ids["d.due"], codice_fiscale=CF_DUE,
        )

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("import_ruoli_gestionale", *args, stdout=out)
        return out.getvalue()

    def _roles(self, righe=None):
        return _xlsx(self.tmp, "roles.xlsx", ROLES_HEADER, righe if righe is not None else [
            [1, "Capocommessa", "Guida la commessa", "", "line"],
            [2, "Dept Chief", "", "", "line"],
            [3, "Preposto", "", "", "line"],
        ])

    def _people(self, righe):
        return _xlsx(self.tmp, "people.xlsx", PEOPLE_HEADER, righe)

    # ---------------------------------------------------------------- catalogo
    def test_dry_run_non_scrive_il_catalogo(self):
        self._run("--roles", self._roles())
        self.assertEqual(RuoloOperativo.objects.count(), 0)

    def test_apply_crea_i_ruoli_mancanti(self):
        self._run("--roles", self._roles(), "--apply")
        self.assertEqual(
            set(RuoloOperativo.objects.values_list("nome", flat=True)),
            {"Capocommessa", "Dept Chief", "Preposto"},
        )

    def test_rilanciare_non_duplica(self):
        self._run("--roles", self._roles(), "--apply")
        self._run("--roles", self._roles(), "--apply")
        self.assertEqual(RuoloOperativo.objects.count(), 3)

    def test_descrizione_gia_scritta_nel_portale_non_viene_sovrascritta(self):
        RuoloOperativo.objects.create(nome="Capocommessa", descrizione="Scritta a mano")
        self._run("--roles", self._roles(), "--apply")
        self.assertEqual(
            RuoloOperativo.objects.get(nome="Capocommessa").descrizione, "Scritta a mano"
        )

    def test_scopo_finisce_nella_descrizione(self):
        self._run("--roles", self._roles([[1, "Energy Manager", "", "Gestire i consumi", "line"]]), "--apply")
        self.assertIn("Scopo: Gestire i consumi", RuoloOperativo.objects.get(nome="Energy Manager").descrizione)

    # ----------------------------------------------------------- assegnazioni
    def _import_base(self, righe, *args):
        return self._run("--roles", self._roles(), "--people", self._people(righe), *args)

    def test_assegnazione_creata_per_codice_fiscale(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Dept Chief", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply")
        ass = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(ass.ruolo.nome, "Capocommessa")
        self.assertEqual(ass.data_inizio, datetime.date(2020, 3, 1))
        self.assertEqual(ass.tipologia, DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE)

    def test_il_principale_diventa_il_ruolo_aziendale(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "", "", "Principale", "", 100, "01/03/2020", None],
            [2, "ROSSI MARIO", CF_UNO, "Preposto", "", "", "", "Secondario", "", 100, "01/04/2021", None],
        ], "--apply")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(az.ruolo_aziendale, "Capocommessa")
        self.assertEqual(
            DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.ids["u.uno"]).count(), 2
        )

    def test_ruolo_chiuso_conserva_la_data_fine(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Preposto", "", "", "", "Secondario", "", 100, "01/03/2019", "31/12/2021"],
        ], "--apply")
        ass = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(ass.data_fine, datetime.date(2021, 12, 31))
        self.assertTrue(ass.is_conclusa)

    def test_persona_senza_codice_fiscale_noto_viene_saltata_e_segnalata(self):
        out = self._import_base([
            [1, "IGNOTO TIZIO", CF_IGNOTO, "Capocommessa", "", "", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply")
        self.assertEqual(DipendenteRuoloOperativo.objects.count(), 0)
        self.assertIn("IGNOTO TIZIO", out)

    def test_assegnazione_esistente_viene_completata_non_duplicata(self):
        ruolo = RuoloOperativo.objects.create(nome="Capocommessa")
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.ids["u.uno"], ruolo=ruolo,
        )
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply")
        qs = DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().data_inizio, datetime.date(2020, 3, 1))

    def test_due_principali_tiene_il_piu_recente_e_lo_dichiara(self):
        out = self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "", "", "Principale", "", 100, "01/03/2020", None],
            [2, "ROSSI MARIO", CF_UNO, "Dept Chief", "", "", "", "Principale", "", 100, "01/06/2023", None],
        ], "--apply")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.ids["u.uno"])
        self.assertEqual(az.ruolo_aziendale, "Dept Chief")
        self.assertIn("PIÙ ruoli principali", out)

    # --------------------------------------------------------------- gerarchia
    def test_gerarchia_scritta_dove_univoca(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Dept Chief", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply")
        self.assertEqual(
            RuoloOperativo.objects.get(nome="Capocommessa").riporta_a.nome, "Dept Chief"
        )

    def test_gerarchia_in_conflitto_resta_vuota(self):
        out = self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Dept Chief", "", "Principale", "", 100, "01/03/2020", None],
            [2, "VERDI LUIGI", CF_DUE, "Capocommessa", "", "Preposto", "", "Principale", "", 100, "01/03/2021", None],
        ], "--apply")
        self.assertIsNone(RuoloOperativo.objects.get(nome="Capocommessa").riporta_a)
        self.assertIn("più responsabili", out)

    def test_no_gerarchia_lascia_stare_i_riporti(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Dept Chief", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply", "--no-gerarchia")
        self.assertIsNone(RuoloOperativo.objects.get(nome="Capocommessa").riporta_a)

    def test_riporto_a_se_stesso_ignorato(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Capocommessa", "", "Principale", "", 100, "01/03/2020", None],
        ], "--apply")
        self.assertIsNone(RuoloOperativo.objects.get(nome="Capocommessa").riporta_a)

    def test_riporto_chiuso_non_descrive_l_organizzazione_di_oggi(self):
        self._import_base([
            [1, "ROSSI MARIO", CF_UNO, "Capocommessa", "", "Dept Chief", "", "Secondario", "", 100, "01/03/2015", "31/12/2018"],
        ], "--apply")
        self.assertIsNone(RuoloOperativo.objects.get(nome="Capocommessa").riporta_a)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RuoloQualificaUITests(TestCase):
    """Le qualifiche del ruolo si gestiscono dal portale, non solo da import."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="rq_admin", email="rq_admin@x.local", password="x"
        )
        cls.utente = User.objects.create_user(
            username="rq_user", email="rq_user@x.local", password="x"
        )

    def setUp(self):
        self.ruolo = RuoloOperativo.objects.create(nome="Capocommessa")
        self.qualifica = TipoQualifica.objects.create(nome="Preposto ASR")

    def test_admin_associa_una_qualifica_al_ruolo(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("anagrafica:ruolo_qualifica_aggiungi", args=[self.ruolo.pk]),
            {"qualifica_id": self.qualifica.pk, "livello": "Base"},
        )
        rq = RuoloQualifica.objects.get(ruolo=self.ruolo)
        self.assertEqual(rq.qualifica, self.qualifica)
        self.assertEqual(rq.livello, "Base")
        self.assertTrue(rq.obbligatoria)

    def test_associazione_ripetuta_non_duplica(self):
        self.client.force_login(self.admin)
        for _ in range(2):
            self.client.post(
                reverse("anagrafica:ruolo_qualifica_aggiungi", args=[self.ruolo.pk]),
                {"qualifica_id": self.qualifica.pk},
            )
        self.assertEqual(RuoloQualifica.objects.filter(ruolo=self.ruolo).count(), 1)

    def test_facoltativa_quando_richiesto(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("anagrafica:ruolo_qualifica_aggiungi", args=[self.ruolo.pk]),
            {"qualifica_id": self.qualifica.pk, "obbligatoria": "0"},
        )
        self.assertFalse(RuoloQualifica.objects.get(ruolo=self.ruolo).obbligatoria)

    def test_rimozione(self):
        self.client.force_login(self.admin)
        rq = RuoloQualifica.objects.create(ruolo=self.ruolo, qualifica=self.qualifica)
        self.client.post(
            reverse("anagrafica:ruolo_qualifica_rimuovi", args=[self.ruolo.pk, rq.pk])
        )
        self.assertFalse(RuoloQualifica.objects.filter(pk=rq.pk).exists())

    def test_non_admin_non_puo_associare(self):
        self.client.force_login(self.utente)
        self.client.post(
            reverse("anagrafica:ruolo_qualifica_aggiungi", args=[self.ruolo.pk]),
            {"qualifica_id": self.qualifica.pk},
        )
        self.assertFalse(RuoloQualifica.objects.exists())

    def test_il_catalogo_mostra_le_qualifiche_del_ruolo(self):
        self.client.force_login(self.admin)
        RuoloQualifica.objects.create(ruolo=self.ruolo, qualifica=self.qualifica, livello="2")
        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))
        per_nome = {r.nome: r for r in resp.context["ruoli"]}
        self.assertEqual(
            [q.qualifica.nome for q in per_nome["Capocommessa"].qualifiche], ["Preposto ASR"]
        )
