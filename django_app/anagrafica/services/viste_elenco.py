"""Scelta della vista dell'elenco dipendenti e preset (prompt 03)."""
from __future__ import annotations

from ..models_elenco import PreferenzaVistaUtente, VistaElenco
from .colonne_elenco import DEFAULT_COLONNE, REGISTRO, colonne_da_specifica

# Preset iniziali (anche per «Ripristina»): chiavi del registro nell'ordine di colonna.
PRESET = {
    "standard": ("Standard", "Vista di partenza dell'elenco.", ["reparto", "mansione", "email"]),
    "iso9001": ("ISO 9001", "Qualità: ruoli, qualifiche e formazione.",
                ["reparto", "mansione", "ruoli", "matricola", "formazione_scaduta", "formazione_in_scadenza", "timbri"]),
    "iso45001": ("ISO 45001", "Salute e sicurezza: visite e formazione obbligatoria.",
                 ["reparto", "mansione", "ruoli", "visita_scadenza", "visita_scaduta", "formazione_scaduta", "formazione_in_scadenza"]),
    "hr": ("HR", "Rapporto di lavoro e contatti aziendali.",
           ["reparto", "area_aziendale", "tipologia_contratto", "livello", "assunzione", "fine_prova", "email_aziendale", "telefono_aziendale", "account"]),
    "sicurezza": ("Sicurezza", "Vista operativa per preposti e RSPP.",
                  ["reparto", "mansione", "ruoli", "badge", "visita_scaduta", "formazione_scaduta"]),
    "altro": ("Altro", "Vista libera da personalizzare.", ["reparto", "mansione"]),
}


def specifica(chiavi: list[str]) -> list[dict]:
    return [{"chiave": k, "visibile": True, "larghezza": 0} for k in dict.fromkeys(chiavi) if k in REGISTRO]


def _ruolo_legacy_id(request) -> int | None:
    try:
        from core.legacy_utils import get_legacy_user

        legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return int(getattr(legacy, "ruolo_id", 0) or 0) or None
    except Exception:  # noqa: BLE001 - senza ruolo legacy valgono solo le viste globali
        return None


def viste_per_utente(request) -> list[VistaElenco]:
    ruolo = _ruolo_legacy_id(request)
    return [v for v in VistaElenco.objects.filter(attiva=True)
            if v.ambito == VistaElenco.AMBITO_GLOBALE or (ruolo and v.ruolo_legacy_id == ruolo)]


def vista_corrente(request, *, ricorda: bool = True) -> VistaElenco | None:
    """Vista richiesta (``?vista=codice``, ricordata per l'utente) > preferenza > predefinita per
    ruolo > predefinita globale > nessuna (colonne di default)."""
    disponibili = {v.codice: v for v in viste_per_utente(request)}
    richiesta = (request.GET.get("vista") or "").strip()
    if richiesta and richiesta in disponibili:
        vista = disponibili[richiesta]
        if ricorda and request.user.is_authenticated:
            from django.db import IntegrityError, transaction

            try:
                with transaction.atomic():
                    PreferenzaVistaUtente.objects.update_or_create(user=request.user, defaults={"vista": vista})
            except IntegrityError:  # due richieste in parallelo: basta che una delle due la salvi
                pass
        return vista
    if request.user.is_authenticated:
        pref = PreferenzaVistaUtente.objects.filter(user=request.user).select_related("vista").first()
        if pref and pref.vista and pref.vista.codice in disponibili:
            return pref.vista
    ruolo = _ruolo_legacy_id(request)
    predefinite = [v for v in disponibili.values() if v.predefinita]
    per_ruolo = [v for v in predefinite if v.ambito == VistaElenco.AMBITO_RUOLO and v.ruolo_legacy_id == ruolo]
    return (per_ruolo or predefinite or [None])[0]


def colonne_richieste(request, vista: VistaElenco | None) -> list[dict]:
    """Colonne da mostrare: ``?colonne=a,b`` (ad hoc) oppure quelle della vista, sempre filtrate
    dai permessi. Una colonna sensibile chiesta in querystring da chi non ha il permesso sparisce."""
    ad_hoc = [k.strip() for k in (request.GET.get("colonne") or "").split(",") if k.strip()]
    if ad_hoc and not (vista and vista.blocca_personalizzazione):
        return colonne_da_specifica(specifica(ad_hoc), request)
    return colonne_da_specifica(vista.colonne if vista else specifica(DEFAULT_COLONNE), request)
