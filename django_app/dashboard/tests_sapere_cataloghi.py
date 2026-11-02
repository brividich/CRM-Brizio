"""Stanza «Sapere»: cataloghi, copertine con immagine, visibilità per ruolo."""
from __future__ import annotations

import io
import json
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core import sapere
from core.copertine import CopertinaNonValida, prepara_copertina
from core.models import Catalogo, CatalogoRoleAccess, CatalogoVoce, HubLink, HubLinkCategory, HubLinkRoleAccess

_TMP = tempfile.mkdtemp(prefix="pn-sapere-test-")


def _immagine(nome="foto.png", formato="PNG", dim=(2400, 1200), exif=False) -> SimpleUploadedFile:
    from PIL import Image

    img = Image.new("RGB", dim, (200, 60, 30))
    buf = io.BytesIO()
    kwargs = {}
    if exif:
        dati = Image.Exif()
        dati[0x010F] = "MarcaDiProva"  # Make
        kwargs["exif"] = dati.tobytes()
    img.save(buf, format=formato, **kwargs)
    return SimpleUploadedFile(nome, buf.getvalue(), content_type=f"image/{formato.lower()}")


def _utente(role_id=7, admin=False):
    return sapere.Identita(role_id=role_id, is_admin=admin, guide_admin=admin)


@override_settings(HUB_BACHECA_PRIVATE_ROOT=_TMP, DOCUMENT_ENCRYPTION_KEY="")
class CopertineTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP, ignore_errors=True)

    def test_ricodifica_in_jpeg_ridotto_senza_exif(self):
        from PIL import Image

        out = prepara_copertina(_immagine("scatto.jpg", "JPEG", exif=True))
        self.assertTrue(out.name.endswith(".jpg"))
        img = Image.open(io.BytesIO(out.read()))
        self.assertEqual(img.format, "JPEG")
        self.assertLessEqual(max(img.size), 1200)
        self.assertNotIn(0x010F, img.getexif())

    def test_png_trasparente_su_fondo_bianco(self):
        from PIL import Image

        img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = prepara_copertina(SimpleUploadedFile("t.png", buf.getvalue()))
        self.assertEqual(Image.open(io.BytesIO(out.read())).getpixel((5, 5)), (255, 255, 255))

    def test_rifiuta_estensione_e_file_non_immagine(self):
        with self.assertRaises(CopertinaNonValida):
            prepara_copertina(SimpleUploadedFile("x.gif", b"GIF89a"))
        with self.assertRaises(CopertinaNonValida):
            prepara_copertina(SimpleUploadedFile("finta.jpg", b"%PDF-1.4 non sono un'immagine"))


