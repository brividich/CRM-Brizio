"""Ricalcolo delle scadenze HR a ogni modifica dei dati da cui dipendono.

Il motore dei requisiti (``services.requisiti``) calcola al volo, ma due cose
sono salvate a DB e vanno tenute allineate: la cache ``TrainingDeadline``
(scadenzario formazione, KPI, promemoria) e ``VisitaMedica.data_scadenza``
(scadenza effettiva). Prima si riallineavano solo salvando una visita, chiudendo
un corso, registrando uno spostamento e la notte: una mansione con una visita in
piu', un tipo di visita con un'altra durata, un ruolo assegnato o un attestato
cancellato restavano sbagliati fino alle 00:20.

Qui ogni salvataggio o cancellazione di un dato letto dal motore programma il
ricalcolo a transazione conclusa (``scadenze.ricalcola_dopo_commit``, uno per
transazione):

- dati **della persona** (visite, attestati, ruoli, protocollo sanitario, scheda
  aziendale, esposizioni dirette, abilitazioni ai processi, regole individuali):
  ricalcolo della persona (e della precedente, se il record cambia persona);
- **cataloghi** (tipi visita, corsi, piani, mansioni, fattori di rischio,
  categorie corso, ruoli, aree, processi, regole di mansione/ruolo/area) e le
  loro relazioni molti-a-molti: ricalcolo di tutti (meno di un secondo).

Restano fuori le scritture massive senza segnali (``update()``, ``bulk_create``,
SQL diretto): le copre il ricalcolo notturno, e chi le fa in un flusso utente
chiama ``ricalcola_dopo_commit`` da se' (es. ``core.legacy_anagrafica``).
"""
from __future__ import annotations

import logging

from django.apps import apps
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save

logger = logging.getLogger(__name__)

# Dati per persona: (app, modello).
PERSONA = [
    ("anagrafica", "VisitaMedica"),
    ("anagrafica", "TrainingEmployeeRecord"),
    ("anagrafica", "DipendenteRuoloOperativo"),
    ("anagrafica", "RequisitoVisitaDipendente"),
    ("anagrafica", "DipendenteAnagraficaAziendale"),
    ("anagrafica", "DipendenteAssegnazione"),
    ("anagrafica", "AbilitazioneProcesso"),
]
# Possono essere della persona o di tutti (regole, esposizioni): decide il record.
MISTI = [
    ("anagrafica", "TrainingRequirementRule", ("mansione_id", "ruolo_operativo_id", "area_id")),
    ("anagrafica", "EsposizioneRischio", ("mansione_id", "area_id")),
]
# Cataloghi: (app, modello, campi che contano; None = tutti).
CATALOGHI = [
    ("anagrafica", "TipoVisitaMedica", ("durata_mesi", "categoria", "obbligatoria", "is_active")),
    ("anagrafica", "TrainingCourse", ("validita_mesi", "is_active", "piano_id", "categoria_id")),
    ("anagrafica", "TrainingPlan", ("stato", "is_active")),
    ("anagrafica", "Mansione", ("nome", "is_active")),
    ("anagrafica", "FattoreRischio", None),
    ("anagrafica", "CategoriaCorso", None),
    ("anagrafica", "RuoloOperativo", None),
    ("anagrafica", "AreaAziendale", None),
    ("anagrafica", "ProcessoQualificato", None),
]
# Anagrafica legacy via ORM: la chiave primaria e' l'id della persona.
LEGACY = ("core", "AnagraficaDipendente")

_UID = "anagrafica_scadenze_"


def _ricalcola(ids) -> None:
    from anagrafica.services.scadenze import ricalcola_dopo_commit

    try:
        ricalcola_dopo_commit(ids)
    except Exception:
        # Il ricalcolo non deve mai impedire il salvataggio: lo riprende la notte.
        logger.exception("programmazione ricalcolo scadenze fallita per %s", ids or "tutti")


def _vecchi_valori(sender, instance, campi):
    if instance.pk is None:
        return None
    try:
        return sender._default_manager.filter(pk=instance.pk).values(*campi).first()
    except Exception:
        return None


# ── Persona ───────────────────────────────────────────────────────────────
def _persona_pre_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    vecchio = _vecchi_valori(sender, instance, ["legacy_anagrafica_id"])
    instance._scadenze_persona_prima = (vecchio or {}).get("legacy_anagrafica_id")


def _persona_post(sender, instance, raw=False, **kwargs):
    if raw:
        return
    ids = {getattr(instance, "legacy_anagrafica_id", None), getattr(instance, "_scadenze_persona_prima", None)}
    ids = [i for i in ids if i and int(i) > 0]
    if ids:
        _ricalcola(ids)


# ── Misti ─────────────────────────────────────────────────────────────────
def _misto_post(campi_tutti):
    def handler(sender, instance, raw=False, **kwargs):
        if raw:
            return
        if any(getattr(instance, c, None) for c in campi_tutti):
            _ricalcola(None)
            return
        _persona_post(sender, instance, raw=raw)
        # Una regola che prima valeva per una mansione/area e ora no: anche i vecchi destinatari.
        if any((getattr(instance, "_scadenze_misto_prima", None) or {}).get(c) for c in campi_tutti):
            _ricalcola(None)

    return handler


def _misto_pre_save(campi_tutti):
    def handler(sender, instance, raw=False, **kwargs):
        if raw:
            return
        vecchio = _vecchi_valori(sender, instance, ["legacy_anagrafica_id", *campi_tutti])
        instance._scadenze_persona_prima = (vecchio or {}).get("legacy_anagrafica_id")
        instance._scadenze_misto_prima = vecchio

    return handler


