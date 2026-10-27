"""Helper per il logging di azioni rilevanti nel portale (audit trail)."""
from __future__ import annotations

import logging


from core.impersonation import display_name_for_user

logger = logging.getLogger(__name__)


def _riferimento_oggetto(oggetto, oggetto_tipo: str, oggetto_id: str) -> tuple[str, str]:
    """Normalizza il riferimento al record: da istanza, o esplicito.

    Passare l'istanza (``oggetto=ticket``) evita di scrivere a mano l'etichetta e
    di sbagliarla; i due parametri espliciti restano per le tabelle **legacy**,
    che non hanno un modello Django da cui dedurla.
    """
    if oggetto is not None:
        meta = getattr(oggetto, "_meta", None)
        etichetta = getattr(meta, "label_lower", "") if meta is not None else ""
        return (etichetta or oggetto_tipo)[:100], str(getattr(oggetto, "pk", "") or oggetto_id)[:64]
    return (oggetto_tipo or "")[:100], str(oggetto_id or "")[:64]


def log_consultazione(
    request,
    azione: str,
    modulo: str,
    dettaglio: dict | None = None,
    *,
    chiave: str,
    oggetto=None,
    oggetto_tipo: str = "",
    oggetto_id: str = "",
    finestra_secondi: int = 3600,
) -> None:
    """Traccia la **lettura** di un dato personale sensibile (GDPR art. 5.1.f / 32).

    Al piu' una riga per utente e ``chiave`` ogni ``finestra_secondi``: i refresh e
    la paginazione non annegano l'audit. Mai bloccante: un errore viene solo loggato.
    """
    try:
        from django.core.cache import cache

        utente = getattr(getattr(request, "user", None), "pk", None) or "anon"
        if cache.add(f"audit:consultazione:{azione}:{utente}:{chiave}", 1, finestra_secondi):
            log_action(request, azione, modulo, dettaglio, oggetto=oggetto,
                       oggetto_tipo=oggetto_tipo, oggetto_id=oggetto_id)
    except Exception:
        logger.warning("Audit consultazione %s fallito", azione, exc_info=True)


def log_action(
    request,
    azione: str,
    modulo: str,
    dettaglio: dict | str | None = None,
    *,
    oggetto=None,
    oggetto_tipo: str = "",
    oggetto_id: str = "",
) -> None:
    """Registra un'azione nell'AuditLog Django.

    Chiamata fire-and-forget: eventuali errori DB sono loggati ma non propagati.

    ``dettaglio`` è tollerante al tipo: un ``dict`` viene usato così com'è, una
    ``str`` viene incapsulata in ``{"dettaglio": ...}``, ``None``/vuoto dà ``{}``.
    Molte call-site storiche passano una stringa: senza questo wrap ``dict("...")``
    solleverebbe ``ValueError`` e l'audit andava perso silenziosamente.

    ``oggetto`` (o la coppia ``oggetto_tipo``/``oggetto_id`` per il legacy) aggancia
    la voce al record toccato, ed è ciò che rende possibile lo storico mostrato
    sulla scheda — vedi :func:`storico_oggetto`. È **opzionale**: le chiamate
    storiche che non lo passano continuano a funzionare identiche, semplicemente
    restano fuori dagli storici per record.
    """
    try:
        from core.models import AuditLog

        impersonator_legacy_user = getattr(request, "impersonator_legacy_user", None)
        impersonator_user = getattr(request, "impersonator_user", None)
        effective_legacy_user = getattr(request, "legacy_user", None)
        actor_legacy_user = impersonator_legacy_user or effective_legacy_user
        actor_display = display_name_for_user(
            django_user=impersonator_user or getattr(request, "user", None),
            legacy_user=actor_legacy_user,
        )
        if isinstance(dettaglio, str):
            payload = {"dettaglio": dettaglio} if dettaglio else {}
        elif dettaglio:
            payload = dict(dettaglio)
        else:
            payload = {}
        if getattr(request, "impersonation_active", False):
            payload.setdefault(
                "_impersonation",
                {
                    "impersonated_legacy_user_id": getattr(getattr(request, "impersonated_legacy_user", None), "id", None),
                    "impersonated_display": display_name_for_user(
                        django_user=getattr(request, "impersonated_user", None) or getattr(request, "user", None),
                        legacy_user=getattr(request, "impersonated_legacy_user", None) or effective_legacy_user,
                    ),
                },
            )
        tipo, identificativo = _riferimento_oggetto(oggetto, oggetto_tipo, oggetto_id)
        AuditLog.objects.create(
            legacy_user_id=actor_legacy_user.id if actor_legacy_user else None,
            utente_display=actor_display,
            azione=azione,
            modulo=modulo,
            dettaglio=payload,
            ip_address=_get_client_ip(request),
            oggetto_tipo=tipo,
            oggetto_id=identificativo,
        )
    except Exception:
        logger.exception("audit log fallito: azione=%s modulo=%s", azione, modulo)


def storico_oggetto(oggetto=None, *, oggetto_tipo: str = "", oggetto_id: str = "", limit: int = 50):
    """Le voci di audit di un singolo record, dalla più recente.

    Restituisce sempre un queryset (vuoto se il riferimento non è determinabile),
    così il chiamante non deve difendersi dal ``None``.
    """
    from core.models import AuditLog

    tipo, identificativo = _riferimento_oggetto(oggetto, oggetto_tipo, oggetto_id)
    if not tipo or not identificativo:
        return AuditLog.objects.none()
    return AuditLog.objects.filter(
        oggetto_tipo=tipo, oggetto_id=identificativo
    ).order_by("-created_at")[:limit]


