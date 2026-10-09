"""Stato operativo del dipendente: può operare nella mansione, oppure no?

Due cause rendono una persona **non idonea a operare**:

1. **Visita del cambio mansione mancante** (D.Lgs. 81/2008 art. 41 c. 2
   lett. d): la decorrenza dello spostamento è arrivata e l'adempimento VISITA
   obbligatorio è ancora aperto. Cosa ne segue lo decide
   ``ConfigSicurezzaOperativa.modalita_visita_mancante``:

   - ``SOLO_AVVISO`` (default): avviso visibile, nessun blocco;
   - ``DEROGA_AMMESSA``: non idoneo a operare, salvo deroga motivata e a
     termine (``DerogaOperativaVisita``);
   - ``BLOCCO``: non idoneo a operare, le deroghe non valgono.

2. **Giudizio di non idoneità** (temporanea o definitiva) sull'ultima visita
   corrente: blocca sempre, in qualunque modalità.

Lo stato è **calcolato**, non salvato: non può restare indietro rispetto ai
dati. **Privacy:** ``etichetta`` e ``codice`` sono mostrabili a chi gestisce il
personale (preposti compresi); il *perché* (``motivi``) è un dato derivato da
quello sanitario e va mostrato solo a chi ha il permesso visite
(:meth:`StatoOperativo.motivi_visibili`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from django.utils import timezone

OK = "OK"
AVVISO = "AVVISO"
DEROGA = "DEROGA"
NON_IDONEO = "NON_IDONEO_OPERARE"

MOTIVO_VISITA_MANCANTE = "VISITA_MANCANTE"
MOTIVO_GIUDIZIO = "GIUDIZIO_NON_IDONEITA"

ESITI_NON_IDONEI = ("NON_IDONEO_TEMP", "NON_IDONEO_DEF")


@dataclass
class StatoOperativo:
    legacy_id: int
    codice: str = OK
    etichetta: str = ""
    motivi: list[str] = field(default_factory=list)
    adempimenti_ids: list[int] = field(default_factory=list)
    deroga: object | None = None

    @property
    def bloccante(self) -> bool:
        return self.codice == NON_IDONEO

    @property
    def colore(self) -> str:
        return {NON_IDONEO: "#b91c1c", AVVISO: "#b45309", DEROGA: "#b45309"}.get(self.codice, "#15803d")

    def motivi_visibili(self, can_view_visite: bool) -> list[str]:
        if not can_view_visite:
            return []
        testi = {
            MOTIVO_VISITA_MANCANTE: "Visita al cambio mansione non ancora registrata alla decorrenza",
            MOTIVO_GIUDIZIO: "Giudizio di non idoneità sull'ultima visita",
        }
        return [testi.get(m, m) for m in self.motivi]


def calcola(legacy_ids: Iterable[int] | None = None, *, giorno: date | None = None) -> dict[int, StatoOperativo]:
    """Stato operativo delle persone con qualcosa da segnalare (le altre sono OK).

    ``legacy_ids`` None = tutti. Query costanti: adempimenti aperti scaduti,
    deroghe valide, visite correnti con giudizio di non idoneità.
    """
    from ..models import AdempimentoCambioMansione as A, VisitaMedica
    from ..models_mansioni_rischio import ConfigSicurezzaOperativa, DerogaOperativaVisita
    from .visite import ultime_visite_correnti_ids

    giorno = giorno or timezone.localdate()
    ids = None if legacy_ids is None else [int(i) for i in legacy_ids]
    modalita = ConfigSicurezzaOperativa.load().modalita_visita_mancante

    mancanti = A.objects.filter(
        tipo=A.TIPO_VISITA, obbligatorio=True, stato=A.STATO_APERTO, attivo=True,
        assegnazione__isnull=False, entro_il__lte=giorno,
    )
    if ids is not None:
        mancanti = mancanti.filter(legacy_anagrafica_id__in=ids)
    per_persona: dict[int, list[int]] = {}
    for pk, lid in mancanti.values_list("pk", "legacy_anagrafica_id"):
        per_persona.setdefault(lid, []).append(pk)

    deroghe: dict[int, object] = {}
    if per_persona and modalita == ConfigSicurezzaOperativa.MODALITA_DEROGA:
        for deroga in DerogaOperativaVisita.objects.filter(
            legacy_anagrafica_id__in=list(per_persona), attivo=True, valida_fino__gte=giorno,
        ).order_by("-valida_fino"):
            deroghe.setdefault(deroga.legacy_anagrafica_id, deroga)

    correnti = ultime_visite_correnti_ids(ids) if ids is None or ids else set()
    non_idonei = set(
        VisitaMedica.objects.filter(pk__in=list(correnti), esito__in=ESITI_NON_IDONEI)
        .values_list("legacy_anagrafica_id", flat=True)
    ) if correnti else set()

    out: dict[int, StatoOperativo] = {}
    for lid in set(per_persona) | non_idonei:
        stato = StatoOperativo(legacy_id=lid, adempimenti_ids=per_persona.get(lid, []))
        if lid in per_persona:
            stato.motivi.append(MOTIVO_VISITA_MANCANTE)
        if lid in non_idonei:
            stato.motivi.append(MOTIVO_GIUDIZIO)
            stato.codice, stato.etichetta = NON_IDONEO, "Non idoneo a operare"
        elif modalita == ConfigSicurezzaOperativa.MODALITA_SOLO_AVVISO:
            stato.codice, stato.etichetta = AVVISO, "Visita del cambio mansione mancante"
        elif lid in deroghe:
            stato.deroga = deroghe[lid]
            stato.codice = DEROGA
            stato.etichetta = f"In deroga fino al {deroghe[lid].valida_fino:%d/%m/%Y}"
        else:
            stato.codice, stato.etichetta = NON_IDONEO, "Non idoneo a operare: visita mancante"
        out[lid] = stato
    return out


def stato_persona(legacy_ids: Iterable[int], *, giorno: date | None = None) -> StatoOperativo:
    """Stato di una persona (tutti i suoi id legacy): il più grave fra gli id."""
    ids = [int(i) for i in legacy_ids]
    stati = list(calcola(ids, giorno=giorno).values())
    if not stati:
        return StatoOperativo(legacy_id=ids[0] if ids else 0)
    ordine = {NON_IDONEO: 0, DEROGA: 1, AVVISO: 2, OK: 3}
    stati.sort(key=lambda s: ordine.get(s.codice, 9))
    peggiore = stati[0]
    for altro in stati[1:]:
        for motivo in altro.motivi:
            if motivo not in peggiore.motivi:
                peggiore.motivi.append(motivo)
        peggiore.adempimenti_ids.extend(altro.adempimenti_ids)
    return peggiore


def concedi_deroga(legacy_id: int, *, motivo: str, valida_fino: date, user, adempimento=None, request=None):
    """Concede una deroga motivata e a termine (solo in modalità DEROGA_AMMESSA)."""
    from django.core.exceptions import ValidationError
    from ..models_mansioni_rischio import ConfigSicurezzaOperativa, DerogaOperativaVisita
    from . import eventi_sicurezza

    config = ConfigSicurezzaOperativa.load()
    if config.modalita_visita_mancante != ConfigSicurezzaOperativa.MODALITA_DEROGA:
        raise ValidationError("Le deroghe sono ammesse solo nella modalità «salvo deroga motivata».")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Il motivo della deroga è obbligatorio.")
    oggi = timezone.localdate()
    if valida_fino < oggi:
        raise ValidationError("La deroga non può scadere nel passato.")
    if (valida_fino - oggi).days > config.deroga_max_giorni:
        raise ValidationError(f"La deroga non può superare {config.deroga_max_giorni} giorni.")
    deroga = DerogaOperativaVisita.objects.create(
        legacy_anagrafica_id=int(legacy_id), adempimento=adempimento, motivo=motivo[:500],
        autorizzato_da=user if getattr(user, "is_authenticated", False) else None, valida_fino=valida_fino,
    )
    eventi_sicurezza.registra(
        legacy_id, "DEROGA_CONCESSA", f"Deroga operativa fino al {valida_fino:%d/%m/%Y}",
        user=user, request=request, oggetto=deroga,
        payload={"deroga_id": deroga.pk, "valida_fino": valida_fino.isoformat(), "motivo": motivo[:300]},
    )
    return deroga


def revoca_deroga(deroga, *, motivo: str, user, request=None):
    from . import eventi_sicurezza

    deroga.attivo = False
    deroga.revocata_il = timezone.now()
    deroga.revocata_da = user if getattr(user, "is_authenticated", False) else None
    deroga.revoca_motivo = (motivo or "").strip()[:300]
    deroga.save(update_fields=["attivo", "revocata_il", "revocata_da", "revoca_motivo"])
    eventi_sicurezza.registra(
        deroga.legacy_anagrafica_id, "DEROGA_REVOCATA", "Deroga operativa revocata",
        user=user, request=request, oggetto=deroga,
        payload={"deroga_id": deroga.pk, "motivo": deroga.revoca_motivo},
    )
    return deroga
