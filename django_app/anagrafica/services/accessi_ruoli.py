"""Accessi al portale dati dal ruolo in azienda: una mappa sola, decisa con la Qualità.

Il ruolo del portale non si assegna più alla persona: è il «profilo di accesso» del
suo ruolo d'organigramma (``RuoloOperativo.profili_permessi``). Qui la mappa
ruolo in azienda → profili, applicata dal comando ``allinea_accessi_ruoli``:

- i ruoli elencati ricevono esattamente quei profili (vuoto = solo il ruolo base);
- i ruoli disattivati perdono ogni collegamento;
- i ruoli non elencati restano come sono e il rapporto li segnala.

Ogni cambio passa dai segnali di ``core.permessi.variazioni``: per ogni persona
resta scritto cosa riceve e cosa perde.
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction

# Nome del ruolo in azienda (senza badare a maiuscole) → codici dei ruoli del portale.
MAPPA: dict[str, tuple[str, ...]] = {
    # Produzione
    "caporeparto": ("ruolo-responsabile",),
    "operatore controllo qualità": ("ruolo-controllo-qualita",),
    "fai officer": ("ruolo-controllo-qualita",),
    "fai manager": ("ruolo-controllo-qualita",),
    "operatore macchina utensile": (),
    "operatore manuale": (),
    "operatore logistica": (),
    "operatore presetting": (),
    "operatore prova pressione": (),
    "operatore generico": (),
    # Direzione e staff
    "chief executive officer": ("ruolo-direzione",),
    "operations manager": ("ruolo-direzione",),
    "datore di lavoro": ("ruolo-direzione",),
    "management representative": ("ruolo-qualita",),
    "management system manager": ("ruolo-qualita",),
    "management system officer": ("ruolo-qualita",),
    "management system assistant": ("ruolo-qualita",),
    "documentation management": ("ruolo-qualita",),
    "accounting manager": ("ruolo-amministrazione",),
    "accounting officer": ("ruolo-amministrazione",),
    "human resource manager": ("ruolo-hr",),
    "human resource officer": ("ruolo-hr",),
    "information technology manager": ("ruolo-tecnico-it",),
    "information technology assistant": ("ruolo-tecnico-it",),
    "manutentore": ("ruolo-tecnico-manutenzione",),
    # Ingegneria
    "engineering manager": ("ruolo-ufficio-tecnico",),
    "project engineer": ("ruolo-ufficio-tecnico",),
    "project engineering manager": ("ruolo-ufficio-tecnico",),
    "cam specialist": ("ruolo-ufficio-tecnico",),
    "cam programming manager": ("ruolo-ufficio-tecnico",),
    "tooling specialist": ("ruolo-ufficio-tecnico",),
    # HSE: sicurezza, qualità e manutenzione (asset), niente IT
    "environmental & safety manager": ("ruolo-sicurezza", "ruolo-qualita", "ruolo-tecnico-manutenzione"),
    "environmental & safety officer": ("ruolo-sicurezza", "ruolo-qualita", "ruolo-tecnico-manutenzione"),
    "aspp": ("ruolo-sicurezza",),
    "rspp": ("ruolo-sicurezza",),
    # Solo ruolo base (deciso 23/10/2026)
    "logistics officer": (),
    "logistics manager": (),
    "procurement supplier officer": (),
    "procurement material officer": (),
    "back officer": (),
    "cost out specialist": (),
    "sales account manager": (),
    "sales account officer": (),
    # Incarichi (si sommano alla posizione)
    "preposto": ("ruolo-preposto",),
    "squadra antincendio": ("ruolo-addetto-emergenze",),
    "squadra primo soccorso": ("ruolo-addetto-emergenze",),
    "ciso": ("ruolo-referente-27001",),
    "privacy manager": ("ruolo-referente-27001",),
    "security specialist": ("ruolo-referente-27001",),
}


def _chiave(nome: str) -> str:
    return " ".join((nome or "").split()).casefold()


def allinea(*, applica: bool = False) -> dict:
    """Calcola i cambi (sola lettura) e con ``applica=True`` li salva."""
    from anagrafica.models import RuoloOperativo
    from core.models import AccessGroup
    from core.permessi.organigramma import _profili_per_ruolo
    from core.permessi.team import _assegnazioni_attive

    gruppi = {g.code: g for g in AccessGroup.objects.filter(is_active=True, amministratore=False)}
    etichette = {g.pk: g.label for g in AccessGroup.objects.all()}
    assegnazioni = list(_assegnazioni_attive().values_list("legacy_anagrafica_id", "ruolo_id"))
    persone_per_ruolo = Counter(r for _a, r in set(assegnazioni))
    righe, mancanti, non_mappati, nuovi = [], set(), [], {}
    for r in RuoloOperativo.objects.prefetch_related("profili_permessi").order_by("-is_active", "nome"):
        attuali = {g.code for g in r.profili_permessi.all()}
        if not r.is_active:
            voluti = set()
        elif _chiave(r.nome) in MAPPA:
            voluti = set(MAPPA[_chiave(r.nome)])
        else:
            if attuali or persone_per_ruolo.get(r.pk):
                non_mappati.append((r, sorted(attuali)))
            continue
        mancanti |= {c for c in voluti if c not in gruppi}
        voluti = {c for c in voluti if c in gruppi}
        if voluti != attuali:
            nuovi[r.pk] = voluti
            righe.append({"ruolo": r, "prima": sorted(attuali), "dopo": sorted(voluti),
                          "persone": persone_per_ruolo.get(r.pk, 0)})
    # Simulazione per persona: stessi filtri del motore (ruolo attivo, assegnazione in corso, niente amministratore).
    prima_map = _profili_per_ruolo({r for _a, r in assegnazioni})
    dopo_map = dict(prima_map)
    for ruolo_id, codici in nuovi.items():
        dopo_map[ruolo_id] = {gruppi[c].pk for c in codici}
    prima, dopo = {}, {}
    for aid, ruolo_id in assegnazioni:
        prima.setdefault(aid, set()).update(prima_map.get(ruolo_id, set()))
        dopo.setdefault(aid, set()).update(dopo_map.get(ruolo_id, set()))
    ricevuti, tolti = Counter(), Counter()
    for aid in prima:
        for g in dopo[aid] - prima[aid]:
            ricevuti[etichette.get(g, g)] += 1
        for g in prima[aid] - dopo[aid]:
            tolti[etichette.get(g, g)] += 1
    if applica and nuovi:
        with transaction.atomic():
            for r in RuoloOperativo.objects.filter(pk__in=list(nuovi)):
                r.profili_permessi.set([gruppi[c] for c in nuovi[r.pk]])
        from core.permessi.cache import invalida_permessi

        invalida_permessi()
    return {"righe": righe, "non_mappati": non_mappati, "mancanti": sorted(mancanti),
            "ricevuti": ricevuti, "tolti": tolti, "applicato": applica}
