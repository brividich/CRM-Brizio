"""Doppioni dell'inventario software tra WatchGuard e Defender: stesso programma, nomi diversi.

Ogni giro (lettura «software_doppioni»):

1. **Unione sicura senza AI** (``software_inventory.unisci_per_equivalenza``): stesso PC, stessa versione,
   nome equivalente («chrome» / «Google Chrome»). Si tiene la riga più vecchia, le fonti si sommano.
2. **Coppie dal nome simile** (``software_fonti_confronto.confronta``): per i PC visti da entrambe le fonti,
   i programmi che una sola fonte vede, con il nome più simile dell'altra. La somiglianza da sola sbaglia
   («OneNote for Windows 10» / «Windows 10»): conta anche se le **versioni coincidono sui PC in comune**.
   - nome uguale tolte le parole del produttore + versioni che coincidono → alias subito;
   - altrimenti decide l'AI locale (sì/no, confidenza, motivo): con confidenza ≥ soglia e versioni che
     coincidono l'alias si crea da solo, sotto soglia resta da decidere in Dispositivi › Software.

Accettare = un ``SoftwareAlias`` di prodotto (nome Defender → nome WatchGuard, che ha già CPE e decisioni)
applicato subito come da Inventario software › Alias. **Annullare** toglie l'alias: al giro successivo di
ciascuna fonte le righe tornano separate. Ogni unione e annullamento è nell'audit.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from security.models import SecurityPropostaAi, SoftwareAlias, SoftwareInstallation, SoftwareSourceKind

logger = logging.getLogger(__name__)

SOGLIA_NOME = 0.7          # sotto questa somiglianza la coppia non si propone nemmeno
COINCIDENZA_MINIMA = 0.5   # quota di PC in comune con la stessa versione per unire da soli
AZIONE_AI = "soc_doppione_software"

SISTEMA = (
    "Sei un tecnico IT. Ricevi due nomi di programma installati sugli stessi PC, letti da due inventari diversi "
    "(WatchGuard e Microsoft Defender), con produttore e versioni. Rispondi solo se sono LO STESSO programma "
    "(stesso prodotto, anche se scritto in modo diverso o con edizione/lingua/architettura nel nome). "
    "Programmi diversi dello stesso produttore NON sono lo stesso (es. «Microsoft Store» e «Microsoft Teams», "
    "«OneNote for Windows 10» e «Windows 10», un componente e il prodotto principale). "
    'Rispondi solo in JSON: {"stesso": true|false, "confidenza": 0-100, "motivazione": "una frase"}.'
)
ESEMPI = [
    ("A: «microsoft onedrive» (microsoft), versioni 25.1, 25.2\nB: «onedrive» (microsoft), versioni 25.1, 25.2\nPC in comune: 12, stessa versione su 11",
     {"stesso": True, "confidenza": 97, "motivazione": "Stesso prodotto, Defender omette il produttore nel nome; le versioni coincidono."}),
    ("A: «onenote for windows 10» (microsoft), versioni 16001.14326\nB: «windows 10» (microsoft), versioni 10.0.19045\nPC in comune: 3, stessa versione su 0",
     {"stesso": False, "confidenza": 95, "motivazione": "Uno è un'app, l'altro il sistema operativo: prodotti diversi."}),
]


def attivo():
    from security.services import soc_settings

    return bool(soc_settings.value("ai.doppioni.attivo"))


def chiave(defender, watchguard):
    return f"doppione|{defender[0]}|{defender[1]}|{watchguard[0]}|{watchguard[1]}"[:300]


def _versioni_per_pc(fonte, coppia):
    """{host: {versioni}} delle righe attive di una fonte per (vendor, prodotto)."""
    out = defaultdict(set)
    for host, version, fonti, origine in SoftwareInstallation.objects.filter(
        still_detected=True, vendor=coppia[0], product=coppia[1]
    ).values_list("host", "version_raw", "fonti", "source_kind"):
        if fonte in (fonti or [origine]):
            out[host].add((version or "").strip().lower())
    return out


def confronto_versioni(defender, watchguard):
    """(PC in comune, PC con almeno una versione uguale, versioni Defender, versioni WatchGuard)."""
    d, w = _versioni_per_pc("defender", defender), _versioni_per_pc("watchguard", watchguard)
    comuni = set(d) & set(w)
    uguali = sum(1 for h in comuni if d[h] & w[h])
    vd = sorted({v for vs in d.values() for v in vs if v})[:6]
    vw = sorted({v for vs in w.values() for v in vs if v})[:6]
    return len(comuni), uguali, vd, vw


def candidati(limit=200):
    """Coppie (defender, watchguard, somiglianza) dal confronto delle fonti, la più simile in cima."""
    from security.management.commands.software_fonti_confronto import confronta

    *_rest, proposte = confronta(SoftwareSourceKind.WATCHGUARD, SoftwareSourceKind.DEFENDER, soglia=SOGLIA_NOME)
    out, viste = [], set()
    for p in proposte:
        # (coppia_wg, n_wg, coppia_defender, n_defender, somiglianza) — vedi software_fonti_confronto
        wg, _n_wg, df, _n_df, punteggio = p
        if (df, wg) in viste or df == wg:
            continue
        viste.add((df, wg))
        out.append((tuple(df), tuple(wg), float(punteggio)))
    out.sort(key=lambda c: -c[2])
    return out[:limit]


def _alias_esistente(defender_product):
    return SoftwareAlias.objects.filter(kind=SoftwareAlias.KIND_PRODUCT, raw__iexact=defender_product).first()


def applica(proposta, *, utente=None, automatico=False, request=None):
    """Crea l'alias nome Defender → nome WatchGuard e lo applica subito (righe unite, impatti CVE spostati)."""
    from security import views_vuln

    _wg_vendor, wg_product = proposta.proposta.split("|", 1)
    with transaction.atomic():
        alias, _ = SoftwareAlias.objects.update_or_create(kind=SoftwareAlias.KIND_PRODUCT, raw=proposta.product[:160],
                                                          defaults={"canonical": wg_product[:160]})
        righe = views_vuln._apply_alias(alias)
        SecurityPropostaAi.objects.filter(pk=proposta.pk).update(
            stato=SecurityPropostaAi.ACCETTATA, decisa_il=timezone.now(), decisa_da=utente)
    _audit(request, "software_doppione_unito", proposta, {"automatico": automatico, "righe": righe})
    return righe


