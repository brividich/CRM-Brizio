"""Ricerca di Anagrafica: casella su tutto il modulo (dashboard) e una per sezione.

Ogni gruppo di risultati entra solo con il permesso della sezione da cui viene; nelle
visite si vedono tipo e scadenza, mai l'esito. Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DipendenteQualifica, TipoQualifica, TipoVisitaMedica, VisitaMedica
from .models_recruiting import Candidato, PosizioneAperta
from .models_reportistica import ReportModello
from .tests import _ensure_anagrafica_table
from .tests_exports_persone import _insert_dipendente

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RicercaAnagraficaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser("ric_admin", "ric@example.invalid", "x")
        cls.utente = User.objects.create_user("ric_utente", "ric_u@example.invalid", "x")
        cls.lid = _insert_dipendente(8701, "Mario", "Zanzibar", reparto="SALDATURA", mansione="Saldatore")
        oggi = timezone.localdate()
        cls.tipo_v = TipoVisitaMedica.objects.create(nome="Periodica Zanzibar", durata_mesi=12, obbligatoria=True)
        VisitaMedica.objects.create(legacy_anagrafica_id=cls.lid, tipo=cls.tipo_v, data_svolgimento=oggi - timedelta(days=30),
                                    data_scadenza=oggi + timedelta(days=330),
                                    esito=VisitaMedica.Esito.IDONEO_CON_LIMITAZIONI)
        tq = TipoQualifica.objects.create(nome="Patentino Zanzibar", categoria=TipoQualifica.CAT_PROFESSIONALE, durata_mesi=24)
        DipendenteQualifica.objects.create(legacy_anagrafica_id=cls.lid, tipo=tq, data_scadenza=oggi + timedelta(days=90))
        cls.pos = PosizioneAperta.objects.create(titolo="Saldatore Zanzibar", data_richiesta=oggi)
        cls.cand = Candidato.objects.create(cognome="Zanzibar", nome="Luca", posizione=cls.pos)
        cls.modello = ReportModello.objects.create(nome="Report Zanzibar", titolo_documento="Zanzibar")

    def _get(self, **params):
        return self.client.get(reverse("anagrafica:ricerca"), params)

    def test_ambito_persone_trova_il_dipendente_e_apre_la_scheda(self):
        self.client.force_login(self.admin)
        r = self._get(q="zanzi", ambito="persone")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ZANZIBAR MARIO")
        self.assertContains(r, reverse("anagrafica:dipendente_detail", args=[self.lid]))
        self.assertNotContains(r, "Saldatore Zanzibar")  # la posizione è di Ingressi

    def test_tutto_il_modulo_raggruppa_per_sezione(self):
        self.client.force_login(self.admin)
        r = self._get(q="zanzibar", ambito="tutto")
        for titolo in ("Dipendenti", "Posizioni aperte", "Candidati", "Tipi di qualifica", "Tipi di visita", "Modelli di report"):
            self.assertContains(r, titolo)
        self.assertContains(r, reverse("anagrafica:recruiting_detail", args=[self.cand.pk]))
        self.assertContains(r, reverse("anagrafica:reportistica_genera", args=[self.modello.pk]))

    def test_visite_mostrano_scadenza_mai_esito(self):
        self.client.force_login(self.admin)
        r = self._get(q="zanzibar", ambito="visite")
        self.assertContains(r, "Periodica Zanzibar (scade")
        self.assertNotContains(r, "limitazioni")

    def test_senza_permesso_visite_nessun_gruppo_sanitario(self):
        from django.test import RequestFactory

        from .services import ricerca_sezioni

        request = RequestFactory().get("/anagrafica/ricerca/")
        request.user = self.utente
        for ambito in ("tutto", "visite"):
            chiavi = {g.chiave for g in ricerca_sezioni.cerca(request, "zanzibar", ambito)}
            self.assertFalse(chiavi & {"tipi_visita", "persone_visite"}, ambito)
        request.user = self.admin
        chiavi = {g.chiave for g in ricerca_sezioni.cerca(request, "zanzibar", "visite")}
        self.assertEqual(chiavi, {"tipi_visita", "persone_visite"})

    def test_tendina_htmx_e_testo_troppo_corto(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("anagrafica:ricerca"), {"q": "zanzibar", "ambito": "qualifiche", "suggest": "1"},
                            HTTP_HX_REQUEST="true")
        self.assertContains(r, "fmd-suggest")
        self.assertContains(r, "Patentino Zanzibar")
        self.assertNotContains(r, "<html")
        r = self._get(q="z", ambito="tutto")
        self.assertContains(r, "Scrivi almeno due caratteri")

    def test_casella_su_dashboard_e_su_ogni_sezione(self):
        self.client.force_login(self.admin)
        pagine = {
            "anagrafica:index": "tutto", "anagrafica:dipendenti_list": "persone",
            "anagrafica:recruiting_dashboard": "ingressi", "anagrafica:qualifiche_dashboard": "qualifiche",
            "anagrafica:visite_mediche_dashboard": "visite", "anagrafica:retribuzioni_globale": "amministrazione",
            "anagrafica:reportistica_index": "report",
        }
        for rotta, ambito in pagine.items():
            r = self.client.get(reverse(rotta))
            self.assertEqual(r.status_code, 200, rotta)
            self.assertContains(r, f'name="ambito" value="{ambito}"', msg_prefix=rotta)
        # Formazione e Sicurezza hanno già la loro ricerca dedicata.
        self.assertContains(self.client.get(reverse("anagrafica:formazione_dashboard")), reverse("anagrafica:formazione_ricerca"))
        self.assertContains(self.client.get(reverse("anagrafica:sicurezza_hub")), reverse("anagrafica:sicurezza_ricerca"))
