"""Minimappa degli asset nei ticket di manutenzione (assets.services.mappa_ticket)."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from anagrafica.models import AreaAziendale, Reparto
from assets.models import Asset, AssetCategory, PlantLayout, PlantLayoutArea, PlantLayoutMarker, RepartoAssetCollegato
from assets.services.mappa_ticket import MODALITA_AREE, indice_unita, mappe, stesso_reparto, unita_utente
from tickets.models import CategoriaTicket, Ticket, TicketImpostazioni, TipoTicket
from tickets.tests import _complete_onboarding
from tickets.views import _get_assets_for_select, _get_my_assets


def _png(name: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "#ffffff").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class _ConPlanimetria(TestCase):
    def setUp(self):
        super().setUp()
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        media = override_settings(MEDIA_ROOT=Path(self._media.name))
        media.enable()
        self.addCleanup(media.disable)
        self.torni = Reparto.objects.create(nome="Torni")
        self.cnc = Reparto.objects.create(nome="CNC")
        self.area_tnc = AreaAziendale.objects.create(nome="TNC", reparto=self.torni)
        self.hvac = PlantLayout.objects.create(
            category="Heating, Ventilation and Air Conditioning", name="Planimetria Condizionatori",
            image=_png("hvac.png"), is_active=True,
        )
        chiller = AssetCategory.objects.create(code="chiller", label="Chiller", sinonimi="condizionatore, clima")
        self.mio = Asset.objects.create(asset_tag="HVAC-1", name="Chiller 2206", reparto="tnc",
                                        asset_type=Asset.TYPE_OTHER, asset_category=chiller)
        self.altro = Asset.objects.create(asset_tag="HVAC-2", name="Chiller 5C00", reparto="CNC",
                                          asset_type=Asset.TYPE_OTHER, asset_category=chiller)
        self.collegato = Asset.objects.create(asset_tag="HVAC-3", name="Bruciatore 22U", reparto="Torn.",
                                              asset_type=Asset.TYPE_OTHER)
        self.pc = Asset.objects.create(asset_tag="PC-1", name="PC ufficio", reparto="Torni", asset_type="PC")
        self.da_collocare = Asset.objects.create(asset_tag="HVAC-4", name="Chiller nuovo", reparto="Torni",
                                                 asset_type=Asset.TYPE_OTHER)
        RepartoAssetCollegato.objects.create(testo="Torn.", chiave="torn.", reparto=self.torni)
        for asset, x in ((self.mio, 20), (self.altro, 60), (self.collegato, 30), (self.pc, 40)):
            PlantLayoutMarker.objects.create(layout=self.hvac, asset=asset, x_percent=x, y_percent=25)
        PlantLayoutMarker.objects.create(layout=self.hvac, asset=self.da_collocare, x_percent=50, y_percent=50)


class MappaTicketServizioTests(_ConPlanimetria):
    def test_reparto_riconosciuto_da_nome_area_e_collegamento(self):
        indice = indice_unita()
        mie = unita_utente("Torni", None, indice)
        self.assertTrue(stesso_reparto("TNC", mie, indice))  # area del reparto
        self.assertTrue(stesso_reparto("  torn. ", mie, indice))  # testo collegato a mano
        self.assertFalse(stesso_reparto("CNC", mie, indice))
        # chi sta in un'area non ha le altre aree o il reparto intero
        mie_area = unita_utente("TNC", None, indice)
        self.assertFalse(stesso_reparto("Torni", mie_area, indice))
        self.assertTrue(stesso_reparto("tnc", mie_area, indice))

    def test_capo_vede_i_suoi_reparti_anche_senza_reparto_scritto(self):
        self.cnc.caporeparto_legacy_id = 77
        self.cnc.save()
        indice = indice_unita()
        self.assertTrue(stesso_reparto("CNC", unita_utente("", 77, indice), indice))

    def test_mappe_solo_asset_non_it_collocati_e_mio_dal_testo(self):
        (pianta,) = mappe("Torni")
        per_id = {m["asset_id"]: m for m in pianta["markers"]}
        self.assertEqual(set(per_id), {self.mio.pk, self.altro.pk, self.collegato.pk})
        self.assertTrue(per_id[self.mio.pk]["mio"])
        self.assertTrue(per_id[self.collegato.pk]["mio"])
        self.assertFalse(per_id[self.altro.pk]["mio"])
        self.assertEqual(per_id[self.mio.pk]["categoria"], "Chiller")
        self.assertEqual(pianta["mie"], 2)

    def test_modalita_aree_usa_i_riquadri_e_senza_aree_torna_al_testo(self):
        (pianta,) = mappe("Torni", modalita=MODALITA_AREE)
        self.assertFalse(pianta["da_aree"])
        self.assertEqual(pianta["mie"], 2)
        PlantLayoutArea.objects.create(layout=self.hvac, name="Zona CNC", reparto_code="CNC",
                                       x_percent=55, y_percent=0, width_percent=20, height_percent=50)
        (pianta,) = mappe("CNC", modalita=MODALITA_AREE)
        self.assertTrue(pianta["da_aree"])
        mie = {m["asset_id"] for m in pianta["markers"] if m["mio"]}
        self.assertEqual(mie, {self.altro.pk})

    def test_filtri_per_dettaglio(self):
        altra = PlantLayout.objects.create(category="Officina", name="Officina", image=_png("o.png"), is_active=True)
        self.assertEqual([m["id"] for m in mappe(solo_asset=self.mio.pk)], [self.hvac.pk])
        self.assertEqual([m["id"] for m in mappe(solo_layout=altra.pk)], [altra.pk])

    def test_miei_asset_del_reparto_con_testo_corretto(self):
        items, label = _get_my_assets(None, "", "Torni", TipoTicket.MAN)
        self.assertEqual({i["id"] for i in items}, {self.mio.pk, self.collegato.pk, self.da_collocare.pk})
        self.assertIn("Torni", label)

    def test_ricerca_con_sinonimi_della_categoria(self):
        dati = {a["id"]: a for a in _get_assets_for_select()}
        self.assertIn("condizionatore", dati[self.mio.pk]["sinonimi"])
        self.assertEqual(dati[self.collegato.pk]["sinonimi"], "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MappaTicketVisteTests(_ConPlanimetria):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="capo-tnc", password="x", is_superuser=True)
        _complete_onboarding(self.user)
        self.client.force_login(self.user)

    def _post(self, **extra):
        payload = {
            "tipo": "MAN", "incide_sicurezza": "0", "categoria": "GENERICA", "priorita": "MEDIA",
            "titolo": "Condizionatore guasto", "descrizione": "Non raffredda",
        }
        payload.update(extra)
        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._legacy_identity", return_value=("Capo", "capo@example.com", None)),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        ):
            return self.client.post(reverse("tickets:nuovo"), payload)

    def test_form_manutenzione_ha_la_mappa_e_quello_it_no(self):
        with patch("tickets.views._can_open_tickets", return_value=True):
            man = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            it = self.client.get(reverse("tickets:nuovo") + "?tipo=IT")
        self.assertContains(man, 'id="tkt-mappa"')
        self.assertContains(man, "mappe-ticket-data")
        self.assertNotContains(it, 'id="tkt-mappa"')

    def test_punto_sulla_mappa_senza_asset(self):
        resp = self._post(mappa_layout_id=str(self.hvac.pk), mappa_x="42.5", mappa_y="17.25")
        self.assertEqual(resp.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertIsNone(ticket.asset_id)
        self.assertEqual(ticket.mappa_layout_id, self.hvac.pk)
        self.assertEqual(str(ticket.mappa_x), "42.50")
        self.assertIn("Planimetria Condizionatori", ticket.asset_descrizione_libera)

    def test_punto_fuori_pianta_ignorato(self):
        resp = self._post(mappa_layout_id=str(self.hvac.pk), mappa_x="140", mappa_y="10")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ticket.objects.exists())

    def test_asset_scelto_dalla_mappa(self):
        self._post(asset_id=str(self.mio.pk))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.asset_id, self.mio.pk)
        self.assertIsNone(ticket.mappa_layout_id)

    def test_dettaglio_e_gestione_mostrano_dove_si_trova(self):
        self._post(asset_id=str(self.mio.pk))
        ticket = Ticket.objects.get()
        det = self.client.get(reverse("tickets:detail", args=[ticket.pk]))
        self.assertContains(det, "Dove si trova")
        self.assertEqual([m["id"] for m in det.context["mappe_ticket"]], [self.hvac.pk])
        with patch("tickets.views._can_manage_tickets", return_value=True):
            gest = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk]))
        self.assertContains(gest, 'id="mappa-card"')
        self.assertContains(gest, f"tktMappa.mostraAsset({self.mio.pk})")

    def test_impostazioni_salvano_modalita_e_planimetria_per_categoria(self):
        cat = CategoriaTicket.objects.create(tipo=TipoTicket.MAN, codice="CLIMA", etichetta="Climatizzazione")
        resp = self.client.post(reverse("tickets:impostazioni"), {
            "action": "save_mappa_config",
            "mappa_reparto_da": "aree",
            f"planimetria_{cat.pk}": "heating, ventilation and air conditioning",
        })
        self.assertEqual(resp.status_code, 302)
        cat.refresh_from_db()
        self.assertEqual(cat.planimetria, self.hvac.category)
        self.assertEqual(TicketImpostazioni.objects.get(tipo=TipoTicket.MAN).mappa_reparto_da, "aree")
        pagina = self.client.get(reverse("tickets:impostazioni"))
        self.assertContains(pagina, "Mappa asset nei ticket di manutenzione")
