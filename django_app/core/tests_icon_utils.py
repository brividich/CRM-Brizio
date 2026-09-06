"""Test del ripiego delle icone.

Un'icona può essere un'emoji, e allora va stampata. Ma uno **slug** non
riconosciuto no: stamparlo significa scrivere il nome dell'icona dentro
l'interfaccia. È quello che succedeva nella barra in alto, dove accanto a
KICK-OFF compariva la scritta «check-square».
"""

from django.test import SimpleTestCase

from core.icon_utils import icon_text_or_fallback, resolve_semantic_icon_name


class IconTextFallbackTests(SimpleTestCase):
    def test_uno_slug_non_riconosciuto_non_viene_stampato(self):
        self.assertEqual(icon_text_or_fallback("file-text", "Documenti"), "D")

    def test_un_emoji_resta_un_emoji(self):
        self.assertEqual(icon_text_or_fallback("📊", "Report"), "📊")

    def test_un_simbolo_breve_resta(self):
        self.assertEqual(icon_text_or_fallback("→", "Avanti"), "→")
        self.assertEqual(icon_text_or_fallback("OK", "Stato"), "OK")

    def test_senza_icona_si_usa_l_iniziale_dell_etichetta(self):
        self.assertEqual(icon_text_or_fallback("", "Notizie"), "N")

    def test_senza_icona_e_senza_etichetta_non_si_stampa_nulla(self):
        self.assertEqual(icon_text_or_fallback("", ""), "")


class CheckSquareAliasTests(SimpleTestCase):
    def test_check_square_si_risolve_in_un_icona_vera(self):
        # Era il caso reale che finiva stampato nella barra di navigazione.
        self.assertTrue(resolve_semantic_icon_name("check-square", "KICK-OFF"))
