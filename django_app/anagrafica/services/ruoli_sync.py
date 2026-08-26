"""Ruoli di una persona: assegnazioni multiple, un ruolo principale.

Il ruolo di un dipendente vive in due posti che raccontano cose diverse:

- ``DipendenteRuoloOperativo`` — le **assegnazioni**, N per persona. Una persona
  può essere insieme Capocommessa e Preposto: il multiruolo è la norma, non
  l'eccezione, e non va schiacciato.
- ``DipendenteAnagraficaAziendale.ruolo_aziendale`` — un **campo testuale
  singolo**, quello che gli spostamenti organizzativi, i report e gli export
  chiamano «Ruolo aziendale». Non può contenerne più d'uno.

Finché nessuno li teneva allineati si vedeva un ruolo «assegnato» nel catalogo
e un «Ruolo aziendale: —» nella scheda della stessa persona. Qui il campo
testuale diventa il **ruolo principale**: uno dei ruoli assegnati, quello che
rappresenta la persona nell'organizzazione. Le regole, in una riga ciascuna:

- assegnare un ruolo a chi non ha ancora un principale lo rende principale;
- assegnare un ruolo a chi ne ha già uno **non** tocca il principale;
- scegliere un ruolo aziendale (spostamento/scheda) crea l'assegnazione se
  manca e lo rende principale;
- rimuovere l'assegnazione del principale promuove il primo ruolo rimasto, o
  svuota il campo se non ne restano.

A queste regole se ne sovrappone una quinta, che le limita tutte:
**solo i ruoli dell'ambito della scheda toccano il ruolo principale**. Un ruolo
dell'organigramma 45001 o 27001 (``RuoloOperativo.ambito`` con
``alimenta_scheda=False``) si assegna e basta: non diventa principale, non
promuove nessuno quando viene tolto, non compare nel campo testuale. È il senso
stesso degli ambiti — i ruoli si sovrappongono, non si sostituiscono. I ruoli
senza ambito valgono come ruoli della scheda: prima della classificazione lo
erano tutti.

Nessuna funzione qui dentro elimina assegnazioni che non le siano state
chieste: il multiruolo si perde in un attimo e si ricostruisce a mano.
"""
from __future__ import annotations

from ..models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    RuoloOperativo,
)


def _ruolo_per_nome(nome: str) -> RuoloOperativo | None:
    """Ruolo del catalogo che corrisponde al nome, senza distinzione di caso."""
    nome = (nome or "").strip()
    if not nome:
        return None
    return RuoloOperativo.objects.select_related("ambito").filter(nome__iexact=nome).first()


def alimenta_principale(ruolo: RuoloOperativo) -> bool:
    """Il ruolo appartiene all'ambito che alimenta il «Ruolo aziendale».

    Vero anche per i ruoli senza ambito: sono quelli nati prima della
    classificazione, e il loro comportamento non deve cambiare.
    """
    return bool(ruolo) and ruolo.alimenta_ruolo_principale


def ruoli_che_alimentano(legacy_id: int):
    """Assegnazioni della persona nell'ambito della scheda, per nome ruolo."""
    return [
        a
        for a in (
            DipendenteRuoloOperativo.objects
            .filter(legacy_anagrafica_id=legacy_id)
            .select_related("ruolo", "ruolo__ambito")
            .order_by("ruolo__nome")
        )
        if a.ruolo.alimenta_ruolo_principale
    ]


def ruolo_principale(legacy_id: int) -> str:
    az = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    return (az.ruolo_aziendale or "").strip() if az else ""


def _scrivi_principale(legacy_id: int, nome: str, *, user=None) -> None:
    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id, defaults={"updated_by": user},
    )
    if (az.ruolo_aziendale or "").strip() == (nome or "").strip():
        return
    az.ruolo_aziendale = (nome or "")[:200]
    if user is not None:
        az.updated_by = user
    az.save(update_fields=["ruolo_aziendale", "updated_by", "updated_at"])


def dopo_assegnazione(legacy_id: int, ruolo: RuoloOperativo, *, user=None) -> bool:
    """Il ruolo appena assegnato diventa principale solo se non ce n'è già uno.

    E solo se è un ruolo dell'ambito della scheda: gli altri organigrammi si
    sovrappongono senza scrivere nel campo testuale.

    Ritorna True se il principale è stato scritto: chi chiama lo usa per dirlo
    all'utente, visto che è un effetto che non ha chiesto esplicitamente.
    """
    if not alimenta_principale(ruolo):
        # Ruolo di un altro organigramma (45001, 27001, …): si somma agli altri
        # e non tocca il ruolo principale della scheda.
        return False
    if ruolo_principale(legacy_id):
        return False
    _scrivi_principale(legacy_id, ruolo.nome, user=user)
    return True


def dopo_rimozione(legacy_id: int, nome_rimosso: str, *, user=None) -> str:
    """Se spariva il principale, promuove il primo ruolo rimasto (o svuota).

    «Rimasto» significa rimasto **nell'ambito della scheda**: un ruolo 45001
    non prende il posto del ruolo produttivo appena tolto.

    Ritorna il nome del nuovo principale (stringa vuota se non ne restano).
    Va chiamata **dopo** la delete dell'assegnazione.
    """
    corrente = ruolo_principale(legacy_id)
    if not corrente or corrente.casefold() != (nome_rimosso or "").strip().casefold():
        return corrente

    rimasti = ruoli_che_alimentano(legacy_id)
    nuovo = rimasti[0].ruolo.nome if rimasti else ""
    _scrivi_principale(legacy_id, nuovo, user=user)
    return nuovo


def assicura_assegnazione(legacy_id: int, nome_ruolo: str, *, user=None) -> bool:
    """Il ruolo aziendale scelto esiste anche come assegnazione.

    Serve al percorso inverso: lo spostamento organizzativo scrive un nome nel
    campo testuale, e quel ruolo deve comparire tra i ruoli della persona. Le
    altre assegnazioni **restano** (multiruolo). Ritorna True se l'assegnazione
    è stata creata ora; False se c'era già o se il nome non è in catalogo — un
    valore storico fuori catalogo resta legittimo nel campo testuale.
    """
    ruolo = _ruolo_per_nome(nome_ruolo)
    if ruolo is None:
        return False
    _, creata = DipendenteRuoloOperativo.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        ruolo=ruolo,
        defaults={"assegnato_da": user if getattr(user, "pk", None) else None},
    )
    return creata
