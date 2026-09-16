"""Formato unico del nominativo dipendente: ``Nome Cognome``, iniziali maiuscole."""
from django.template import Context, Template
from django.test import SimpleTestCase

from anagrafica.forms import DipendenteLegacyForm
from core import naming


class NormalizzaParteTests(SimpleTestCase):
    def test_maiuscolo_diventa_iniziale_maiuscola(self):
        self.assertEqual(naming.normalizza_parte("BOVA"), "Bova")

    def test_minuscolo_diventa_iniziale_maiuscola(self):
        self.assertEqual(naming.normalizza_parte("bova"), "Bova")

    def test_nome_composto_su_piu_parole(self):
        self.assertEqual(naming.normalizza_parte("MARIA TERESA"), "Maria Teresa")

    def test_cognome_con_particella_su_due_parole(self):
        self.assertEqual(naming.normalizza_parte("DE LUCIA"), "De Lucia")

    def test_apostrofo_semplice(self):
        self.assertEqual(naming.normalizza_parte("D'ANGELO"), "D'Angelo")

    def test_apostrofo_tipografico(self):
        self.assertEqual(naming.normalizza_parte("DELL’ACQUA"), "Dell’Acqua")

    def test_apostrofo_finale_resta_tale(self):
        self.assertEqual(naming.normalizza_parte("NICCOLO'"), "Niccolo'")

    def test_trattino(self):
        self.assertEqual(naming.normalizza_parte("ROSSI-BIANCHI"), "Rossi-Bianchi")

    def test_spazi_multipli_collassati(self):
        self.assertEqual(naming.normalizza_parte("  DI   MAIO  "), "Di Maio")

    def test_vuoto_e_none(self):
        self.assertEqual(naming.normalizza_parte(""), "")
        self.assertEqual(naming.normalizza_parte(None), "")


class NomeCompletoTests(SimpleTestCase):
    def test_ordine_nome_poi_cognome(self):
        self.assertEqual(naming.nome_completo("LUCA", "BOVA"), "Luca Bova")

    def test_ordine_indipendente_dal_casing_in_ingresso(self):
        self.assertEqual(naming.nome_completo("Luca", "bova"), "Luca Bova")

    def test_cognome_mancante(self):
        self.assertEqual(naming.nome_completo("LUCA", ""), "Luca")

    def test_entrambi_mancanti(self):
        self.assertEqual(naming.nome_completo(None, None), "")

    def test_iniziali_seguono_lo_stesso_ordine(self):
        self.assertEqual(naming.iniziali("LUCA", "BOVA"), "LB")

    def test_chiave_ordinamento_resta_cognome_nome(self):
        self.assertEqual(naming.chiave_ordinamento("LUCA", "BOVA"), "Bova Luca")


class TemplateTagTests(SimpleTestCase):
    def _render(self, tpl, ctx):
        return Template("{% load anagrafica_extras %}" + tpl).render(Context(ctx))

    def test_nominativo_da_dizionario(self):
        out = self._render("{% nominativo dip %}", {"dip": {"nome": "LUCA", "cognome": "BOVA"}})
        self.assertEqual(out, "Luca Bova")

    def test_nominativo_da_oggetto(self):
        class Dip:
            nome = "MARIA TERESA"
            cognome = "GIRARDI"

        out = self._render("{% nominativo dip %}", {"dip": Dip()})
        self.assertEqual(out, "Maria Teresa Girardi")

    def test_nominativo_con_argomenti_sciolti(self):
        out = self._render(
            "{% nominativo nome=n cognome=c %}", {"n": "pietro", "c": "DE NITTO"}
        )
        self.assertEqual(out, "Pietro De Nitto")

    def test_iniziali_e_sort(self):
        ctx = {"dip": {"nome": "LUCA", "cognome": "BOVA"}}
        self.assertEqual(self._render("{% nominativo_iniziali dip %}", ctx), "LB")
        self.assertEqual(self._render("{% nominativo_sort dip %}", ctx), "Bova Luca")

    def test_filtro_parte_nome(self):
        self.assertEqual(self._render("{{ v|parte_nome }}", {"v": "BOVA"}), "Bova")


class FormNormalizzaTests(SimpleTestCase):
    def test_form_normalizza_nome_e_cognome(self):
        form = DipendenteLegacyForm(data={"nome": "luca", "cognome": "BOVA"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["nome"], "Luca")
        self.assertEqual(form.cleaned_data["cognome"], "Bova")

    def test_form_senza_cognome_resta_valido(self):
        form = DipendenteLegacyForm(data={"nome": "LUCA"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cognome"], "")
