"""Copilota NC che impara dallo storico (NC simili e loro esito) e dalle decisioni salvate. AI mockata."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from ai_assistant.models import AiProposta
from anomalie import ai_nc
from anomalie import qualita_service as qs
from anomalie.quality_models import AnomaliaNC as NC
from anomalie.quality_models import AnomaliaNCAzione
from anomalie.tests_qualita import QualitaBase
from core.models import UserOnboarding

CHAT = "ai_assistant.services.chat_with_ollama"
User = get_user_model()


def _risposta(**data):
    return SimpleNamespace(content=json.dumps(data))


class NcSimiliTests(QualitaBase):
    def _nc_chiusa(self, op, desc, causa, azione, esito):
        scheda = qs.sync_da_anomalia(self.add(op, desc=desc))
        qs.applica_modifiche(scheda, {"tipo_difetto": self.fuori_tol.pk})
        nc = scheda.nc
        nc.causa_radice = causa
        nc.verifica_esito = esito
        nc.stato = NC.Stato.CHIUSA
        nc.save()
        AnomaliaNCAzione.objects.create(nc=nc, descrizione=azione, stato=AnomaliaNCAzione.Stato.FATTA)
        return nc

    def test_simili_con_esito_reale_e_contesto(self):
        buona = self._nc_chiusa("OP/B", "quota fuori tolleranza sul foro passante", "utensile usurato",
                                "Cambio utensile ogni 200 pezzi", NC.Esito.EFFICACE)
        cattiva = self._nc_chiusa("OP/C", "foro fuori tolleranza dopo cambio turno", "taratura sbagliata",
                                  "Richiamo verbale all'operatore", NC.Esito.NON_EFFICACE)
        nc = qs.sync_da_anomalia(self.add("OP/A", desc="quota fuori tolleranza sul foro")).nc
        simili = ai_nc.nc_simili(nc)
        per_protocollo = {c["protocollo"]: c for c in simili}
        self.assertTrue(per_protocollo[buona.protocollo]["efficace"])
        self.assertIn("stesso P/N", per_protocollo[buona.protocollo]["motivi"])  # OP/A e OP/B hanno lo stesso P/N
        self.assertTrue(per_protocollo[cattiva.protocollo]["non_efficace"])
        contesto = ai_nc.contesto_nc(nc, simili)
        self.assertIn("azioni EFFICACI alla verifica", contesto)
        self.assertIn("azioni NON EFFICACI alla verifica", contesto)
        self.assertIn("Cambio utensile ogni 200 pezzi", contesto)
        self.assertNotIn("Luca Bianchi", contesto)  # niente nomi di capocommessa/CAR
        riuso = ai_nc.azioni_da_riusare(simili)
        self.assertEqual([(a["descrizione"], a["protocollo"]) for a in riuso], [("Cambio utensile ogni 200 pezzi", buona.protocollo)])
        self.assertIn("DA RIUSARE", contesto)
        self.assertIn("DA NON RIPROPORRE", contesto)
        self.assertIn("Richiamo verbale all'operatore", contesto.split("DA NON RIPROPORRE")[1])

    def test_proposta_validata_e_registrata(self):
        buona = self._nc_chiusa("OP/B", "quota fuori tolleranza sul foro passante", "utensile usurato",
                                "Cambio utensile ogni 200 pezzi", NC.Esito.EFFICACE)
        nc = qs.sync_da_anomalia(self.add("OP/A", desc="quota fuori tolleranza sul foro")).nc
        risposta = _risposta(perche=["quota fuori", "utensile consumato", "nessun cambio programmato", "manca il limite", "piano assente", "extra"],
                             causa_radice="Utensile usurato per mancanza di un cambio programmato",
                             azioni=[{"descrizione": "Cambio utensile ogni 200 pezzi", "tipo": "correttiva", "da_storico": buona.protocollo},
                                     {"descrizione": "Inventata", "tipo": "BOH", "da_storico": "NC-9999-0001"}, {"tipo": "x"}],
                             motivazione="come nella NC simile")
        with patch(CHAT, return_value=risposta):
            p = ai_nc.proponi_analisi_nc(nc)
        self.assertEqual(len(p["perche"]), 5)
        self.assertEqual(p["azioni"][0], {"descrizione": "Cambio utensile ogni 200 pezzi", "tipo": "CORRETTIVA", "da_storico": buona.protocollo})
        self.assertEqual((p["azioni"][1]["tipo"], p["azioni"][1]["da_storico"]), ("CORRETTIVA", ""))
        self.assertEqual(len(p["azioni"]), 2)
        self.assertEqual(AiProposta.objects.filter(modulo="anomalie", esito=AiProposta.IN_ATTESA).count(), 2)

    def test_ai_spenta_restano_i_simili(self):
        nc = qs.sync_da_anomalia(self.add()).nc
        with patch(CHAT, side_effect=RuntimeError("Ollama non raggiungibile")):
            p = ai_nc.proponi_analisi_nc(nc)
        self.assertFalse(p["ai_disponibile"])
        self.assertEqual((p["causa_radice"], p["azioni"]), ("", []))


class NcCopilotaPaginaTests(QualitaBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="nc-ai", password="pass12345", email="a@x.it")
        self.client.force_login(self.admin)
        self.nc = qs.sync_da_anomalia(self.add()).nc
        self.url = reverse("anomalie_nc_dettaglio", args=[self.nc.pk])

    def test_pulsante_proposta_e_apprendimento_dal_salvataggio(self):
        self.assertContains(self.client.get(self.url), "Proponi analisi e azioni")
        risposta = _risposta(perche=["a", "b"], causa_radice="Utensile usurato per mancato cambio programmato",
                             azioni=[{"descrizione": "Cambio utensile ogni 200 pezzi", "tipo": "CORRETTIVA"}])
        with patch(CHAT, return_value=risposta):
            r = self.client.post(reverse("anomalie_nc_copilota", args=[self.nc.pk]))
        self.assertContains(r, "Copia nell'analisi")
        self.assertContains(r, 'data-descrizione="Cambio utensile ogni 200 pezzi"')
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.causa_radice, "")  # proporre non salva nulla

        # La persona salva una causa riformulata (= accettata) e un'azione diversa (= scartata).
        self.client.post(self.url, {"action": "analisi", "causa_radice": "utensile usurato: manca un cambio programmato"})
        self.client.post(self.url, {"action": "azione_nuova", "descrizione": "Controllo al 100% del lotto"})
        self.client.post(self.url, {"action": "verifica", "verifica_esito": "NON_EFFICACE"})
        causa = AiProposta.objects.get(azione=ai_nc.AZIONE_CAUSA)
        azioni = AiProposta.objects.get(azione=ai_nc.AZIONE_AZIONI)
        self.assertEqual(causa.esito, AiProposta.ACCETTATA)
        self.assertEqual(azioni.esito, AiProposta.SCARTATA)

    def test_solo_chi_modifica_puo_chiedere(self):
        user = User.objects.create_user(username="nc-lettore", password="pass12345")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "skipped": False})
        self.client.force_login(user)
        with patch("core.middleware.resolve_acl_access", return_value={"allowed": True}), \
                patch("anomalie.views._can_view_anomalie_for_op", return_value=True), \
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=False):
            r = self.client.post(reverse("anomalie_nc_copilota", args=[self.nc.pk]))
        self.assertEqual(r.status_code, 403)


@patch("anomalie.views._has_table", return_value=True)
class ClassificazioneImparaTests(QualitaBase):
    def test_proposta_e_decisione_della_scheda(self, _ht):
        admin = User.objects.create_superuser(username="cls-ai", password="pass12345", email="c@x.it")
        self.client.force_login(admin)
        aid = self.add()
        risposta = json.dumps({"tipo_difetto": self.graffi.nome, "gravita": "MINORE"})
        with patch("anomalie.ai_copilota._chiama_ai", return_value=risposta):
            r = self.client.post(reverse("api_anomalie_qualita_copilota"), data=json.dumps({"local_id": aid}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.client.post(reverse("api_anomalie_qualita"), data=json.dumps({"local_id": aid, "tipo_difetto": self.graffi.pk, "gravita": "MAGGIORE"}),
                         content_type="application/json")
        p = AiProposta.objects.get(azione="classificazione")
        self.assertEqual((p.esito, p.campi_corretti), (AiProposta.MODIFICATA, ["gravita"]))
