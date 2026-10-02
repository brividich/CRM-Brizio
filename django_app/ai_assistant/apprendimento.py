"""Come i copiloti AI «imparano» dalle persone, senza riaddestrare il modello.

1. Quando un copilota propone qualcosa, ``registra_proposta`` salva i valori proposti
   (etichette, codici, testi brevi) legati all'oggetto su cui si lavora.
2. Quando la persona salva davvero (approva una richiesta, compila l'analisi, classifica),
   ``registra_decisione`` confronta cio' che e' stato salvato con la proposta: accettata,
   corretta (quali campi) o scartata.
3. Alla proposta successiva ``lezioni_testo`` riassume come sono andate le proposte passate
   («la gravita' proposta MINORE e' stata corretta in MAGGIORE 4 volte») e il copilota lo
   mette nel contesto dell'AI. Le correzioni frequenti diventano la regola.

Tutto fail-safe: se il registro non e' disponibile il copilota funziona come prima.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

FINESTRA_DECISIONE_GIORNI = 60
MIN_PROPOSTE_PER_LEZIONI = 3


def _norm(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "si" if value else "no"
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(str(_norm(v)) for v in value if _norm(v) not in ("", ())))
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _parole(text: str) -> set[str]:
    return {p for p in re.findall(r"[a-zà-ù0-9]+", text) if len(p) >= 4}


def stesso_valore(proposto, deciso) -> bool:
    """Uguali; per i testi lunghi basta che dicano piu' o meno la stessa cosa (parole in comune)."""
    a, b = _norm(proposto), _norm(deciso)
    if a == b:
        return True
    if isinstance(a, tuple) and isinstance(b, tuple):
        # Elenchi (es. azioni): accettato se almeno meta' delle voci proposte compare, anche riformulata.
        if not a or not b:
            return False
        ritrovate = sum(1 for voce in a if any(stesso_valore(voce, altra) for altra in b))
        return ritrovate * 2 >= len(a)
    if isinstance(a, str) and isinstance(b, str) and (len(a) > 40 or len(b) > 40):
        pa, pb = _parole(a), _parole(b)
        return bool(pa and pb) and len(pa & pb) / len(pa | pb) >= 0.4
    return False


def _vuoto(value) -> bool:
    return _norm(value) in ("", ())


def _breve(value, limite=600):
    if isinstance(value, (list, tuple)):
        return [str(v)[:limite] for v in list(value)[:10]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:limite]


def registra_proposta(*, modulo: str, azione: str, oggetto_ref, proposta: dict, user=None):
    """Salva la proposta del copilota. Le proposte precedenti ancora in attesa sullo stesso
    oggetto diventano «superate»: conta l'ultima che la persona ha visto."""
    try:
        from .models import AiProposta

        valori = {k: _breve(v) for k, v in (proposta or {}).items() if not _vuoto(v)}
        if not valori:
            return None
        ref = str(oggetto_ref)[:80]
        AiProposta.objects.filter(modulo=modulo, azione=azione, oggetto_ref=ref, esito=AiProposta.IN_ATTESA).update(esito=AiProposta.SUPERATA)
        return AiProposta.objects.create(
            modulo=modulo, azione=azione, oggetto_ref=ref, proposta=valori,
            utente=user if getattr(user, "pk", None) else None,
        )
    except Exception:  # noqa: BLE001 - il registro non deve mai bloccare il copilota
        logger.exception("Proposta AI non registrata (%s.%s)", modulo, azione)
        return None