AZIONI_AUTOMATICHE = {
    "auto_insert": "Creazione",
    "auto_update": "Modifica",
    "auto_delete": "Eliminazione",
}


# verbose_name di default (dal nome del campo) dei campi più comuni senza etichetta.
ETICHETTE_COMUNI = {
    "is active": "Attivo",
    "created at": "Creato il",
    "updated at": "Aggiornato il",
}


def storico_leggibile(voci) -> list:
    """Le voci di audit pronte per lo storico in pagina.

    Ogni ``dettaglio["modifiche"]`` nella forma ``{campo: {"old", "new"}}`` (quello
    dei segnali automatici, ma anche di ``log_action`` che lo usano) diventa una
    riga «campo: prima → dopo»; creazioni ed eliminazioni automatiche mostrano i
    valori. Etichette dei campi, valori delle scelte e nomi dei record collegati
    (FK) vengono dal modello indicato in ``oggetto_tipo``, al posto del JSON
    grezzo. Le altre voci restano com'erano (azione + dettaglio).
    """
    from types import SimpleNamespace

    from django.apps import apps

    from core import audit_policy

    modelli: dict = {}
    cache_fk: dict = {}

    def _modello(etichetta: str):
        if etichetta not in modelli:
            try:
                modelli[etichetta] = apps.get_model(etichetta) if "." in etichetta else None
            except LookupError:
                modelli[etichetta] = None
        return modelli[etichetta]

    def _valore(field, val):
        if val is None or val == "":
            return "—"
        if isinstance(val, bool):
            return "Sì" if val else "No"
        if field is None:
            return str(val)
        if field.choices:
            return str(dict(field.flatchoices).get(val, val))
        if field.is_relation and field.related_model is not None:
            chiave = (field.related_model, val)
            if chiave not in cache_fk:
                try:
                    collegato = field.related_model._default_manager.filter(pk=val).first()
                except Exception:
                    collegato = None
                cache_fk[chiave] = str(collegato) if collegato is not None else f"#{val}"
            return cache_fk[chiave]
        return str(val)

    risultato = []
    for voce in voci:
        dettaglio = voce.dettaglio if isinstance(voce.dettaglio, dict) else {}
        model = _modello(voce.oggetto_tipo or "")
        campi = {f.attname: f for f in model._meta.concrete_fields} if model is not None else {}
        ignorati = frozenset()
        if model is not None:
            # Fuori anche data di creazione e chiave: non dicono cosa è cambiato.
            ignorati = audit_policy.ignored_fields(model) | {model._meta.pk.attname} | {
                f.attname for f in model._meta.concrete_fields if getattr(f, "auto_now_add", False)
            }

        def _da_mostrare(attname, campi=campi, ignorati=ignorati) -> bool:
            # Con il modello noto si mostrano solo i suoi campi veri: le M2M finiscono
            # nello snapshot come testo del manager («app.Modello.None»), non come valori.
            return attname not in ignorati and (not campi or attname in campi)

        def _riga(attname, prima, dopo, campi=campi):
            field = campi.get(attname)
            etichetta = str(field.verbose_name) if field is not None else str(attname)
            etichetta = ETICHETTE_COMUNI.get(etichetta, etichetta)
            return {"campo": etichetta[:1].upper() + etichetta[1:],
                    "prima": _valore(field, prima), "dopo": _valore(field, dopo)}

        righe = []
        modifiche = dettaglio.get("modifiche")
        if isinstance(modifiche, dict):
            for attname, diff in modifiche.items():
                if not _da_mostrare(attname) or not isinstance(diff, dict):
                    continue
                righe.append(_riga(attname, diff.get("old"), diff.get("new")))
        elif voce.azione in ("auto_insert", "auto_delete"):
            chiave_valori = "valori" if "valori" in dettaglio else "nuovi_valori"
            for attname, val in (dettaglio.get(chiave_valori) or {}).items():
                if not _da_mostrare(attname) or val in (None, ""):
                    continue
                righe.append(_riga(attname, None, val) if voce.azione == "auto_insert" else _riga(attname, val, None))
        if not righe and voce.azione in AZIONI_AUTOMATICHE:
            # Modelli «metadata_only»: si sa quali campi, mai i valori.
            for attname in dettaglio.get("campi") or dettaglio.get("campi_valorizzati") or []:
                if _da_mostrare(attname):
                    riga = _riga(attname, None, None)
                    riga["dopo"] = "modificato" if voce.azione == "auto_update" else "valorizzato"
                    righe.append(riga)
        resto = {} if voce.azione in AZIONI_AUTOMATICHE else {
            k: v for k, v in dettaglio.items() if k != "modifiche"
        }
        risultato.append(SimpleNamespace(
            azione=voce.azione,
            azione_label=AZIONI_AUTOMATICHE.get(voce.azione, voce.azione.replace("_", " ").capitalize()),
            created_at=voce.created_at,
            utente_display=voce.utente_display,
            modulo=voce.modulo,
            oggetto_tipo=voce.oggetto_tipo,
            oggetto_id=voce.oggetto_id,
            oggetto_label=str(dettaglio.get("oggetto") or ""),
            righe=righe,
            dettaglio=resto,
        ))
    return risultato


def _get_client_ip(request) -> str | None:
    # Comandi di gestione e job non hanno una richiesta: niente IP, ma l'audit si scrive.
    from core.net import client_ip

    return client_ip(request)
