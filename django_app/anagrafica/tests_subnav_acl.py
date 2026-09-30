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
        # I cancelli sono letti dal sorgente delle view: si patchano gli helper veri.
        with mock.patch("core.middleware.acl_allows_path", return_value=True), \
                mock.patch("anagrafica.views._can_view_formazione", return_value=False), \
                mock.patch("anagrafica.views_recruiting._can_view_recruiting", return_value=False), \
                mock.patch("anagrafica.views._is_anagrafica_admin", return_value=True):
            nav = subnav_anagrafica({"request": self.request})
        labels = self._labels(nav)
        self.assertIn("Dipendenti", labels)
        self.assertIn("Impostazioni", labels)  # la pagina non ha un cancello di pagina
        self.assertNotIn("Recruiting", labels)
        self.assertNotIn("Formazione", labels)  # landing e unico figlio negati

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


def _helper_ok(request, *args):
    return True


def _helper_no(request, *args):
    return False


SOGLIA = "x"


def _view_senza_cancello(request):
    return None


def _view_cancello_diretto(request):
    """Docstring ignorata."""
    if request.method == "POST":
        pass
    if not _helper_ok(request, SOGLIA):
        return None
    if not _helper_no(request, "costante"):
        return None
    return None


def _view_cancello_via_variabile(request):
    is_admin = _helper_no(request)
    if not is_admin:
        return None
    return None


def _view_cancello_dopo_il_return(request):
    return None
    if not _helper_no(request):  # noqa: unreachable
        return None


def _view_parametri_pagina(request, pk):
    if not _helper_no(request, pk):  # dipende dalla pagina: non è un cancello di sezione
        return None
    if not _helper_no(request.user):
        return None
    return None


def _view_cancello_import_locale(request):
    from anagrafica.tests_subnav_acl import _helper_no as nega

    if not nega(request):
        return None
    return None


class PageGatesDetectionTests(TestCase):
    def _names(self, view):
        from anagrafica.subnav_gates import page_gates

        return [g.__name__ for g in page_gates(view)]

    def test_rilevamento(self):
        self.assertEqual(self._names(_view_senza_cancello), [])
        self.assertEqual(self._names(_view_cancello_diretto), ["_helper_ok", "_helper_no"])
        self.assertEqual(self._names(_view_cancello_via_variabile), ["_helper_no"])
        self.assertEqual(self._names(_view_cancello_dopo_il_return), [])
        self.assertEqual(self._names(_view_parametri_pagina), [])
        self.assertEqual(self._names(_view_cancello_import_locale), ["nega"])

    def test_i_cancelli_chiamano_gli_helper_con_gli_argomenti(self):
        from anagrafica.subnav_gates import page_gates

        ok, no = page_gates(_view_cancello_diretto)
        self.assertTrue(ok(object()))
        self.assertFalse(no(object()))
        (nega,) = page_gates(_view_cancello_import_locale)
        self.assertFalse(nega(object()))

    def test_view_reali_del_modulo(self):
        from django.urls import resolve

        from anagrafica.subnav_gates import page_gates

        attesi = {
            "anagrafica:recruiting_list": "_can_view_recruiting",
            "anagrafica:formazione_dashboard": "_can_view_formazione",
            "anagrafica:visite_mediche_dashboard": "_can_view_visite_mediche",
            "anagrafica:onboarding_list": "_check_hr_permission",
            "anagrafica:contratti_import": "_is_anagrafica_admin",
        }
        for route, helper in attesi.items():
            nomi = [g.__name__ for g in page_gates(resolve(reverse(route)).func)]
            self.assertIn(helper, nomi, route)
        # Impostazioni usa is_admin solo per le parti di gestione: nessun cancello.
        self.assertEqual(page_gates(resolve(reverse("anagrafica:impostazioni")).func), ())