def registra_decisione(*, modulo: str, azione: str, oggetto_ref, decisione: dict, user=None, campi=None):
    """Confronta cio' che la persona ha salvato con l'ultima proposta in attesa sullo stesso oggetto.

    ``campi``: quali chiavi confrontare (default: quelle proposte). Senza una proposta recente
    non fa nulla: la persona ha lavorato senza AI e non c'e' niente da imparare.
    """
    try:
        from .models import AiProposta

        limite = timezone.now() - timedelta(days=FINESTRA_DECISIONE_GIORNI)
        proposta = (AiProposta.objects.filter(modulo=modulo, azione=azione, oggetto_ref=str(oggetto_ref)[:80],
                                              esito=AiProposta.IN_ATTESA, created_at__gte=limite)
                    .order_by("-created_at").first())
        if proposta is None:
            return None
        chiavi = [c for c in (campi or proposta.proposta.keys()) if c in proposta.proposta]
        if not chiavi:
            return None
        decisione = decisione or {}
        corretti = [c for c in chiavi if not stesso_valore(proposta.proposta.get(c), decisione.get(c))]
        if not corretti:
            esito = AiProposta.ACCETTATA
        elif len(corretti) == len(chiavi):
            esito = AiProposta.SCARTATA
        else:
            esito = AiProposta.MODIFICATA
        proposta.decisione = {c: _breve(decisione.get(c)) for c in chiavi}
        proposta.campi_corretti = corretti
        proposta.esito = esito
        proposta.deciso_da = user if getattr(user, "pk", None) else None
        proposta.deciso_il = timezone.now()
        proposta.save(update_fields=["decisione", "campi_corretti", "esito", "deciso_da", "deciso_il"])
        return proposta
    except Exception:  # noqa: BLE001
        logger.exception("Decisione AI non registrata (%s.%s)", modulo, azione)
        return None


def lezioni(modulo: str, azione: str, *, giorni: int = 365, limite: int = 400, etichette: dict | None = None) -> dict:
    """Come sono andate le proposte passate: quante accettate e le correzioni piu' frequenti."""
    vuoto = {"totale": 0, "accettate": 0, "corrette": 0, "scartate": 0, "percentuale_accettate": None, "correzioni": []}
    try:
        from .models import AiProposta

        righe = list(
            AiProposta.objects.filter(modulo=modulo, azione=azione, created_at__gte=timezone.now() - timedelta(days=giorni))
            .exclude(esito__in=[AiProposta.IN_ATTESA, AiProposta.SUPERATA])
            .order_by("-created_at")[:limite]
        )
    except Exception:  # noqa: BLE001
        logger.exception("Lezioni AI non disponibili (%s.%s)", modulo, azione)
        return vuoto
    if not righe:
        return vuoto
    conteggi = Counter(r.esito for r in righe)
    correzioni = Counter()
    for riga in righe:
        for campo in riga.campi_corretti or []:
            prima, dopo = riga.proposta.get(campo), riga.decisione.get(campo)
            # Solo valori corti (codici, etichette, si/no): le correzioni ai testi liberi non fanno regola.
            if all(isinstance(v, (str, bool, int)) and len(str(v)) <= 60 for v in (prima, dopo)) and not _vuoto(dopo):
                correzioni[(campo, str(prima), str(dopo))] += 1
    etichette = etichette or {}
    totale = len(righe)
    return {
        "totale": totale,
        "accettate": conteggi.get("accettata", 0),
        "corrette": conteggi.get("modificata", 0),
        "scartate": conteggi.get("scartata", 0),
        "percentuale_accettate": round(100 * conteggi.get("accettata", 0) / totale),
        "correzioni": [
            {"campo": etichette.get(campo, campo), "proposto": prima, "scelto": dopo, "volte": n}
            for (campo, prima, dopo), n in correzioni.most_common(6) if n >= 2
        ],
    }


def lezioni_testo(modulo: str, azione: str, **kwargs) -> str:
    """Le lezioni in poche righe per il prompt. Vuoto finche' ci sono troppe poche decisioni."""
    dati = lezioni(modulo, azione, **kwargs)
    if dati["totale"] < MIN_PROPOSTE_PER_LEZIONI:
        return ""
    righe = [
        f"COME SONO ANDATE LE TUE PROPOSTE PRECEDENTI ({dati['totale']}): {dati['accettate']} accettate, "
        f"{dati['corrette']} corrette, {dati['scartate']} scartate dalle persone."
    ]
    for c in dati["correzioni"]:
        righe.append(f"- {c['campo']}: proponevi «{c['proposto']}», le persone hanno scelto «{c['scelto']}» ({c['volte']} volte)")
    if dati["correzioni"]:
        righe.append("Tieni conto di queste correzioni: se il caso è simile, proponi direttamente ciò che le persone scelgono.")
    return "\n".join(righe)