class VisibilitaCataloghiTests(TestCase):
    def setUp(self):
        self.cat_bacheca = HubLinkCategory.objects.create(name="IT", slug="it", sezione="self_help", colore="#123456")
        self.link = HubLink.objects.create(category=self.cat_bacheca, kind=HubLink.KIND_URL,
                                           title="Collegarsi tramite VPN", url="https://e.local/vpn")
        self.catalogo = Catalogo.objects.create(titolo="Primo giorno", slug="primo-giorno")

    def test_catalogo_senza_ruoli_visibile_a_tutti_con_ruoli_solo_a_quelli(self):
        self.assertTrue(sapere.catalogo_visibile(self.catalogo, _utente(7)))
        CatalogoRoleAccess.objects.create(catalogo=self.catalogo, legacy_role_id=3)
        cat = Catalogo.objects.prefetch_related("role_accesses").get(pk=self.catalogo.pk)
        self.assertFalse(sapere.catalogo_visibile(cat, _utente(7)))
        self.assertTrue(sapere.catalogo_visibile(cat, _utente(3)))
        self.assertFalse(sapere.catalogo_visibile(cat, _utente(None)))
        self.assertTrue(sapere.catalogo_visibile(cat, _utente(None, admin=True)))

    def test_catalogo_nascosto_non_compare(self):
        self.catalogo.is_visible = False
        self.catalogo.save()
        self.assertEqual(sapere.cataloghi_visibili(_utente(admin=True)), [])

    def test_voci_seguono_i_permessi_della_fonte(self):
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="risorsa", hub_link=self.link, ordine=10)
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="guida", guida_slug="assenze", ordine=20)
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="guida", guida_slug="emergenza", ordine=30)
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="guida", guida_slug="non-esiste", ordine=40)
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="collegamento", titolo="La mia scheda",
                                    url="/anagrafica/la-mia-scheda/", ordine=50)
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="collegamento", titolo="Cattivo",
                                    url="javascript:alert(1)", ordine=60)
        titoli = [v["titolo"] for v in sapere.voci_visibili(self.catalogo, _utente(7))]
        self.assertEqual(titoli[0], "Collegarsi tramite VPN")
        self.assertIn("La mia scheda", titoli)
        self.assertNotIn("Cattivo", titoli)
        self.assertEqual(len(titoli), 3)  # risorsa, guida assenze, collegamento: niente emergenza (solo admin)

        # Risorsa riservata a un altro ruolo: sparisce dal catalogo.
        HubLinkRoleAccess.objects.create(link=self.link, legacy_role_id=3)
        titoli = [v["titolo"] for v in sapere.voci_visibili(self.catalogo, _utente(7))]
        self.assertNotIn("Collegarsi tramite VPN", titoli)
        # L'amministratore vede anche la guida di emergenza.
        self.assertEqual(len(sapere.voci_visibili(self.catalogo, _utente(admin=True))), 4)

    def test_catalogo_vuoto_non_va_in_home(self):
        self.assertEqual(sapere.schede_cataloghi(_utente()), [])
        CatalogoVoce.objects.create(catalogo=self.catalogo, tipo="guida", guida_slug="assenze")
        self.assertEqual([s["titolo"] for s in sapere.schede_cataloghi(_utente())], ["Primo giorno"])

    def test_url_collegamento(self):
        for buono in ("/anagrafica/", "https://e.local", "http://intranet.local/x"):
            self.assertTrue(sapere.url_collegamento_valido(buono), buono)
        for cattivo in ("//evil.example", "javascript:alert(1)", "", "ftp://x", "/\\evil"):
            self.assertFalse(sapere.url_collegamento_valido(cattivo), cattivo)


