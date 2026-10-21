"""Retention GDPR dei dati HR.

Un solo punto di calcolo per il comando ``cleanup_expired_documents``, per il
report settimanale in monitoring (solo conteggi, nessuna cancellazione) e per la
pagina «Conservazione dei dati», dove un amministratore dell'anagrafica conferma
l'eliminazione dei documenti e l'anonimizzazione dei candidati. Ogni azione
ricontrolla che il dato sia ancora oltre la conservazione e va nel registro.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

logger = logging.getLogger(__name__)

CHECK_NAME = "anagrafica_retention_report"
# Candidati chiusi senza esito utile o tenuti «in database» (decisione GDPR del
# 21/10/2026): oltre questi mesi dall'ultima modifica i loro dati vanno rivalutati.
MESI_CONSERVAZIONE_CANDIDATI = 24


def _mesi_fa(oggi: date, mesi: int) -> date:
    """``oggi`` meno ``mesi`` mesi di calendario (giorno clampato a fine mese).

    ``models._add_months`` con mesi negativi restituisce la data invariata: usato
    qui faceva risultare «oltre la conservazione» qualunque candidato chiuso prima
    di oggi (fix del 21/10/2026)."""
    import calendar

    indice = oggi.year * 12 + (oggi.month - 1) - int(mesi)
    anno, mese = divmod(indice, 12)
    return date(anno, mese + 1, min(oggi.day, calendar.monthrange(anno, mese + 1)[1]))


@dataclass
class EsitoDocumenti:
    esaminati: int = 0
    saltati_attivi: int = 0
    saltati_retention: int = 0
    da_eliminare: list = field(default_factory=list)  # [(documento, data_cessazione)]


def documenti_scaduti(*, oggi: date | None = None, tipo: str = "", limit: int | None = None) -> EsitoDocumenti:
    """Documenti con retention scaduta di persone cessate da piu' degli anni di legge.

    Criteri (tutti veri): ``retention_until`` passato, data di cessazione valorizzata,
    ``cessazione + anni di retention del tipo`` passata. Un dipendente attivo non
    perde mai documenti.
    """
    from anagrafica.models import DipendenteAnagraficaAziendale, DocumentoDipendente, _add_months

    oggi = oggi or timezone.localdate()
    qs = DocumentoDipendente.objects.filter(
        retention_until__isnull=False, retention_until__lt=oggi,
    ).order_by("retention_until", "id")
    if tipo:
        qs = qs.filter(tipo=tipo)
    legacy_ids = list(qs.values_list("legacy_anagrafica_id", flat=True).distinct())
    cessazioni = dict(
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=legacy_ids)
        .values_list("legacy_anagrafica_id", "data_cessazione")
    )
    esito = EsitoDocumenti()
    for doc in (qs[:limit] if limit else qs):
        esito.esaminati += 1
        cessazione = cessazioni.get(doc.legacy_anagrafica_id)
        if cessazione is None:
            esito.saltati_attivi += 1
            continue
        anni = DocumentoDipendente._RETENTION_ANNI.get(doc.tipo, 10)
        if _add_months(cessazione, anni * 12) >= oggi:
            esito.saltati_retention += 1
            continue
        esito.da_eliminare.append((doc, cessazione))
    return esito


# Cognome scritto sui candidati resi anonimi: escono dal report e dalle ricerche.
COGNOME_ANONIMO = "[anonimizzato]"
# Dati personali del candidato svuotati dall'anonimizzazione. Restano stato, date,
# posizione, canale, mansione cercata, esiti e punteggi: servono alle statistiche
# del recruiting e non identificano la persona.
CAMPI_PERSONALI_CANDIDATO = (
    "nome", "cellulare", "email", "localita", "provincia", "azienda_attuale", "mansione_attuale",
    "livello_contratto_attuale", "eta", "titolo_studio", "cittadinanza", "lingua_inglese_livello",
    "disponibilita", "motivo_cambio_lavoro", "note", "note_secondo_colloquio", "offerta_note",
    "canale_dettaglio", "occupato_attualmente", "idoneita_tirocinio", "idoneita_apprendistato",
    "rischio_abbandono",
)


def candidati_scaduti(*, oggi: date | None = None):
    """Candidati chiusi (non idonei, rinunce, annullati) o tenuti «in database» fermi da
    oltre la conservazione. Gli assunti passano alla scheda del dipendente e restano."""
    from anagrafica.models_recruiting import Candidato

    oggi = oggi or timezone.localdate()
    soglia = _mesi_fa(oggi, MESI_CONSERVAZIONE_CANDIDATI)
    return Candidato.objects.filter(
        stato__in=(Candidato.STATO_SCARTATO, Candidato.STATO_RINUNCIA, Candidato.STATO_ANNULLATO,
                   Candidato.STATO_IN_DATABASE),
        updated_at__date__lt=soglia,
    ).exclude(cognome=COGNOME_ANONIMO).order_by("updated_at", "id")


def candidati_da_rivalutare(*, oggi: date | None = None) -> int:
    return candidati_scaduti(oggi=oggi).count()


def elimina_documenti(request, ids, *, oggi: date | None = None) -> dict:
    """Elimina (file compreso) i documenti indicati, ma solo quelli che oggi risultano
    ancora oltre la conservazione: un id che non lo è più viene saltato (fail-closed).
    Una riga di registro attività per documento, senza contenuto del file."""
    from core.audit import log_action

    ammessi = {doc.pk: (doc, cessazione) for doc, cessazione in documenti_scaduti(oggi=oggi).da_eliminare}
    esito = {"eliminati": 0, "saltati": 0, "errori": 0}
    for doc_id in {int(i) for i in ids}:
        coppia = ammessi.get(doc_id)
        if coppia is None:
            esito["saltati"] += 1
            continue
        doc, cessazione = coppia
        dettaglio = {"oggetto": "retention_documento", "documento_id": doc.pk, "tipo": doc.tipo,
                     "legacy_anagrafica_id": doc.legacy_anagrafica_id, "cessazione": str(cessazione),
                     "retention_until": str(doc.retention_until)}
        try:
            doc.delete()
        except Exception:
            logger.exception("Retention: eliminazione documento %s fallita", doc_id)
            esito["errori"] += 1
            continue
        log_action(request, "delete", "anagrafica", dettaglio)
        esito["eliminati"] += 1
    return esito


def anonimizza_candidati(request, ids, *, oggi: date | None = None) -> dict:
    """Rende anonimi i candidati indicati ancora oltre la conservazione: svuota i dati
    personali e toglie lo storico delle modifiche (che li conteneva). Il record resta
    per le statistiche del recruiting. Registro attività senza nominativi."""
    from django.db import transaction

    from anagrafica.models_recruiting import Candidato
    from core.audit import log_action

    ammessi = set(candidati_scaduti(oggi=oggi).filter(pk__in={int(i) for i in ids}).values_list("pk", flat=True))
    esito = {"anonimizzati": 0, "saltati": len({int(i) for i in ids}) - len(ammessi)}
    for candidato in Candidato.objects.filter(pk__in=ammessi):
        with transaction.atomic():
            for nome in CAMPI_PERSONALI_CANDIDATO:
                campo = Candidato._meta.get_field(nome)
                setattr(candidato, nome, None if campo.null else campo.get_default())
            candidato.cognome = COGNOME_ANONIMO
            candidato.save()
            candidato.log_modifiche.all().delete()
        log_action(request, "update", "anagrafica", {
            "oggetto": "retention_candidato", "candidato_id": candidato.pk,
            "codice_riferimento": candidato.codice_riferimento, "stato": candidato.stato,
        })
        esito["anonimizzati"] += 1
    return esito


# Dipendenti cessati (decisione GDPR del 21/10/2026, termini da validare col DPO):
# passati questi anni dalla cessazione si tolgono i dati personali che non servono
# piu' allo storico. Restano anagrafica aziendale, formazione, DPI e le visite con
# date ed esito (lo storico); si svuotano dati civili e familiari, recapiti privati,
# prescrizioni e note delle visite; si cancellano voci retributive e saldi cedolino.
ANNI_CONSERVAZIONE_CESSATI = 10
# Campi civili che restano: il genere serve alle statistiche, non identifica.
CAMPI_CIVILI_TENUTI = frozenset({"id", "legacy_anagrafica_id", "genere", "updated_at", "updated_by"})
CAMPI_AZIENDALI_PERSONALI = ("taglia_scarpe", "taglia_pantalone", "taglia_maglia", "telefono_aziendale")


def _valore_vuoto(campo):
    if campo.null:
        return None
    default = campo.get_default()
    return default if default is not None else ""


def _civile_ha_dati(civile) -> bool:
    for campo in civile._meta.concrete_fields:
        if campo.name in CAMPI_CIVILI_TENUTI:
            continue
        valore = getattr(civile, campo.name)
        if campo.name == "foto":
            if valore:
                return True
            continue
        if valore not in (None, "", False, _valore_vuoto(campo)):
            return True
    return False


def cessati_da_minimizzare(*, oggi: date | None = None, limit: int | None = None) -> list[dict]:
    """Cessati da oltre ``ANNI_CONSERVAZIONE_CESSATI`` anni che hanno ancora dati da
    togliere. Riassunti dopo la cessazione (assunzione successiva) esclusi. Idempotente:
    chi e' gia' stato minimizzato non ricompare."""
    from django.db.models import F, Q

    from anagrafica.models import (
        DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile, FiglioACarico, SaldoCedolino,
        VisitaMedica, VoceRetributiva,
    )

    oggi = oggi or timezone.localdate()
    soglia = _mesi_fa(oggi, ANNI_CONSERVAZIONE_CESSATI * 12)
    aziendali = (
        DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False, data_cessazione__lt=soglia)
        .exclude(data_assunzione_ultima__gt=F("data_cessazione"))
        .order_by("data_cessazione", "legacy_anagrafica_id")
    )
    righe = []
    for az in aziendali.iterator():
        lid = az.legacy_anagrafica_id
        civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=lid).first()
        conteggi = {
            "civili": int(bool(civile and _civile_ha_dati(civile))),
            "figli": FiglioACarico.objects.filter(anagrafica__legacy_anagrafica_id=lid).count(),
            "retribuzioni": VoceRetributiva.objects.filter(legacy_anagrafica_id=lid).count(),
            "saldi": SaldoCedolino.objects.filter(legacy_anagrafica_id=lid).count(),
            "visite": VisitaMedica.objects.filter(legacy_anagrafica_id=lid)
            .filter(~Q(prescrizioni="") | ~Q(note="") | ~Q(scadenza_nota="")).count(),
            "aziendali": int(any(getattr(az, c) for c in CAMPI_AZIENDALI_PERSONALI)),
        }
        if any(conteggi.values()):
            righe.append({"legacy_anagrafica_id": lid, "cessazione": az.data_cessazione, **conteggi})
            if limit and len(righe) >= limit:
                break
    return righe


def minimizza_cessati(request, ids, *, oggi: date | None = None) -> dict:
    """Toglie i dati personali non piu' necessari ai cessati indicati, solo se oggi
    risultano ancora oltre la conservazione. Registro attivita' con i soli conteggi."""
    from django.db import transaction

    from anagrafica.models import (
        DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile, FiglioACarico, SaldoCedolino,
        VisitaMedica, VoceRetributiva,
    )
    from core.audit import log_action

    richiesti = {int(i) for i in ids}
    ammessi = {r["legacy_anagrafica_id"]: r for r in cessati_da_minimizzare(oggi=oggi)
               if r["legacy_anagrafica_id"] in richiesti}
    esito = {"minimizzati": 0, "saltati": len(richiesti) - len(ammessi), "errori": 0}
    for lid, riga in ammessi.items():
        try:
            with transaction.atomic():
                civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=lid).first()
                codice_fiscale = (civile.codice_fiscale or "").strip() if civile else ""
                VoceRetributiva.objects.filter(legacy_anagrafica_id=lid).delete()
                SaldoCedolino.objects.filter(legacy_anagrafica_id=lid).delete()
                if codice_fiscale:
                    VoceRetributiva.objects.filter(legacy_anagrafica_id__isnull=True, tax_code=codice_fiscale).delete()
                    SaldoCedolino.objects.filter(legacy_anagrafica_id__isnull=True, tax_code=codice_fiscale).delete()
                FiglioACarico.objects.filter(anagrafica__legacy_anagrafica_id=lid).delete()
                VisitaMedica.objects.filter(legacy_anagrafica_id=lid).update(prescrizioni="", note="", scadenza_nota="")
                DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=lid).update(
                    **{c: "" for c in CAMPI_AZIENDALI_PERSONALI}
                )
                if civile:
                    if civile.foto:
                        civile.foto.delete(save=False)
                    for campo in civile._meta.concrete_fields:
                        if campo.name in CAMPI_CIVILI_TENUTI or campo.name == "foto":
                            continue
                        setattr(civile, campo.name, _valore_vuoto(campo))
                    civile.foto = ""
                    civile.save()
        except Exception:
            logger.exception("Retention: minimizzazione del cessato %s fallita", lid)
            esito["errori"] += 1
            continue
        log_action(request, "update", "anagrafica", {
            "oggetto": "retention_cessato", "legacy_anagrafica_id": lid,
            "cessazione": str(riga["cessazione"]),
            "rimossi": {k: riga[k] for k in ("civili", "figli", "retribuzioni", "saldi", "visite", "aziendali")},
        })
        esito["minimizzati"] += 1
    return esito


