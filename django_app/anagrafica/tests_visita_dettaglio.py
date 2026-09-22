"""Scheda della singola visita e accesso ai dati sanitari."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import TipoVisitaMedica, VisitaMedica


class VisitaMedicaDettaglioTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="visita_detail_admin", email="detail@example.test", password="test"
        )
        self.utente = get_user_model().objects.create_user(
            username="visita_detail_user", password="test"
        )
        self.tipo = TipoVisitaMedica.objects.create(nome="Visita sintetica", durata_mesi=12)
        self.visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=81235, tipo=self.tipo, data_svolgimento=date(2020, 1, 10),
            note="Nota sintetica",
        )
        self.url = reverse("anagrafica:visita_medica_dettaglio", args=[self.visita.pk])

    def test_scheda_mostra_report_e_form_di_modifica(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visita sintetica")
        self.assertContains(response, "Nota sintetica")
        self.assertContains(response, "Stampa scheda")
        self.assertContains(response, reverse(
            "anagrafica:dipendente_visita_edit", args=[81235, self.visita.pk]
        ))
        self.assertContains(response, reverse("anagrafica:visita_medica_elimina", args=[self.visita.pk]))

    def test_utente_senza_permesso_non_legge_la_scheda(self):
        self.client.force_login(self.utente)
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(b"Nota sintetica", response.content)

    def test_modifica_ritorna_alla_scheda_anche_con_tipo_inattivo(self):
        self.tipo.is_active = False
        self.tipo.save(update_fields=["is_active"])
        self.client.force_login(self.admin)
        response = self.client.post(reverse(
            "anagrafica:dipendente_visita_edit", args=[81235, self.visita.pk]
        ), {
            "tipo": self.tipo.pk,
            "data_svolgimento": "2020-02-10",
            "esito": VisitaMedica.Esito.IDONEO,
            "prescrizioni": "",
            "medico_competente": "",
            "note": "Nota corretta",
        })
        self.assertRedirects(response, self.url)
        self.visita.refresh_from_db()
        self.assertEqual(self.visita.note, "Nota corretta")
        self.assertEqual(self.visita.data_scadenza, date(2021, 2, 10))
