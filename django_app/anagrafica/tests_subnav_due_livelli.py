"""Menu Anagrafica a due livelli: pilastri, sezioni, voce accesa dal percorso, numeri senza doppi conteggi."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from .models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica
from .templatetags.anagrafica_extras import subnav_anagrafica

User = get_user_model()

VOCI_SCADUTE = [
    {"kind": "visita", "scaduta": True},
    {"kind": "formazione", "scaduta": True},
    {"kind": "qualifica", "scaduta": True},
]


class VociDelMenuTests(TestCase):
    def test_organizzazione_e_un_pilastro_con_le_sue_voci(self):
        org = SubnavCategoriaAnagrafica.objects.get(landing_url_value="anagrafica:struttura_org")
        voci = dict(SubnavLinkAnagrafica.objects.filter(categoria=org).values_list("url_value", "gruppo"))
        self.assertEqual(voci["anagrafica:struttura_org"], "Struttura")
        self.assertEqual(voci["anagrafica:mansionario"], "Struttura")
        self.assertEqual(voci["anagrafica:centri_costo"], "Reparti e costi")

    def test_skill_matrix_diventa_abilitazioni(self):
        self.assertFalse(SubnavLinkAnagrafica.objects.filter(gruppo__in=("Skill Matrix", "Trasversale")).exists())
        self.assertEqual(SubnavLinkAnagrafica.objects.get(url_value="anagrafica:matrice_competenze").gruppo, "Abilitazioni")


@override_settings(LEGACY_AUTH_ENABLED=False)
class DueLivelliTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("duelivelli_admin", "duelivelli@example.invalid", "x")

    def setUp(self):
        cache.clear()

    def _barra(self, path, voci=()):
        request = RequestFactory().get(path)
        request.user = self.admin
        request.resolver_match = resolve(path)
        with patch("anagrafica.views._helpers._build_scadenzario_voci", return_value=list(voci)):
            return subnav_anagrafica({"request": request})

    def _pilastro(self, barra, nome):
        return next(i for i in barra["items"] if i["label"].startswith(nome))

    def test_seconda_riga_con_sezioni_e_voci_del_pilastro_acceso(self):
        barra = self._barra(reverse("anagrafica:qualifiche_list"))
        self.assertTrue(self._pilastro(barra, "Competenze")["active"])
        self.assertEqual([s["titolo"] for s in barra["seconda"]["sezioni"]], ["Formazione", "Qualifiche", "Abilitazioni"])
        self.assertEqual([s["titolo"] for s in barra["seconda"]["sezioni"] if s["active"]], ["Qualifiche"])
        self.assertIn("Catalogo qualifiche", [v["label"] for v in barra["seconda"]["voci"]])
        self.assertNotIn("Corsi", [v["label"] for v in barra["seconda"]["voci"]])

    def test_pilastro_senza_gruppi_mostra_solo_le_voci(self):
        barra = self._barra(reverse("anagrafica:costo_orario"))
        self.assertEqual(barra["seconda"]["sezioni"], [])
        self.assertIn("Costo orario", [v["label"] for v in barra["seconda"]["voci"]])

    def test_sottopagina_senza_voce_resta_nel_suo_pilastro(self):
        barra = self._barra(reverse("anagrafica:mansionario_lacune"))
        self.assertTrue(self._pilastro(barra, "Organizzazione")["active"])
        accese = [v["label"] for v in barra["seconda"]["voci"] if v["active"]]
        self.assertEqual(accese, ["Mansionario"])

    def test_dashboard_senza_seconda_riga(self):
        self.assertIsNone(self._barra(reverse("anagrafica:index"))["seconda"])

    def test_pagina_di_sicurezza_senza_voce_accende_il_pilastro(self):
        barra = self._barra(reverse("anagrafica:fattori_rischio_list"))
        self.assertTrue(self._pilastro(barra, "Salute e sicurezza")["active"])
        self.assertEqual(barra["seconda"]["aria"], "Salute e sicurezza")
        self.assertEqual([s["titolo"] for s in barra["seconda"]["sezioni"] if s["active"]], ["Rischi e mansioni"])

    def test_numero_sul_pilastro_non_conta_due_volte_le_visite(self):
        barra = self._barra(reverse("anagrafica:index"), VOCI_SCADUTE)
        # 3 scadenze scadute, di cui una visita: la visita non si somma di nuovo.
        self.assertEqual(self._pilastro(barra, "Salute e sicurezza")["n"], 3)
        self.assertEqual(self._pilastro(barra, "Scadenzario")["n"], 3)

    def test_impostazioni_in_fondo_a_destra(self):
        barra = self._barra(reverse("anagrafica:index"))
        fine = [i["url"] for i in barra["items"] if i.get("fine")]
        self.assertEqual(fine, [reverse("anagrafica:impostazioni")])

    def test_pagina_mostra_le_due_righe_e_le_voci_per_il_telefono(self):
        self.client.force_login(self.admin)
        with patch("anagrafica.views._helpers._build_scadenzario_voci", return_value=[]):
            r = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertContains(r, 'class="hrnav-sub"')
        self.assertContains(r, 'class="hrnav-sub-sez"')
        # Il pannello del telefono legge tutte le voci da qui, anche quelle degli altri pilastri.
        self.assertContains(r, "hrnav-dd-menu")
        self.assertContains(r, reverse("anagrafica:centri_costo"))
        self.assertNotContains(r, "hrnav-caret")