def report_retention(*, oggi: date | None = None) -> dict:
    """Riepilogo in sola lettura: conteggi per tipo documento e candidati da rivalutare."""
    esito = documenti_scaduti(oggi=oggi)
    per_tipo: dict[str, int] = {}
    for doc, _cessazione in esito.da_eliminare:
        per_tipo[doc.tipo] = per_tipo.get(doc.tipo, 0) + 1
    return {
        "documenti_da_eliminare": len(esito.da_eliminare),
        "documenti_per_tipo": dict(sorted(per_tipo.items())),
        "documenti_di_attivi": esito.saltati_attivi,
        "candidati_da_rivalutare": candidati_da_rivalutare(oggi=oggi),
        "cessati_da_minimizzare": len(cessati_da_minimizzare(oggi=oggi)),
    }


def pubblica_in_monitoring(report: dict) -> dict:
    """Una Issue (dedup) in monitoring se c'e' qualcosa oltre la conservazione.

    Il messaggio contiene solo conteggi: nessun nome, nessun dato sanitario.
    Nulla viene cancellato: la cancellazione resta ``cleanup_expired_documents --apply``.
    """
    from monitoring.models import Issue
    from monitoring.services import open_or_update_issue_from_health_check, resolve_health_check_issue

    documenti = report["documenti_da_eliminare"]
    candidati = report["candidati_da_rivalutare"]
    cessati = report.get("cessati_da_minimizzare", 0)
    if not documenti and not candidati and not cessati:
        resolve_health_check_issue(check_name=CHECK_NAME, category=Issue.Category.DATA,
                                   summary="Retention HR: nessun dato oltre la conservazione.")
        return report
    righe = [f"Documenti dipendente oltre la conservazione: {documenti}"]
    righe += [f"  {tipo}: {n}" for tipo, n in report["documenti_per_tipo"].items()]
    righe.append(f"Candidati chiusi o in database fermi da oltre {MESI_CONSERVAZIONE_CANDIDATI} mesi: {candidati}")
    righe.append(f"Dipendenti cessati da oltre {ANNI_CONSERVAZIONE_CESSATI} anni con dati da togliere: {cessati}")
    righe.append("Report in sola lettura: nulla e' stato cancellato. Per eliminare dopo una verifica: "
                 "Anagrafica → Impostazioni → «Conservazione dei dati» (/anagrafica/impostazioni/retention/).")
    open_or_update_issue_from_health_check(
        check_name=CHECK_NAME,
        title=f"Retention HR: {documenti} documenti, {candidati} candidati, {cessati} cessati oltre la conservazione",
        message="\n".join(righe)[:8000],
        severity=Issue.Severity.LOW,
        category=Issue.Category.DATA, module_name="anagrafica",
        extra_json=report,
        notify=False,
    )
    return report