def annulla(proposta, *, utente=None, request=None):
    """Toglie l'alias: al prossimo giro di ciascuna fonte le righe tornano separate."""
    SoftwareAlias.objects.filter(kind=SoftwareAlias.KIND_PRODUCT, raw__iexact=proposta.product).delete()
    SecurityPropostaAi.objects.filter(pk=proposta.pk).update(stato=SecurityPropostaAi.RIFIUTATA, decisa_il=timezone.now(), decisa_da=utente)
    _audit(request, "software_doppione_annullato", proposta, {})


def rifiuta(proposta, *, utente=None, request=None):
    SecurityPropostaAi.objects.filter(pk=proposta.pk).update(stato=SecurityPropostaAi.RIFIUTATA, decisa_il=timezone.now(), decisa_da=utente)
    _audit(request, "software_doppione_rifiutato", proposta, {})


def _audit(request, azione, proposta, extra):
    from core.audit import log_action

    log_action(request, azione, "security", {"defender": f"{proposta.vendor}|{proposta.product}", "watchguard": proposta.proposta,
                                             "confidenza": proposta.confidenza, **extra},
               oggetto_tipo="security.SecurityPropostaAi", oggetto_id=str(proposta.pk))


def _chiedi_ai(defender, watchguard, comuni, uguali, vd, vw):
    from security.services import cpe_ai

    domanda = (f"A: «{watchguard[1]}» ({watchguard[0]}), versioni {', '.join(vw) or 'n.d.'}\n"
               f"B: «{defender[1]}» ({defender[0]}), versioni {', '.join(vd) or 'n.d.'}\n"
               f"PC in comune: {comuni}, stessa versione su {uguali}")
    risposta = cpe_ai._chiedi(cpe_ai._messaggi(SISTEMA, ESEMPI, domanda), action=AZIONE_AI, object_type="software", object_id=defender[1][:80])
    data = risposta.get("data") if risposta.get("ok") else None
    if not isinstance(data, dict) or "stesso" not in data:
        return None, risposta.get("error") or "risposta non valida", risposta.get("model", "")
    return {"stesso": bool(data.get("stesso")), "confidenza": cpe_ai._confidenza(data.get("confidenza")),
            "motivazione": cpe_ai._motivazione(data.get("motivazione"))}, "", risposta.get("model", "")


