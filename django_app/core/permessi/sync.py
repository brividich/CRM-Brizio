"""Dalla matrice dei ruoli ai permessi di pagina (``GroupPermissionGrant``).

La matrice dice «il ruolo X puo' vedere/creare/... sul modulo Y». Le pagine
pero' sono protette dal middleware ACL v2 con un permesso per rotta. Questo
modulo traduce la prima nei secondi, cosi' esiste una sola cosa da gestire.

Classificazione dei permessi di pagina: si leggono le rotte che il permesso
governa davvero (``core.acl_capability``) e il nome della risorsa. Molti code
generati in automatico finiscono in ``.view`` anche quando la pagina approva o
cancella (``dpi.approva.view``, ``diario_preposto.elimina.view``): fidarsi del
suffisso farebbe concedere un'approvazione a chi deve solo vedere. Fra piu'
segnali vince il piu' alto; un permesso illeggibile lo accende solo «gestire».

Le righe scritte qui portano la nota ``NOTA_MATRICE``: sono le sole che la
sincronizzazione crea e cancella. I grant di gruppo messi a mano (pagina
Accessi) non vengono toccati. Non si scrive mai ``enabled=False``: un ruolo che
non concede tace, e decide il ruolo successivo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction

from core.permessi.registro import AZIONE_CAPACITA, moduli_registrati
from core.permission_taxonomy import (
    CAPABILITY_IGNOTO,
    CAPABILITY_LETTURA,
    capability_for_name,
    strongest_capability,
)

logger = logging.getLogger(__name__)

NOTA_MATRICE = "matrice ruoli"


def _capacita_da_code(code: str, dal_nome: str) -> list[str]:
    parti = code.split(".")
    segnali = []
    if len(parti) == 3 and parti[0] != "legacy" and parti[2] == "view":
        # code generato dalla rotta: «<app>.<nome_rotta>.view» -> conta il nome rotta.
        segnali.append(capability_for_name(parti[1]))
    else:
        segnali.append(dal_nome)
    return segnali


def capacita_permessi() -> dict[str, str]:
    """code -> capacita' effettiva (lettura/modifica/approvazione/amministrazione/ignoto)."""
    from core.acl_capability import capability_index
    from core.models import PermissionDefinition

    indice = capability_index(use_cache=False)
    forzate = {
        code: capacita for spec in moduli_registrati().values() for code, capacita in spec.capacita_forzate
    }
    risultato: dict[str, str] = {}
    for code, modulo in PermissionDefinition.objects.filter(is_active=True).values_list("code", "module"):
        if code in forzate:
            risultato[code] = forzate[code]
            continue
        dal_nome = indice.by_name.get(code) or indice.get(code)
        segnali = _capacita_da_code(code, dal_nome)
        segnali.extend(capability_for_name(rotta) for rotta in indice.governed_routes.get(code, []))
        segnali.extend(cap for _rotta, cap in indice.subtree_routes.get(code, []))
        noti = [s for s in segnali if s and s != CAPABILITY_IGNOTO]
        risultato[code] = strongest_capability(noti) if noti else CAPABILITY_IGNOTO
    return risultato


def codici_per_modulo() -> dict[str, list[str]]:
    """chiave modulo -> code di pagina che gli appartengono.

    Un code dichiarato esplicitamente (``codici_acl``) appartiene a quel
    modulo anche se il suo ``PermissionDefinition.module`` dice altro.
    """
    from core.models import PermissionDefinition

    specs = moduli_registrati()
    espliciti: dict[str, str] = {}
    per_modulo_acl: dict[str, str] = {}
    for spec in specs.values():
        for code in spec.codici_acl:
            espliciti[code] = spec.chiave
        for nome in spec.moduli_acl:
            per_modulo_acl[nome] = spec.chiave

    risultato: dict[str, list[str]] = {chiave: [] for chiave in specs}
    for code, modulo in PermissionDefinition.objects.filter(is_active=True).values_list("code", "module"):
        chiave = espliciti.get(code) or per_modulo_acl.get(modulo)
        if chiave:
            risultato[chiave].append(code)
    for codes in risultato.values():
        codes.sort()
    return risultato


def pagine_azioni_proprie() -> dict[str, dict[str, str]]:
    """chiave modulo -> {code: azione propria che, sola, lo accende}.

    Sono le pagine dichiarate con ``pagine_azioni`` nel registro: le azioni
    standard non le toccano, ne' le accende «vede tutto».
    """
    return {
        spec.chiave: {code: azione for azione, codes in spec.pagine_azioni for code in codes}
        for spec in moduli_registrati().values()
        if spec.pagine_azioni
    }


