"""Ambito «Propri» su allegati, documenti, componenti e Storico: niente record di asset altrui. Dati sintetici."""
from __future__ import annotations

from datetime import date

from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

from anagrafica.models import Reparto
from core.models import AccessGroup, AccessGroupMembership, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.permessi.preset import applica_preset
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

from .models import (
    Asset,
    AssetComponent,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
)
from .registro_permessi import MODULO_INVENTARIO, MODULO_MANUTENZIONE
from .urls import _protezioni_per_record


class VisibilitaAllegatiTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()
        ensure_anagrafica_table()
        self.car, self.car_legacy = self.persona("Capo Sintetico")
        ruolo = AccessGroup.objects.create(code="syn-car-all", label="CAR sintetico", priority=900)
        for modulo in (MODULO_INVENTARIO, MODULO_MANUTENZIONE):
            RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo=modulo, azione="vedere", ambito="propri")
        AccessGroupMembership.objects.create(group=ruolo, legacy_user_id=self.car_legacy.id)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, utente_id) VALUES (%s, %s, %s, %s, %s)",
                [9301, "Capo", "Sintetico", "CN5", self.car_legacy.id],
            )
        Reparto.objects.create(nome="CN5", caporeparto_legacy_id=9301)
        Reparto.objects.create(nome="CN6")
        self.mio = Asset.objects.create(asset_tag="SYN-A5", name="Fresa CN5", asset_type=Asset.TYPE_CNC, reparto="CN5")
        self.altro = Asset.objects.create(asset_tag="SYN-A6", name="Fresa CN6", asset_type=Asset.TYPE_CNC,
                                          reparto="CN6")
        plan = MaintenanceInterventionTemplate.objects.create(code="syn-olio", label="Olio")
        self.occ_altro = MaintenanceOccurrence.objects.create(plan=plan, asset=self.altro, due_date=date(2026, 1, 10))
        self.occ_mio = MaintenanceOccurrence.objects.create(plan=plan, asset=self.mio, due_date=date(2026, 1, 10))
        self.att_altro = MaintenanceOccurrenceAttachment.objects.create(occurrence=self.occ_altro, file="x/altro.pdf")
        self.att_mio = MaintenanceOccurrenceAttachment.objects.create(occurrence=self.occ_mio, file="x/mio.pdf")
        self.comp_altro = AssetComponent.objects.create(asset=self.altro, name="Mandrino")
        self.attiva_sistema()

    def tearDown(self):
        cache.clear()
        invalida_permessi()

    def _request(self, path="/assets/"):
        request = RequestFactory().get(path)
        request.user = self.ricarica(self.car)
        request.session = {}
        return request

    def test_download_protetti_per_record(self):
        for name, kwargs, kwarg in (
            ("assets:occurrence_attachment_download", {"attachment_id": 1}, "attachment_id"),
            ("assets:workorder_attachment_download", {"attachment_id": 1}, "attachment_id"),
            ("assets:asset_document_download", {"document_id": 1}, "document_id"),
            ("assets:asset_component_edit", {"id": 1}, "id"),
        ):
            with self.subTest(name=name):
                func = resolve(reverse(name, kwargs=kwargs)).func
                self.assertEqual(getattr(func, "record_visibile_kwarg", None), kwarg)

    def test_allegato_manutenzione_di_altro_reparto_403(self):
        url = reverse("assets:occurrence_attachment_download", kwargs={"attachment_id": self.att_altro.pk})
        response = resolve(url).func(self._request(url), attachment_id=self.att_altro.pk)
        self.assertEqual(response.status_code, 403)

    def test_filtro_allegati_lascia_solo_i_propri(self):
        modello, filtra = _protezioni_per_record()["attachment_id@scadenze-manutenzione"][1]
        visibili = set(filtra(self._request(), modello.objects.all()).values_list("pk", flat=True))
        self.assertEqual(visibili, {self.att_mio.pk})

    def test_componente_di_altro_reparto_403(self):
        url = reverse("assets:asset_component_edit", kwargs={"id": self.comp_altro.pk})
        response = resolve(url).func(self._request(url), id=self.comp_altro.pk)
        self.assertEqual(response.status_code, 403)
