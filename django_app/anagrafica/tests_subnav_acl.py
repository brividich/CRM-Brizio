"""Subnav Anagrafica: le voci che l'utente non può aprire non vengono mostrate."""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from anagrafica.models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica
from anagrafica.templatetags.anagrafica_extras import subnav_anagrafica


class SubnavAclFilterTests(TestCase):
    def setUp(self):
        SubnavLinkAnagrafica.objects.all().delete()
        SubnavCategoriaAnagrafica.objects.all().delete()
        self.cat = SubnavCategoriaAnagrafica.objects.create(
            nome="Formazione", ordine=10, is_active=True,
            landing_url_type="named", landing_url_value="anagrafica:formazione_dashboard",
        )
        SubnavLinkAnagrafica.objects.create(
            etichetta="Dipendenti", url_type="named", url_value="anagrafica:dipendenti_list",
            ordine=1, is_active=True,
        )
        SubnavLinkAnagrafica.objects.create(
            etichetta="Impostazioni", url_type="named", url_value="anagrafica:impostazioni",
            ordine=2, is_active=True,
        )
        SubnavLinkAnagrafica.objects.create(
            etichetta="Corsi", url_type="named", url_value="anagrafica:formazione_piani_list",
            categoria=self.cat, ordine=11, is_active=True,
        )
        SubnavLinkAnagrafica.objects.create(
            etichetta="Esterno", url_type="raw", url_value="https://example.invalid/doc",
            ordine=3, is_active=True,
        )
        self.user = get_user_model().objects.create_user(username="subnav_acl_u", password="x")
        self.request = RequestFactory().get(reverse("anagrafica:dipendenti_list"))
        self.request.user = self.user

    def _labels(self, nav):
        out = []
        for item in nav["items"]:
            out.append(item["label"])
            out.extend(c["label"] for c in item.get("links", []) if item["type"] == "category")
        return out

    def _run(self, allowed_paths, gate=True):
        def fake(path, **kwargs):
            return path in allowed_paths

        with mock.patch("core.middleware.acl_allows_path", side_effect=fake) as patched, \
                mock.patch("anagrafica.subnav_gates.section_gate_allows", return_value=gate):
            nav = subnav_anagrafica({"request": self.request})
        return nav, patched

    def test_cancello_di_sezione_nasconde_anche_con_acl_concessa(self):
        # ACL concessa ovunque, ma il cancello in-view della formazione dice no.
        SubnavLinkAnagrafica.objects.create(
            etichetta="Recruiting", url_type="named", url_value="anagrafica:recruiting_list",
            ordine=4, is_active=True,
        )
        from anagrafica.subnav_gates import SECTION_GATES

        nega = lambda request: False  # noqa: E731
        with mock.patch("core.middleware.acl_allows_path", return_value=True), \
                mock.patch.dict(SECTION_GATES, {
                    "anagrafica:formazione_dashboard": nega,
                    "anagrafica:formazione_piani_list": nega,
                    "anagrafica:recruiting_list": nega,
                }):
            nav = subnav_anagrafica({"request": self.request})
        labels = self._labels(nav)
        self.assertIn("Dipendenti", labels)
        self.assertIn("Impostazioni", labels)  # nessun cancello di pagina registrato
        self.assertNotIn("Recruiting", labels)
        self.assertNotIn("Formazione", labels)  # landing e unico figlio negati

    def test_registro_cancelli_solo_route_esistenti(self):
        from anagrafica.subnav_gates import SECTION_GATES

        for name in SECTION_GATES:
            reverse(name)  # NoReverseMatch = voce del registro morta

    def test_nasconde_voci_non_accessibili(self):
        allowed = {reverse("anagrafica:dipendenti_list")}
        nav, _ = self._run(allowed)
        labels = self._labels(nav)
        self.assertIn("Dipendenti", labels)
        self.assertNotIn("Impostazioni", labels)
        # Categoria con tutti i figli negati: sparisce.
        self.assertNotIn("Formazione", labels)
        # Link esterno: fuori dal perimetro ACL, resta.
        self.assertIn("Esterno", labels)

    def test_landing_negata_categoria_resta_dropdown(self):
        allowed = {reverse("anagrafica:formazione_piani_list")}
        nav, _ = self._run(allowed)
        cat = next(i for i in nav["items"] if i["type"] == "category")
        self.assertEqual(cat["landing_url"], "")
        self.assertEqual([c["label"] for c in cat["links"]], ["Corsi"])

    def test_tutto_consentito(self):
        allowed = {
            reverse("anagrafica:dipendenti_list"),
            reverse("anagrafica:impostazioni"),
            reverse("anagrafica:formazione_piani_list"),
            reverse("anagrafica:formazione_dashboard"),
        }
        nav, patched = self._run(allowed)
        labels = self._labels(nav)
        for label in ("Dipendenti", "Impostazioni", "Formazione", "Corsi"):
            self.assertIn(label, labels)
        cat = next(i for i in nav["items"] if i["type"] == "category")
        self.assertEqual(cat["landing_url"], reverse("anagrafica:formazione_dashboard"))
        # Un controllo per path, mai per il link esterno.
        checked = [c.args[0] for c in patched.call_args_list]
        self.assertEqual(len(checked), len(set(checked)))
        self.assertNotIn("https://example.invalid/doc", checked)
