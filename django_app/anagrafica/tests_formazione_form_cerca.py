"""Tasto «cerca» sulle tendine lunghe dei form «+ nuovo corso» / «+ nuova sessione».

Il pannello è progressive enhancement lato client: qui si verifica solo che il
componente sia effettivamente servito nelle due pagine e che arrivi DOPO il
quick-add (l'ordine conta: il tasto «+ nuovo» viene adottato nella stessa riga).

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser durante i test.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import TrainingPlan

User = get_user_model()

MARCATORE = "fss-tools"          # classe della riga strumenti creata dal componente
MARCATORE_QA = "qa-modal"        # markup del quick-add «+ nuovo»


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TastoCercaNeiFormTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-fcerca", "su-fcerca@test.local", "x")
        self.client.force_login(self.su)
        TrainingPlan.objects.get_or_create(codice="P-CERCA", defaults={"nome": "Piano cerca"})

    def _body(self, nome_url):
        resp = self.client.get(reverse(nome_url))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_form_nuovo_corso_include_il_tasto_cerca(self):
        body = self._body("anagrafica:formazione_corso_create")
        self.assertIn(MARCATORE, body)

    def test_form_nuova_sessione_include_il_tasto_cerca(self):
        body = self._body("anagrafica:formazione_sessione_create")
        self.assertIn(MARCATORE, body)

    def test_il_componente_viene_dopo_il_quick_add(self):
        """Se l'ordine si inverte, «+ nuovo» resta fuori dalla riga strumenti."""
        for nome_url in ("anagrafica:formazione_corso_create",
                         "anagrafica:formazione_sessione_create"):
            with self.subTest(url=nome_url):
                body = self._body(nome_url)
                self.assertLess(body.index(MARCATORE_QA), body.index(MARCATORE))

    def test_le_select_lunghe_sono_agganciate_per_nome(self):
        """I nomi campo dichiarati nel componente devono esistere nei form."""
        body = self._body("anagrafica:formazione_corso_create")
        for nome in ("piano", "categoria", "qualifica"):
            self.assertIn('name="%s"' % nome, body)
        body = self._body("anagrafica:formazione_sessione_create")
        for nome in ("corso", "docente"):
            self.assertIn('name="%s"' % nome, body)