@dataclass
class EsitoSync:
    ruolo: str
    accesi: int = 0
    spenti: int = 0
    invariati: int = 0
    governati: int = 0
    dettaglio: list[str] = field(default_factory=list)


def codici_desiderati(ruolo, *, capacita=None, per_modulo=None) -> tuple[set[str], set[str]]:
    """(code da accendere, code governati dalla matrice) per un ruolo."""
    from core.models import RuoloPermessoModulo

    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    specs = moduli_registrati()

    riservate = pagine_azioni_proprie()

    governati = {code for codes in per_modulo.values() for code in codes}
    desiderati: set[str] = set()
    for cella in RuoloPermessoModulo.objects.filter(ruolo=ruolo, consentito=True):
        proprie = riservate.get(cella.modulo, {})
        capacita_azione = AZIONE_CAPACITA.get(cella.azione)
        if not capacita_azione:
            # Azioni proprie del modulo: accendono solo le pagine dichiarate nel
            # registro, il resto si controlla dentro le view.
            desiderati.update(
                code for code in per_modulo.get(cella.modulo, []) if proprie.get(code) == cella.azione
            )
            continue
        for code in per_modulo.get(cella.modulo, []):
            if code not in proprie and capacita.get(code, CAPABILITY_IGNOTO) in capacita_azione:
                desiderati.add(code)

    if ruolo.vede_tutto:
        # «Vede tutto» = le azioni di AZIONI_LETTURA su ogni modulo: tutte
        # accendono i soli permessi di lettura.
        for chiave, codes in per_modulo.items():
            spec = specs.get(chiave)
            if spec is None or spec.solo_amministratore:
                continue
            proprie = riservate.get(chiave, {})
            desiderati.update(c for c in codes if c not in proprie and capacita.get(c) == CAPABILITY_LETTURA)
    return desiderati, governati


STATO_PIENO = "pieno"
STATO_PARZIALE = "parziale"
STATO_VUOTO = "vuoto"


@dataclass
class StatoPagine:
    """Cosa i permessi di pagina del ruolo concedono davvero per una cella."""

    totale: int = 0
    concesse: list[str] = field(default_factory=list)
    chiuse: list[str] = field(default_factory=list)  # senza grant o con diniego
    negate: list[str] = field(default_factory=list)
    a_mano: list[str] = field(default_factory=list)  # concesse fuori dalla matrice
    tolte_a_mano: list[str] = field(default_factory=list)  # la matrice le vuole, il grant manca

    @property
    def stato(self) -> str:
        if not self.concesse:
            return STATO_VUOTO
        return STATO_PIENO if len(self.concesse) == self.totale else STATO_PARZIALE

    @property
    def eccezione(self) -> bool:
        return bool(self.a_mano or self.tolte_a_mano)

    @property
    def dettaglio(self) -> str:
        """Testo per il tooltip della cella: quali pagine e perche'."""
        righe = [f"Pagine concesse: {len(self.concesse)} su {self.totale}"]
        aperte = [c for c in self.concesse if c not in self.a_mano]
        chiuse = [c for c in self.chiuse if c not in self.tolte_a_mano]
        for titolo, codes in (
            ("concesse dalla matrice", aperte),
            ("concesse a mano (Accessi)", self.a_mano),
            ("tolte a mano (Accessi), la matrice le vorrebbe", self.tolte_a_mano),
            ("non concesse", chiuse),
        ):
            if codes:
                righe.append(f"{titolo}:")
                righe.extend(f"  {c}" for c in codes)
        return "\n".join(righe)


def stato_pagine_ruolo(ruolo, *, capacita=None, per_modulo=None) -> dict[tuple[str, str], StatoPagine]:
    """(modulo, azione) -> stato reale dei permessi di pagina del ruolo.

    E' il verso inverso della sincronizzazione, in sola lettura: la matrice
    mostra cosa i grant di gruppo concedono davvero, compresi quelli messi o
    tolti a mano dalla pagina Accessi. Le azioni proprie dei moduli compaiono
    solo se il registro dichiara loro delle pagine. Le celle senza pagine non
    compaiono.
    """
    from core.models import GroupPermissionGrant

    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    desiderati, _governati = codici_desiderati(ruolo, capacita=capacita, per_modulo=per_modulo)
    grant = {
        g.permission_id: g
        for g in GroupPermissionGrant.objects.filter(group=ruolo)
    }
    riservate = pagine_azioni_proprie()
    risultato: dict[tuple[str, str], StatoPagine] = {}
    for chiave, codes in per_modulo.items():
        proprie = riservate.get(chiave, {})
        pagine_per_azione = [
            (azione, [c for c in codes if c not in proprie and capacita.get(c, CAPABILITY_IGNOTO) in caps])
            for azione, caps in AZIONE_CAPACITA.items()
        ]
        pagine_per_azione += [
            (azione, [c for c in codes if proprie.get(c) == azione])
            for azione in sorted(set(proprie.values()))
        ]
        for azione, pagine in pagine_per_azione:
            if not pagine:
                continue
            stato = StatoPagine(totale=len(pagine))
            for code in pagine:
                g = grant.get(code)
                if g is not None and g.enabled:
                    stato.concesse.append(code)
                    if code not in desiderati:
                        stato.a_mano.append(code)
                else:
                    stato.chiuse.append(code)
                    if g is not None:
                        stato.negate.append(code)
                    if code in desiderati:
                        stato.tolte_a_mano.append(code)
            risultato[(chiave, azione)] = stato
    return risultato


