import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import RegistroRifiuti


@override_settings(LEGACY_AUTH_ENABLED=False)
class WizardStepByStepTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="wizardtest", password="x", is_superuser=True)
        self.client.force_login(self.user)

    def test_pages_render(self):
        for url, tipo in [
            ("/rentri/carico/", "C"),
            ("/rentri/scarico-originale/", "O"),
            ("/rentri/scarico-effettivo/", "M"),
            ("/rentri/rettifica-scarico/", "R"),
        ]:
            r = self.client.get(url)
            assert r.status_code == 200, (url, r.status_code)
            # Form unico a pagina singola: niente piu' passi «Avanti».
            self.assertContains(r, 'id="rnf-form"')
            self.assertContains(r, f'data-tipo="{tipo}"')
            self.assertContains(r, 'id="f-unita"')
            self.assertNotContains(r, "Avanti")
            self.assertNotContains(r, "{#")
            if tipo == "C":
                self.assertNotContains(r, 'id="rifop-list"')
            else:
                self.assertContains(r, 'id="rifop-list"')

    def test_api_codici(self):
        RegistroRifiuti.objects.create(tipo="C", data=datetime.date(2026, 1, 1), codice="150101", quantita=1)
        r = self.client.get("/rentri/api/codici/?q=1501")
        assert r.status_code == 200, r.content
        assert "150101" in r.json()["codici"], r.json()

    def test_candidati_chain(self):
        c = RegistroRifiuti.objects.create(tipo="C", data=datetime.date(2026, 1, 1), codice="XX", quantita=10)
        r = self.client.get("/rentri/api/candidati-rif-op/?tipo=O&codice=XX")
        candidati = r.json()["candidati"]
        assert len(candidati) == 1 and candidati[0]["id_registrazione"] == c.id_registrazione, candidati

        o = RegistroRifiuti.objects.create(tipo="O", data=datetime.date(2026, 1, 2), codice="XX", rif_op=c.id_registrazione, quantita=10)
        # Scaricato per intero: non è più tra i carichi da scaricare.
        r = self.client.get("/rentri/api/candidati-rif-op/?tipo=O&codice=XX")
        assert r.json()["candidati"] == [], r.json()

        r = self.client.get("/rentri/api/candidati-rif-op/?tipo=M&codice=XX")
        candidati = r.json()["candidati"]
        # Lo scarico effettivo si collega alla O, con il carico in vista.
        assert len(candidati) == 1 and candidati[0]["id_registrazione"] == o.id_registrazione, candidati
        assert candidati[0]["carichi"] == [c.id_registrazione], candidati

        m = RegistroRifiuti.objects.create(tipo="M", data=datetime.date(2026, 1, 3), codice="XX", rif_op=o.rif_op, quantita=5)
        r = self.client.get("/rentri/api/candidati-rif-op/?tipo=M&codice=XX")
        assert r.json()["candidati"] == [], r.json()

        r = self.client.get("/rentri/api/candidati-rif-op/?tipo=R&codice=XX")
        candidati = r.json()["candidati"]
        assert len(candidati) == 1 and candidati[0]["id_registrazione"] == m.id_registrazione, candidati

    def test_carico_multipart_allegato(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = SimpleUploadedFile("scheda.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", content_type="application/pdf")
        r = self.client.post("/rentri/carico/", {
            "tipo": "C", "data": "2026-01-01", "codice": "15 01 01", "quantita": "3", "unita": "kg",
            "rentri_si_no": "false", "allegato": pdf,
        })
        assert r.status_code == 200, r.content
        body = r.json()
        assert body["ok"], body
        reg = RegistroRifiuti.objects.get(pk=body["id"])
        assert reg.allegato.name, "allegato non salvato"

    def test_edit_mode_render_with_rif_op(self):
        c = RegistroRifiuti.objects.create(tipo="C", data=datetime.date(2026, 1, 1), codice="YY", quantita=10)
        o = RegistroRifiuti.objects.create(tipo="O", data=datetime.date(2026, 1, 2), codice="YY", rif_op=c.id_registrazione, quantita=5)
        r = self.client.get(f"/rentri/{o.pk}/modifica/")
        assert r.status_code == 200, r.content
        self.assertContains(r, 'data-tipo="O"')
        self.assertContains(r, c.id_registrazione)
        self.assertContains(r, "Aggiorna registrazione")