# ── Cataloghi ─────────────────────────────────────────────────────────────
def _catalogo_pre_save(campi):
    def handler(sender, instance, raw=False, **kwargs):
        if raw or campi is None:
            return
        instance._scadenze_catalogo_prima = _vecchi_valori(sender, instance, list(campi))

    return handler


def _catalogo_post_save(campi):
    def handler(sender, instance, created=False, raw=False, update_fields=None, **kwargs):
        if raw:
            return
        if campi is not None and not created:
            if update_fields is not None and not ({f.replace("_id", "") for f in campi}
                                                  & {f.replace("_id", "") for f in update_fields}):
                return
            prima = getattr(instance, "_scadenze_catalogo_prima", None)
            if prima is not None and all(prima.get(c) == getattr(instance, c, None) for c in campi):
                return  # cambiati solo campi descrittivi
        _ricalcola(None)

    return handler


def _catalogo_post_delete(sender, instance, **kwargs):
    _ricalcola(None)


def _m2m_changed(sender, action=None, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        _ricalcola(None)


# ── Qualifiche: durata del tipo ───────────────────────────────────────────
def _tipo_qualifica_pre_save(sender, instance, raw=False, **kwargs):
    vecchio = None if raw else _vecchi_valori(sender, instance, ["durata_mesi"])
    instance._durata_prima = (vecchio or {}).get("durata_mesi")


def _tipo_qualifica_post_save(sender, instance, created=False, raw=False, **kwargs):
    """Cambia la durata del tipo: si ricalcolano le scadenze ancora automatiche.

    ``DipendenteQualifica.data_scadenza`` si scrive alla registrazione
    (conseguimento + durata del tipo, o data inserita a mano). Una scadenza uguale
    a quella automatica con la durata vecchia segue la nuova; una diversa e' stata
    inserita a mano e resta.
    """
    if raw or created or instance._durata_prima is None or instance._durata_prima == instance.durata_mesi:
        return
    from anagrafica.models import DipendenteQualifica, _add_months

    vecchia, nuova = instance._durata_prima or 0, instance.durata_mesi or 0
    n = 0
    for q in DipendenteQualifica.objects.filter(tipo=instance, data_conseguimento__isnull=False):
        automatica = _add_months(q.data_conseguimento, vecchia) if vecchia > 0 else None
        if q.data_scadenza != automatica:
            continue
        attesa = _add_months(q.data_conseguimento, nuova) if nuova > 0 else None
        if attesa != q.data_scadenza:
            DipendenteQualifica.objects.filter(pk=q.pk).update(data_scadenza=attesa)
            n += 1
    if n:
        logger.info("qualifiche: durata tipo %s %s→%s mesi, %d scadenze riallineate", instance.pk, vecchia, nuova, n)


def _legacy_post(sender, instance, raw=False, **kwargs):
    if not raw and instance.pk:
        _ricalcola([instance.pk])


def collega() -> None:
    """Registra i segnali (idempotente: dispatch_uid)."""
    def modello(app, nome):
        try:
            return apps.get_model(app, nome)
        except LookupError:
            return None

    for app, nome in PERSONA:
        m = modello(app, nome)
        if m is None:
            continue
        pre_save.connect(_persona_pre_save, sender=m, dispatch_uid=f"{_UID}pre_{nome}")
        post_save.connect(_persona_post, sender=m, dispatch_uid=f"{_UID}save_{nome}")
        post_delete.connect(_persona_post, sender=m, dispatch_uid=f"{_UID}del_{nome}")

    for app, nome, campi_tutti in MISTI:
        m = modello(app, nome)
        if m is None:
            continue
        pre_save.connect(_misto_pre_save(campi_tutti), sender=m, dispatch_uid=f"{_UID}pre_{nome}", weak=False)
        post_save.connect(_misto_post(campi_tutti), sender=m, dispatch_uid=f"{_UID}save_{nome}", weak=False)
        post_delete.connect(_misto_post(campi_tutti), sender=m, dispatch_uid=f"{_UID}del_{nome}", weak=False)

    for app, nome, campi in CATALOGHI:
        m = modello(app, nome)
        if m is None:
            continue
        pre_save.connect(_catalogo_pre_save(campi), sender=m, dispatch_uid=f"{_UID}pre_{nome}", weak=False)
        post_save.connect(_catalogo_post_save(campi), sender=m, dispatch_uid=f"{_UID}save_{nome}", weak=False)
        post_delete.connect(_catalogo_post_delete, sender=m, dispatch_uid=f"{_UID}del_{nome}")
        for campo in m._meta.many_to_many:
            m2m_changed.connect(_m2m_changed, sender=campo.remote_field.through,
                                dispatch_uid=f"{_UID}m2m_{nome}_{campo.name}")

    m = modello("anagrafica", "TipoQualifica")
    pre_save.connect(_tipo_qualifica_pre_save, sender=m, dispatch_uid=f"{_UID}pre_TipoQualifica")
    post_save.connect(_tipo_qualifica_post_save, sender=m, dispatch_uid=f"{_UID}save_TipoQualifica")

    m = modello(*LEGACY)
    if m is not None:
        post_save.connect(_legacy_post, sender=m, dispatch_uid=f"{_UID}save_legacy")
        post_delete.connect(_legacy_post, sender=m, dispatch_uid=f"{_UID}del_legacy")
