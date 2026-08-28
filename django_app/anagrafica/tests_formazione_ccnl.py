"""Monte ore CCNL: diritto soggettivo alla formazione (24h/3 anni, finestra
scorrevole), separato dalla formazione sicurezza (`obbligatoria_ccnl=True`),
che resta informativa e non concorre al monte ore.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser durante i test.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .models_formazione import TrainingCourse, TrainingEmployeeRecord, TrainingPlan
from .services.formazione_ccnl import finestra_scorrevole, monte_ore_dipendenti, righe_dipendenti

User = get_user_model()

OGGI = date(2026, 8, 28)


def _piano():
    piano, _ = TrainingPlan.objects.get_or_create(codice="P-CCNL", defaults={"nome": "Piano CCNL"})
    return piano


def _corso(codice, titolo, obbligatoria_ccnl=False):
    return TrainingCourse.objects.create(
        piano=_piano(), codice=codice, titolo=titolo, durata_ore_teorica=4,
        obbligatoria_ccnl=obbligatoria_ccnl,
    )


def _completamento(corso, legacy_id, data, ore, idoneo=True):
    return TrainingEmployeeRecord.objects.create(
        corso=corso, legacy_anagrafica_id=legacy_id, data_completamento=data,
        ore_frequentate=ore, idoneo=idoneo,
    )


class FinestraScorrevoleTests(TestCase):
    def test_finestra_di_tre_anni_terminante_oggi(self):
        dal, al = finestra_scorrevole(al=OGGI)
        self.assertEqual(al, OGGI)
        self.assertEqual(dal, date(2023, 8, 28))

    def test_default_al_oggi(self):
        _, al = finestra_scorrevole()
        self.assertEqual(al, date.today())


class MonteOreDipendentiTests(TestCase):
    def setUp(self):
        self.facoltativo = _corso("C-FAC", "Excel avanzato", obbligatoria_ccnl=False)
        self.sicurezza = _corso("C-SIC", "Antincendio", obbligatoria_ccnl=True)

    def test_ore_facoltative_e_obbligatorie_separate(self):
        _completamento(self.facoltativo, 101, date(2026, 1, 10), 8)
        _completamento(self.sicurezza, 101, date(2026, 2, 5), 4)
        _, _, aggregato = monte_ore_dipendenti(al=OGGI)
        riga = aggregato[101]
        self.assertEqual(riga["ore_facoltative"], 8.0)
        self.assertEqual(riga["ore_obbligatorie"], 4.0)
        self.assertEqual(riga["n_corsi_facoltativi"], 1)
        self.assertEqual(riga["n_corsi_obbligatori"], 1)

    def test_completamenti_non_idonei_esclusi(self):
        _completamento(self.facoltativo, 102, date(2026, 1, 10), 8, idoneo=False)
        _, _, aggregato = monte_ore_dipendenti(al=OGGI)
        self.assertNotIn(102, aggregato)

    def test_completamenti_fuori_finestra_esclusi(self):
        fuori = OGGI - timedelta(days=365 * 4)
        _completamento(self.facoltativo, 103, fuori, 8)
        _, _, aggregato = monte_ore_dipendenti(al=OGGI)
        self.assertNotIn(103, aggregato)

    def test_ore_si_sommano_su_piu_completamenti(self):
        secondo = _corso("C-FAC-2", "Public speaking", obbligatoria_ccnl=False)
        _completamento(self.facoltativo, 104, date(2026, 1, 10), 8)
        _completamento(secondo, 104, date(2026, 3, 1), 10)
        _, _, aggregato = monte_ore_dipendenti(al=OGGI)
        self.assertEqual(aggregato[104]["ore_facoltative"], 18.0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RigheDipendentiTests(TestCase):
    def setUp(self):
        self.facoltativo = _corso("C-FAC-R", "Excel avanzato", obbligatoria_ccnl=False)
        self.dip_completo = AnagraficaDipendente.objects.create(
            nome="Anna", cognome="Verdi Test", aliasusername="averdi.test",
            reparto="Produzione",
        )
        self.dip_a_zero = AnagraficaDipendente.objects.create(
            nome="Bruno", cognome="Neri Test", aliasusername="bneri.test",
            reparto="Qualità",
        )
        _completamento(self.facoltativo, self.dip_completo.id, date(2026, 1, 10), 24)

    def test_stato_completo_sopra_soglia(self):
        _, _, _, righe = righe_dipendenti(al=OGGI)
        riga = next(r for r in righe if r["legacy_id"] == self.dip_completo.id)
        self.assertEqual(riga["stato"], "COMPLETO")
        self.assertEqual(riga["pct"], 100)
        self.assertEqual(riga["ore_mancanti"], 0.0)

    def test_stato_da_iniziare_senza_completamenti(self):
        _, _, _, righe = righe_dipendenti(al=OGGI)
        riga = next(r for r in righe if r["legacy_id"] == self.dip_a_zero.id)
        self.assertEqual(riga["stato"], "DA_INIZIARE")
        self.assertEqual(riga["ore_mancanti"], 24.0)

    def test_pct_non_supera_100_oltre_soglia(self):
        _completamento(self.facoltativo, self.dip_completo.id, date(2026, 2, 1), 100)
        _, _, _, righe = righe_dipendenti(al=OGGI)
        riga = next(r for r in righe if r["legacy_id"] == self.dip_completo.id)
        self.assertEqual(riga["pct"], 100)

    def test_filtro_reparto(self):
        _, _, _, righe = righe_dipendenti(al=OGGI, filtro_reparto="Qualità")
        self.assertEqual({r["legacy_id"] for r in righe}, {self.dip_a_zero.id})

    def test_filtro_stato(self):
        _, _, _, righe = righe_dipendenti(al=OGGI, filtro_stato="COMPLETO")
        self.assertEqual({r["legacy_id"] for r in righe}, {self.dip_completo.id})

    def test_filtro_ricerca_nome(self):
        _, _, _, righe = righe_dipendenti(al=OGGI, filtro_q="verdi")
        self.assertEqual({r["legacy_id"] for r in righe}, {self.dip_completo.id})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DashboardViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-ccnl", "su-ccnl@test.local", "x")
        self.client.force_login(self.su)
        self.facoltativo = _corso("C-FAC-V", "Excel avanzato", obbligatoria_ccnl=False)
        self.sicurezza = _corso("C-SIC-V", "Antincendio", obbligatoria_ccnl=True)
        self.dip = AnagraficaDipendente.objects.create(
            nome="Carla", cognome="Gialli Test", aliasusername="cgialli.test",
            reparto="Officina",
        )
        _completamento(self.facoltativo, self.dip.id, date(2026, 1, 10), 12)
        _completamento(self.sicurezza, self.dip.id, date(2026, 2, 1), 4)

    def test_dashboard_ok_e_mostra_dipendente(self):
        resp = self.client.get(reverse("anagrafica:formazione_ccnl_dashboard"))
        self.assertEqual(resp.status_code, 200)
        righe = list(resp.context["page_obj"])
        riga = next(r for r in righe if r["legacy_id"] == self.dip.id)
        self.assertEqual(riga["ore_facoltative"], 12.0)
        self.assertEqual(riga["ore_obbligatorie"], 4.0)
        self.assertEqual(riga["stato"], "IN_CORSO")

    def test_espansione_htmx_divide_facoltativi_e_obbligatori(self):
        resp = self.client.get(
            reverse("anagrafica:formazione_ccnl_dipendente_espansione", args=[self.dip.id])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r.corso_id for r in resp.context["facoltativi"]], [self.facoltativo.pk])
        self.assertEqual([r.corso_id for r in resp.context["obbligatori"]], [self.sicurezza.pk])

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse("anagrafica:formazione_ccnl_dashboard"))
        self.assertNotEqual(resp.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ExportCcnlTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-ccnl-exp", "su-ccnl-exp@test.local", "x")
        self.client.force_login(self.su)
        self.facoltativo = _corso("C-FAC-E", "Excel avanzato", obbligatoria_ccnl=False)
        self.dip = AnagraficaDipendente.objects.create(
            nome="Dario", cognome="Blu Test", aliasusername="dblu.test",
            reparto="Officina",
        )
        _completamento(self.facoltativo, self.dip.id, date(2026, 1, 10), 12)

    def test_export_dataset_riporta_le_ore(self):
        from .exports_formazione import _formazione_ccnl_rows

        req = type("R", (), {"GET": {}})()
        rows = _formazione_ccnl_rows(req, "full")
        riga = next(r for r in rows if r["nome"] == "Blu Test Dario" or "Dario" in r["nome"])
        self.assertEqual(riga["ore_facoltative"], 12.0)