@override_settings(HUB_BACHECA_PRIVATE_ROOT=_TMP, DOCUMENT_ENCRYPTION_KEY="")
class PagineSapereTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm-sapere", email="a@a.it", password="x")
        self.client.force_login(self.admin)

    def test_rotte_condivise(self):
        from core.middleware import is_acl_shared_path

        cat = Catalogo.objects.create(titolo="IT", slug="it")
        for url in (reverse("sapere_cataloghi"), reverse("sapere_catalogo", args=["it"]),
                    reverse("sapere_copertina", args=["catalogo", cat.pk])):
            self.assertTrue(is_acl_shared_path(url), url)

    def test_crea_catalogo_con_copertina_e_voci_poi_pagina_e_home(self):
        r = self.client.post(reverse("admin_portale:sapere_cataloghi"), {
            "titolo": "Primo giorno in azienda", "descrizione": "Da leggere il primo giorno",
            "colore": "#0F766E", "copertina": _immagine(),
        })
        cat = Catalogo.objects.get()
        self.assertRedirects(r, reverse("admin_portale:sapere_catalogo", args=[cat.pk]), fetch_redirect_response=False)
        self.assertEqual((cat.slug, cat.colore), ("primo-giorno-in-azienda", "#0f766e"))
        self.assertTrue(cat.copertina.name.endswith(".jpg"))

        url_cat = reverse("admin_portale:sapere_catalogo", args=[cat.pk])
        self.client.post(url_cat, {"azione": "aggiungi_voce", "tipo": "guida", "guida_slug": "assenze"})
        self.client.post(url_cat, {"azione": "aggiungi_voce", "tipo": "collegamento",
                                   "titolo": "La mia scheda", "url": "/anagrafica/la-mia-scheda/"})
        self.client.post(url_cat, {"azione": "aggiungi_voce", "tipo": "collegamento",
                                   "titolo": "Sito", "url": "//evil.example"})
        self.assertEqual(cat.voci.count(), 2)

        pagina = self.client.get(reverse("sapere_catalogo", args=[cat.slug]))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Primo giorno in azienda")
        self.assertContains(pagina, "La mia scheda")
        self.assertContains(pagina, reverse("guida_modulo", args=["assenze"]))
        self.assertContains(pagina, reverse("sapere_copertina", args=["catalogo", cat.pk]))

        img = self.client.get(reverse("sapere_copertina", args=["catalogo", cat.pk]))
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img["Content-Type"], "image/jpeg")
        self.assertTrue(b"".join(img.streaming_content).startswith(b"\xff\xd8"))

        home = self.client.get(reverse("home_portale:index"))
        self.assertContains(home, "Cataloghi")
        self.assertContains(home, reverse("sapere_catalogo", args=[cat.slug]))

    def test_ordina_e_togli_voci_ed_elimina_catalogo(self):
        cat = Catalogo.objects.create(titolo="IT", slug="it")
        a = CatalogoVoce.objects.create(catalogo=cat, tipo="guida", guida_slug="assenze", ordine=10)
        b = CatalogoVoce.objects.create(catalogo=cat, tipo="guida", guida_slug="timbri", ordine=20)
        url = reverse("admin_portale:sapere_catalogo", args=[cat.pk])
        self.client.post(url, {"azione": "voce_su", "voce_id": b.pk})
        self.assertEqual(list(cat.voci.order_by("ordine").values_list("pk", flat=True)), [b.pk, a.pk])
        self.client.post(url, {"azione": "voce_elimina", "voce_id": a.pk})
        self.assertEqual(cat.voci.count(), 1)
        self.client.post(url, {"azione": "elimina"})
        self.assertFalse(Catalogo.objects.exists())

    def test_copertina_risorsa_bacheca(self):
        cat = HubLinkCategory.objects.create(name="IT", slug="it-b", sezione="self_help")
        link = HubLink.objects.create(category=cat, kind=HubLink.KIND_URL, title="VPN", url="https://e.local")
        r = self.client.post(reverse("admin_portale:api_hub_link_copertina"), {"id": link.pk, "copertina": _immagine()})
        self.assertEqual(json.loads(r.content)["ok"], True)
        link.refresh_from_db()
        self.assertTrue(link.copertina)
        home = self.client.get(reverse("home_portale:index"))
        self.assertContains(home, link.copertina_url)
        r = self.client.post(reverse("admin_portale:api_hub_link_copertina"),
                             {"id": link.pk, "copertina": SimpleUploadedFile("x.jpg", b"no")})
        self.assertEqual(r.status_code, 400)
        self.client.post(reverse("admin_portale:api_hub_link_copertina"), {"id": link.pk, "rimuovi": "1"})
        link.refresh_from_db()
        self.assertFalse(link.copertina)

    def test_crea_risorsa_multipart_con_copertina_e_ruoli(self):
        cat = HubLinkCategory.objects.create(name="IT", slug="it-c", sezione="self_help")
        r = self.client.post(reverse("admin_portale:api_hub_link_create"), {
            "category_id": cat.pk, "kind": "url", "title": "VPN", "url": "https://e.local",
            "role_ids": ["3", "4"], "copertina": _immagine(),
        })
        self.assertEqual(json.loads(r.content)["ok"], True)
        link = HubLink.objects.get()
        self.assertTrue(link.copertina)
        self.assertEqual(sorted(link.role_accesses.values_list("legacy_role_id", flat=True)), [3, 4])

    def test_catalogo_inesistente_o_nascosto_404(self):
        Catalogo.objects.create(titolo="Nascosto", slug="nascosto", is_visible=False)
        self.assertEqual(self.client.get(reverse("sapere_catalogo", args=["nascosto"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("sapere_catalogo", args=["boh"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("sapere_copertina", args=["altro", 1])).status_code, 404)

    def test_voce_menu_admin(self):
        from core.models import NavigationItem

        self.assertTrue(NavigationItem.objects.filter(code="admin-sapere-cataloghi",
                                                      route_name="admin_portale:sapere_cataloghi").exists())
