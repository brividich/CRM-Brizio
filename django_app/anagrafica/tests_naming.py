"""Formato unico del nominativo dipendente: ``COGNOME NOME``, tutto maiuscolo."""
from django.template import Context, Template
from django.test import SimpleTestCase

from anagrafica.forms import DipendenteLegacyForm
from core import naming


class NormalizzaParteTests(SimpleTestCase):
    def test_maiuscolo_resta_maiuscolo(self):
        self.assertEqual(naming.normalizza_parte("BOVA"), "BOVA")

    def test_minuscolo_diventa_maiuscolo(self):
        self.assertEqual(naming.normalizza_parte("bova"), "BOVA")

    def test_iniziali_maiuscole_diventano_maiuscolo(self):
        self.assertEqual(naming.normalizza_parte("Bova"), "BOVA")

    def test_nome_composto_su_piu_parole(self):
        self.assertEqual(naming.normalizza_parte("Maria teresa"), "MARIA TERESA")

    def test_cognome_con_particella_su_due_parole(self):
        self.assertEqual(naming.normalizza_parte("De Lucia"), "DE LUCIA")

    def test_apostrofo_semplice(self):
        self.assertEqual(naming.normalizza_parte("D'Angelo"), "D'ANGELO")

    def test_apostrofo_tipografico(self):
        self.assertEqual(naming.normalizza_parte("Dell’Acqua"), "DELL’ACQUA")

    def test_lettere_accentate(self):
        self.assertEqual(naming.normalizza_parte("Niccolò"), "NICCOLÒ")

    def test_trattino(self):
        self.assertEqual(naming.normalizza_parte("Rossi-Bianchi"), "ROSSI-BIANCHI")

    def test_spazi_multipli_collassati(self):
        self.assertEqual(naming.normalizza_parte("  di   maio  "), "DI MAIO")

    def test_vuoto_e_none(self):
        self.assertEqual(naming.normalizza_parte(""), "")
        self.assertEqual(naming.normalizza_parte(None), "")


class NomeCompletoTests(SimpleTestCase):
    def test_ordine_cognome_poi_nome(self):
        self.assertEqual(naming.nome_completo("LUCA", "BOVA"), "BOVA LUCA")

    def test_ordine_indipendente_dal_casing_in_ingresso(self):
        self.assertEqual(naming.nome_completo("Luca", "bova"), "BOVA LUCA")

    def test_cognome_mancante(self):
        self.assertEqual(naming.nome_completo("Luca", ""), "LUCA")

    def test_nome_mancante(self):
        self.assertEqual(naming.nome_completo(None, "bova"), "BOVA")

    def test_entrambi_mancanti(self):
        self.assertEqual(naming.nome_completo(None, None), "")

    def test_iniziali_seguono_lo_stesso_ordine(self):
        self.assertEqual(naming.iniziali("luca", "bova"), "BL")

    def test_chiave_ordinamento_cognome_nome(self):
        self.assertEqual(naming.chiave_ordinamento("Luca", "Bova"), "BOVA LUCA")


class TemplateTagTests(SimpleTestCase):
    def _render(self, tpl, ctx):
        return Template("{% load anagrafica_extras %}" + tpl).render(Context(ctx))

    def test_nominativo_da_dizionario(self):
        out = self._render("{% nominativo dip %}", {"dip": {"nome": "Luca", "cognome": "Bova"}})
        self.assertEqual(out, "BOVA LUCA")

    def test_nominativo_da_oggetto(self):
        class Dip:
            nome = "Maria Teresa"
            cognome = "Girardi"

        out = self._render("{% nominativo dip %}", {"dip": Dip()})
        self.assertEqual(out, "GIRARDI MARIA TERESA")

    def test_nominativo_con_argomenti_sciolti(self):
        out = self._render(
            "{% nominativo nome=n cognome=c %}", {"n": "pietro", "c": "De Nitto"}
        )
        self.assertEqual(out, "DE NITTO PIETRO")

    def test_iniziali_e_sort(self):
        ctx = {"dip": {"nome": "LUCA", "cognome": "BOVA"}}
        self.assertEqual(self._render("{% nominativo_iniziali dip %}", ctx), "BL")
        self.assertEqual(self._render("{% nominativo_sort dip %}", ctx), "BOVA LUCA")

    def test_filtro_parte_nome(self):
        self.assertEqual(self._render("{{ v|parte_nome }}", {"v": "Bova"}), "BOVA")


class FormNormalizzaTests(SimpleTestCase):
    def test_form_normalizza_nome_e_cognome(self):
        form = DipendenteLegacyForm(data={"nome": "luca", "cognome": "Bova"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["nome"], "LUCA")
        self.assertEqual(form.cleaned_data["cognome"], "BOVA")

    def test_form_senza_cognome_resta_valido(self):
        form = DipendenteLegacyForm(data={"nome": "LUCA"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cognome"], "")
