"""Testi personalizzabili della reception: pagina pubblica «Richiesta di visita» e mail agli esterni.

Si cambiano in Reception → Configurazione → Impostazioni; vuoto = testo predefinito. Stanno in
``SiteConfig`` con la chiave ``reception_testo_<nome>``. Nei testi delle mail i segnaposti tra graffe
(``{nome}``, ``{codice}``…) si sostituiscono con i dati veri; quelli sconosciuti restano come sono.
L'aspetto grafico delle mail (logo, colori, piè di pagina) è quello comune a tutte le mail dell'HUB.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PREFISSO = "reception_testo_"
COLORE_PREDEFINITO = "#002b5c"  # blu NOVICROM HUB, come l'intestazione delle mail
_SEGNAPOSTO = re.compile(r"\{([a-z_]+)\}")
_COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Testo:
    etichetta: str
    predefinito: str
    segnaposti: tuple[str, ...] = ()
    obbligatori: tuple[str, ...] = ()
    righe: int = 1
    massimo: int = 200


TESTI: dict[str, Testo] = {
    "pagina_titolo": Testo("Titolo", "Registra la tua visita", massimo=80),
    "pagina_intro": Testo("Testo sotto il titolo", "Ti serve un minuto. Ricevi il codice per entrare appena la visita è confermata.",
                          righe=3, massimo=400),
    "pagina_colore": Testo("Colore principale", COLORE_PREDEFINITO, massimo=7),
    "invito_oggetto": Testo("Oggetto", "Il suo accesso a Costruzioni Novicrom Srl", ("nome", "referente")),
    "invito_testo": Testo(
        "Testo",
        "Gentile {nome},\n{referente} la aspetta da Costruzioni Novicrom Srl.\n{quando}\n\n"
        "Il suo codice di accesso è: {codice}\nValido fino al {scadenza}.\n\n"
        "All'arrivo, al chiosco della reception scelga «Ho un codice» e inserisca il codice o mostri il QR qui sotto, "
        "poi ritiri il cartellino.",
        ("nome", "referente", "quando", "data", "ora", "sala", "codice", "scadenza", "azienda"), ("codice",), righe=9, massimo=3000),
    "conferma_oggetto": Testo("Oggetto", "Confermi la richiesta di visita a Costruzioni Novicrom Srl"),
    "conferma_testo": Testo(
        "Testo",
        "Gentile {nome},\nabbiamo ricevuto la sua richiesta di visita a Costruzioni Novicrom Srl per il {data}.\n\n"
        "Per inoltrarla apra questo link e confermi entro {ore} ore:\n{link}\n\n"
        "Se non ha fatto lei la richiesta, ignori questo messaggio: senza conferma viene cancellata.",
        ("nome", "data", "ore", "link"), ("link",), righe=8, massimo=3000),
    "rifiuto_oggetto": Testo("Oggetto", "La sua richiesta di visita a Costruzioni Novicrom Srl"),
    "rifiuto_testo": Testo(
        "Testo",
        "Gentile {nome},\nla sua richiesta di visita a Costruzioni Novicrom Srl per il {data} non è stata accolta.\n{nota}\n"
        "Per accordarsi su un'altra data può rispondere a questa mail o contattare direttamente la persona che voleva incontrare.",
        ("nome", "data", "nota"), righe=7, massimo=3000),
}

# Gruppi mostrati in Impostazioni: (chiave, titolo, nota, campi)
MAIL = (
    ("invito", "Mail con il codice d'invito", "All'ospite annunciato o con la richiesta accettata. Il QR con il codice compare in automatico sotto il testo; l'invito in calendario è allegato.",
     ("invito_oggetto", "invito_testo")),
    ("conferma", "Mail di conferma della richiesta", "All'esterno appena compila il modulo: senza il link non può confermare.",
     ("conferma_oggetto", "conferma_testo")),
    ("rifiuto", "Mail di richiesta non accolta", "All'esterno quando la richiesta viene rifiutata.", ("rifiuto_oggetto", "rifiuto_testo")),
)


def _chiave(nome: str) -> str:
    return PREFISSO + nome


def tutti() -> dict[str, str]:
    """Valori correnti (personalizzati o predefiniti) di tutti i testi."""
    from core.models import SiteConfig

    salvati = SiteConfig.get_many({_chiave(n): "" for n in TESTI})
    return {n: (salvati.get(_chiave(n)) or "").strip() or t.predefinito for n, t in TESTI.items()}


def personalizzati() -> set[str]:
    from core.models import SiteConfig

    salvati = SiteConfig.get_many({_chiave(n): "" for n in TESTI})
    return {n for n in TESTI if (salvati.get(_chiave(n)) or "").strip()}


def leggi(nome: str) -> str:
    from core.models import SiteConfig

    return (SiteConfig.get(_chiave(nome), "") or "").strip() or TESTI[nome].predefinito


def errore(nome: str, valore: str) -> str:
    """Messaggio d'errore se il valore non va bene, stringa vuota se va bene (vuoto = predefinito)."""
    t = TESTI[nome]
    valore = (valore or "").strip()
    if not valore:
        return ""
    if len(valore) > t.massimo:
        return f"«{t.etichetta}»: al massimo {t.massimo} caratteri."
    if nome == "pagina_colore" and not _COLORE.match(valore):
        return "Il colore va scritto come #RRGGBB."
    mancanti = [s for s in t.obbligatori if "{" + s + "}" not in valore]
    if mancanti:
        return f"«{t.etichetta}» deve contenere {', '.join('{' + s + '}' for s in mancanti)}."
    return ""


def salva(nome: str, valore: str) -> None:
    from core.models import SiteConfig

    valore = (valore or "").strip()
    if valore == TESTI[nome].predefinito:
        valore = ""
    if valore or SiteConfig.objects.filter(chiave=_chiave(nome)).exists():
        SiteConfig.set(_chiave(nome), valore, f"Reception: {TESTI[nome].etichetta}")


def componi(testo: str, valori: dict[str, str]) -> str:
    """Sostituisce i segnaposti noti; le righe rimaste vuote in fila si riducono a una."""
    pieno = _SEGNAPOSTO.sub(lambda m: str(valori[m.group(1)]) if m.group(1) in valori else m.group(0), testo)
    return re.sub(r"\n{3,}", "\n\n", pieno).strip()


def pagina() -> dict[str, str]:
    valori = tutti()
    colore = valori["pagina_colore"] if _COLORE.match(valori["pagina_colore"]) else COLORE_PREDEFINITO
    return {"titolo": valori["pagina_titolo"], "intro": valori["pagina_intro"], "colore": colore,
            "colore_personalizzato": colore.lower() != COLORE_PREDEFINITO}
