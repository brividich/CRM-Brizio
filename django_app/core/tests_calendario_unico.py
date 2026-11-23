"""Audit K1-K3: un solo calendario lavorativo, impostato in Assenze, per tutti i moduli. Dati sintetici."""
from datetime import date

from django.test import TestCase

from core import calendario_it as cal


class CalendarioUnicoTests(TestCase):
    def setUp(self):
        from assenze.models import AssenzeImpostazioniHR

        cal.svuota_cache()
        imp = AssenzeImpostazioniHR.get_solo()
        imp.patrono_giorno, imp.patrono_mese, imp.patrono_nome = 29, 6, "San Pietro"
        imp.save()

    def _chiusura(self, da, a):
        from assenze.models import ChiusuraAziendale

        return ChiusuraAziendale.objects.create(data_inizio=da, data_fine=a, descrizione="Ferie estive")

    def test_san_francesco_festa_nazionale_dal_2026(self):
        self.assertIn(date(2027, 10, 4), cal.festivi_nazionali(2027))
        self.assertNotIn(date(2025, 10, 4), cal.festivi_nazionali(2025))
        self.assertFalse(cal.is_lavorativo(date(2027, 10, 4)))  # lunedì

    def test_patrono_e_chiusure_da_assenze(self):
        self._chiusura(date(2026, 8, 10), date(2026, 8, 14))
        self.assertFalse(cal.is_lavorativo(date(2026, 6, 29)))  # lunedì, patrono
        self.assertFalse(cal.is_lavorativo(date(2026, 8, 12)))  # chiusura
        self.assertTrue(cal.is_lavorativo(date(2026, 8, 17)))
        # Termini di legge: le chiusure non contano, il patrono sì.
        legge = cal.festivi_tra(date(2026, 1, 1), date(2026, 12, 31), chiusure=False)
        self.assertNotIn(date(2026, 8, 12), legge)
        self.assertIn(date(2026, 6, 29), legge)

    def test_stessi_giorni_in_tutti_i_moduli(self):
        from assenze import hr
        from gestione_carichi_macchina.saturazione import working_days
        from gestione_specifiche.date_utils import festivi_it
        from scadenzario.calendario import festivi as festivi_scadenzario
        from tasks.services.calendar_it import _build_holidays_set, _is_non_working_day

        self._chiusura(date(2026, 8, 10), date(2026, 8, 14))
        giorni = [date(2026, 6, 29), date(2026, 8, 12), date(2027, 10, 4), date(2026, 4, 6)]
        festivi_tasks = _build_holidays_set(date(2026, 1, 1), date(2027, 12, 31))
        for g in giorni:
            self.assertTrue(_is_non_working_day(g, festivi_tasks), g)
            self.assertIn(g, festivi_it(g.year), g)
            self.assertIn(g, festivi_scadenzario([g.year]), g)
            self.assertFalse(hr.calendario(g, g).lavorativo(g), g)
        self.assertEqual(working_days(giorni), 0)

    def test_rentri_festa_in_mezzo_non_conta(self):
        from rentri.verifica import _giorni_lavorativi

        self._chiusura(date(2026, 4, 27), date(2026, 4, 30))
        # Dal venerdì 24/04 al lunedì 04/05: 25/04 sabato, 01/05 festa; chiusure ignorate.
        self.assertEqual(_giorni_lavorativi(date(2026, 4, 24), date(2026, 5, 4)), 5)

    def test_patrono_vecchio_dello_scadenzario_resta_se_assenze_vuoto(self):
        from assenze.models import AssenzeImpostazioniHR
        from core.models import SiteConfig

        imp = AssenzeImpostazioniHR.get_solo()
        imp.patrono_giorno = imp.patrono_mese = None
        imp.save()
        SiteConfig.set("scadenzario_patrono", "01-31 San Giovanni Bosco", "test")
        cal.svuota_cache()
        self.assertIn(date(2026, 1, 31), cal.festivi_aziendali(2026))