def giro(*, max_ai=None, usa_ai=True):
    """Un giro completo: unione sicura, poi coppie dal nome simile (subito, con l'AI o da decidere)."""
    from security.services import soc_settings, software_inventory
    from security.services.cpe_ai import _hash

    esito = {"unite_stesso_pc": 0, "alias_automatici": 0, "alias_ai": 0, "da_decidere": 0, "non_stesso": 0, "chieste_ai": 0, "errori_ai": 0}
    esito["unite_stesso_pc"] = software_inventory.unisci_per_equivalenza(applica=True)["fuse"]
    soglia = int(soc_settings.value("ai.doppioni.confidenza_auto") or 85)
    max_ai = int(max_ai if max_ai is not None else (soc_settings.value("ai.doppioni.max_per_giro") or 6))
    esistenti = {p.chiave: p for p in SecurityPropostaAi.objects.filter(tipo=SecurityPropostaAi.TIPO_DOPPIONE)}
    for defender, watchguard, punteggio in candidati():
        if _alias_esistente(defender[1]):
            continue
        k = chiave(defender, watchguard)
        comuni, uguali, vd, vw = confronto_versioni(defender, watchguard)
        contesto = _hash(defender, watchguard, comuni, uguali, vd, vw)
        prima = esistenti.get(k)
        if prima is not None and (prima.stato in (SecurityPropostaAi.ACCETTATA, SecurityPropostaAi.RIFIUTATA)
                                  or (prima.contesto_hash == contesto and prima.stato in (SecurityPropostaAi.APERTA, SecurityPropostaAi.SCARTATA))):
            continue
        coincide = comuni > 0 and uguali / comuni >= COINCIDENZA_MINIMA
        campi = {"tipo": SecurityPropostaAi.TIPO_DOPPIONE, "contesto_hash": contesto, "vendor": defender[0][:120], "product": defender[1][:160],
                 "proposta": f"{watchguard[0]}|{watchguard[1]}"[:300], "candidati": [vd, vw, comuni, uguali, round(punteggio, 2)],
                 "creata_il": timezone.now(), "decisa_il": None, "decisa_da": None}
        if punteggio >= 1.0 and coincide:
            riga, _ = SecurityPropostaAi.objects.update_or_create(chiave=k, defaults={
                **campi, "confidenza": 100, "modello": "", "stato": SecurityPropostaAi.APERTA,
                "motivazione": f"Stesso nome tolte le parole del produttore; stessa versione su {uguali} PC di {comuni}."})
            applica(riga, automatico=True)
            esito["alias_automatici"] += 1
            continue
        if not usa_ai or esito["chieste_ai"] >= max_ai:
            continue
        esito["chieste_ai"] += 1
        risposta, errore, modello = _chiedi_ai(defender, watchguard, comuni, uguali, vd, vw)
        if risposta is None:
            esito["errori_ai"] += 1
            if "non raggiungibile" in errore or "non configurati" in errore or "Timeout" in errore:
                break  # AI ferma: niente altre richieste in questo giro
            continue
        stato = SecurityPropostaAi.APERTA if risposta["stesso"] else SecurityPropostaAi.SCARTATA
        riga, _ = SecurityPropostaAi.objects.update_or_create(chiave=k, defaults={
            **campi, "confidenza": risposta["confidenza"], "motivazione": risposta["motivazione"], "modello": modello[:160], "stato": stato})
        if risposta["stesso"] and risposta["confidenza"] >= soglia and coincide:
            applica(riga, automatico=True)
            esito["alias_ai"] += 1
        elif risposta["stesso"]:
            esito["da_decidere"] += 1
        else:
            esito["non_stesso"] += 1
    if esito["alias_automatici"] or esito["alias_ai"] or esito["unite_stesso_pc"]:
        try:
            from security import views_vuln

            views_vuln._queue_recompute()  # impatti CVE sulle righe unite
        except Exception:  # noqa: BLE001
            logger.exception("Doppioni software: ricalcolo CVE non accodato")
    return esito


def giro_lettura():
    if not attivo():
        return {"attivo": False}
    return {"ok": True, **giro()}


def da_decidere():
    return list(SecurityPropostaAi.objects.filter(tipo=SecurityPropostaAi.TIPO_DOPPIONE, stato=SecurityPropostaAi.APERTA).order_by("-confidenza"))


def unite_di_recente(giorni=30):
    from datetime import timedelta

    da = timezone.now() - timedelta(days=giorni)
    return list(SecurityPropostaAi.objects.filter(tipo=SecurityPropostaAi.TIPO_DOPPIONE, stato=SecurityPropostaAi.ACCETTATA,
                                                  decisa_il__gte=da).order_by("-decisa_il")[:100])
