"""Audit S8: ogni pagina del SOC rifiuta chi non ha il permesso.

Su 174 rotte solo 49 hanno la protezione scritta sulla rotta (``_guard``): per le altre
il permesso e' controllato dentro la vista e dal controllo generale. Questo test apre
ogni rotta di ``security/urls_hub.py`` con un utente del portale senza permessi SOC
e pretende il rifiuto, cosi' una pagina nuova lasciata scoperta per dimenticanza
fa fallire la suite.
"""
from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.urls import URLPattern, reverse

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import Profile, UserOnboarding
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables
from security import urls_hub

# Valori finti per i parametri delle rotte: nessun oggetto esiste, quindi una pagina
# che risponde 200 lo fa senza aver controllato il permesso.
_VALORI = {"int": 999999, "slug": "x", "str": "x", "path": "x", "uuid": "00000000-0000-0000-0000-000000000000"}
_PARAM = re.compile(r"<(?:(\w+):)?(\w+)>")
# Risposte che non espongono la pagina: rifiuto, login, metodo non ammesso.
_AMMESSE = {401, 403, 405}
# Stub esplicito (501) delle API non montate: non mostra dati.
_ESCLUSE = {"api_addon_detail"}


def _rotte():
    for voce in urls_hub.urlpatterns:
        if not isinstance(voce, URLPattern) or not voce.name or voce.name in _ESCLUSE:
            continue
        kwargs = {nome: _VALORI.get(tipo or "str", "x") for tipo, nome in _PARAM.findall(str(voce.pattern))}
        yield voce.name, reverse(f"security:{voce.name}", kwargs=kwargs or None)


class RotteSocNegateTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")
        self.user = get_user_model().objects.create_user(username="operaio.soc", password="pass12345")
        legacy = UtenteLegacy.objects.create(
            nome="operaio.soc", email="operaio.soc@example.local", password="x",
            ruolo="utente", ruolo_id=6, attivo=True, deve_cambiare_password=False,
        )
        Profile.objects.create(user=self.user, legacy_user_id=legacy.id, legacy_ruolo_id=6, legacy_ruolo="utente")
        UserOnboarding.objects.create(user=self.user, completed=True)
        cache.clear()
        bump_legacy_cache_version()
        self.client.force_login(self.user)

    def _rifiutata(self, url, risposta) -> bool:
        if risposta.status_code in _AMMESSE:
            return True
        if risposta.status_code in (301, 302):
            # Redirect al login o a una pagina di rifiuto, mai alla pagina stessa.
            return risposta.get("Location", "").split("?")[0] != url
        return False

    def test_ogni_rotta_soc_rifiuta_chi_non_ha_il_permesso(self):
        scoperte = []
        rotte = list(_rotte())
        self.assertGreater(len(rotte), 100)
        for nome, url in rotte:
            risposta = self.client.get(url)
            if risposta.status_code == 405:
                risposta = self.client.post(url, {})
            if not self._rifiutata(url, risposta):
                scoperte.append(f"{nome} {url} -> {risposta.status_code}")
        self.assertEqual(scoperte, [], "Pagine SOC aperte a chi non ha il permesso:\n" + "\n".join(scoperte))

    def test_controllo_il_superuser_apre_le_pagine(self):
        # Se anche l'amministratore fosse respinto, il test sopra non proverebbe niente.
        admin = get_user_model().objects.create_superuser("admin.soc", "admin.soc@example.local", "pass12345")
        UserOnboarding.objects.create(user=admin, completed=True)
        self.client.force_login(admin)
        aperte = sum(1 for _nome, url in _rotte()
                     if "<" not in url and self.client.get(url).status_code == 200)
        self.assertGreater(aperte, 30)