def dati_anteprima_ruolo(ruolo, *, capacita=None, per_modulo=None) -> dict:
    """Quanto serve alla pagina per prevedere i badge prima del salvataggio.

    Per ogni modulo, le sue pagine con capacita' e grant non governati dalla
    matrice (acceso a mano / diniego), che la sincronizzazione non tocca. Il
    calcolo lato pagina ripete ``codici_desiderati`` + ``sincronizza_ruolo``:
    una pagina sara' concessa se e' accesa a mano, oppure se non e' negata e
    una cella della riga (o «vede tutto» per la lettura) la vuole.
    """
    from core.models import GroupPermissionGrant

    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    specs = moduli_registrati()
    riservate = pagine_azioni_proprie()
    grant = {g.permission_id: g for g in GroupPermissionGrant.objects.filter(group=ruolo)}
    azioni = {azione: sorted(caps) for azione, caps in AZIONE_CAPACITA.items()}
    moduli = {}
    for chiave, codes in per_modulo.items():
        proprie = riservate.get(chiave, {})
        righe = []
        for code in codes:
            g = grant.get(code)
            a_mano = g is not None and g.enabled and g.note != NOTA_MATRICE
            # Un grant della matrice spento lo riaccende la sincronizzazione: non e' un diniego.
            negata = g is not None and not g.enabled and g.note != NOTA_MATRICE
            if code in proprie:
                # Pagina di un'azione propria: per la pagina la «capacita'» e' l'azione stessa.
                cap = f"azione:{proprie[code]}"
                azioni.setdefault(proprie[code], [cap])
            else:
                cap = capacita.get(code, CAPABILITY_IGNOTO)
            righe.append([code, cap, int(a_mano), int(negata)])
        spec = specs.get(chiave)
        moduli[chiave] = {"solo_admin": bool(spec and spec.solo_amministratore), "pagine": righe}
    return {
        "azioni": azioni,
        "lettura": CAPABILITY_LETTURA,
        "vede_tutto": bool(ruolo.vede_tutto),
        "moduli": moduli,
    }


def sincronizza_ruolo(ruolo, *, capacita=None, per_modulo=None, dry_run: bool = False) -> EsitoSync:
    from core.models import GroupPermissionGrant

    esito = EsitoSync(ruolo=ruolo.label)
    desiderati, governati = codici_desiderati(ruolo, capacita=capacita, per_modulo=per_modulo)
    esito.governati = len(governati)
    esistenti = {
        g.permission_id: g
        for g in GroupPermissionGrant.objects.filter(group=ruolo, permission_id__in=governati | desiderati)
    }
    with transaction.atomic():
        for code in sorted(desiderati):
            grant = esistenti.get(code)
            if grant is None:
                esito.accesi += 1
                esito.dettaglio.append(f"+ {code}")
                if not dry_run:
                    GroupPermissionGrant.objects.create(
                        group=ruolo, permission_id=code, enabled=True, note=NOTA_MATRICE
                    )
            elif grant.note == NOTA_MATRICE and not grant.enabled:
                esito.accesi += 1
                if not dry_run:
                    grant.enabled = True
                    grant.save(update_fields=["enabled", "updated_at"])
            else:
                esito.invariati += 1
        for code in sorted(governati - desiderati):
            grant = esistenti.get(code)
            if grant is not None and grant.note == NOTA_MATRICE:
                esito.spenti += 1
                esito.dettaglio.append(f"- {code}")
                if not dry_run:
                    grant.delete()
    return esito


def sincronizza_tutti(*, dry_run: bool = False) -> list[EsitoSync]:
    from core.models import AccessGroup

    capacita = capacita_permessi()
    per_modulo = codici_per_modulo()
    esiti = [
        sincronizza_ruolo(ruolo, capacita=capacita, per_modulo=per_modulo, dry_run=dry_run)
        for ruolo in AccessGroup.objects.all().order_by("-priority", "id")
    ]
    if not dry_run:
        from core.permessi.cache import invalida_permessi

        invalida_permessi()
    return esiti
