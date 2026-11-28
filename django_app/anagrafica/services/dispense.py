"""Dispense dei corsi per i dipendenti: chi vede cosa, stato del corso per la persona, ricerca.

Una dispensa è un allegato **del corso** (``TrainingAttachment`` con ``corso``) spuntato
«Visibile ai dipendenti». Mai i registri firme né gli allegati delle edizioni (le copie
servono a HR per documentare cosa è stato consegnato).

Regole:

- il dipendente vede le dispense visibili dei corsi attivi; quelle «Solo a chi ha il corso»
  solo se ha il corso (assegnato, iscritto a un'edizione non annullata, iscritto all'e-learning
  o con un completamento a libretto);
- chi gestisce o consulta la formazione vede tutte le dispense visibili, anche dei corsi archiviati;
- «Ho letto» registra una conferma per persona e dispensa (libretto formativo);
- ricerca: titolo, corso e testo estratto dei PDF, con le stesse regole di CN-SGI
  (radici, accenti, parole in qualunque ordine) e la pagina del PDF.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

TIPI_DISPENSA = ("MATERIALE", "PROGRAMMA", "ALTRO")
STATI_ASSEGNAZIONE_APERTI = ("ASSEGNATO", "IN_CORSO", "SCADUTO", "RIMANDATO")
GIORNI_NUOVE = 30
GIORNI_CONSULTATE = 90
COLORE_SENZA_TIPO = "#475569"
ETICHETTE = {"MATERIALE": "Dispensa", "PROGRAMMA": "Programma", "ALTRO": "Altro"}


def base():
    """Dispense pubblicabili: materiale del corso spuntato «Visibile ai dipendenti»."""
    from ..models_formazione import TrainingAttachment
    return (TrainingAttachment.objects
            .filter(corso__isnull=False, visibile_dipendenti=True, tipo__in=TIPI_DISPENSA)
            .select_related("corso", "corso__tipo"))


def corsi_della_persona(legacy_id: int | None) -> set[int]:
    """Corsi che la persona «ha»: assegnati, iscritta (edizione o e-learning) o fatti."""
    if not legacy_id:
        return set()
    from ..models_formazione import (TrainingAssignment, TrainingElearningEnrollment, TrainingEmployeeRecord,
                                     TrainingEnrollment)
    ids = set(TrainingAssignment.objects.filter(legacy_anagrafica_id=legacy_id).values_list("corso_id", flat=True))
    ids |= set(TrainingEnrollment.objects.filter(legacy_anagrafica_id=legacy_id)
               .exclude(stato="RITIRATO").exclude(sessione__stato="ANNULLATA")
               .values_list("sessione__corso_id", flat=True))
    ids |= set(TrainingElearningEnrollment.objects.filter(legacy_anagrafica_id=legacy_id).values_list("corso_id", flat=True))
    ids |= set(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=legacy_id, annullato_il__isnull=True)
               .values_list("corso_id", flat=True))
    return ids


class Contesto:
    """Chi guarda: persona collegata, corsi che ha, se vede tutto (formazione)."""

    def __init__(self, legacy_id: int | None, *, tutto: bool = False):
        self.legacy_id = legacy_id
        self.tutto = tutto
        self._corsi = None

    @classmethod
    def da_request(cls, request) -> "Contesto":
        from ..views._helpers import _can_view_formazione, _current_legacy_anagrafica_id
        return cls(_current_legacy_anagrafica_id(request), tutto=_can_view_formazione(request))

    @property
    def corsi(self) -> set[int]:
        if self._corsi is None:
            self._corsi = corsi_della_persona(self.legacy_id)
        return self._corsi


def url_corso(corso_id: int) -> str:
    """La pagina del corso per il dipendente («Corsi e dispense»): stato, passo da fare, dispense."""
    from django.urls import reverse
    return reverse("anagrafica:dispense_corso", args=[corso_id])


def scadenze_della_persona(legacy_id: int | None, *, oggi=None) -> list:
    """Scadenze di formazione obbligatoria della persona, scadute o entro il preavviso (90 giorni):
    stessa fonte dello scadenzario (``TrainingDeadline``)."""
    if not legacy_id:
        return []
    from ..models_formazione import TrainingDeadline
    from ..scadenze_soglie import GIORNI_PREAVVISO
    oggi = oggi or timezone.localdate()
    return list(TrainingDeadline.objects.filter(legacy_anagrafica_id=legacy_id, is_required=True,
                                                data_scadenza__isnull=False,
                                                data_scadenza__lte=oggi + timedelta(days=GIORNI_PREAVVISO))
                .select_related("corso").order_by("data_scadenza"))


def ha_scadenza(legacy_id: int | None, corso_id: int) -> bool:
    if not legacy_id:
        return False
    from ..models_formazione import TrainingDeadline
    return TrainingDeadline.objects.filter(legacy_anagrafica_id=legacy_id, corso_id=corso_id).exists()


def visibili(ctx: Contesto):
    """Dispense che chi guarda può aprire."""
    qs = base()
    if ctx.tutto:
        return qs
    qs = qs.filter(corso__stato="ATTIVO", corso__is_active=True)
    return qs.filter(Q(solo_chi_ha_corso=False) | Q(corso_id__in=list(ctx.corsi)))


def puo_vedere(att, ctx: Contesto) -> bool:
    return visibili(ctx).filter(pk=att.pk).exists()


def letture_di(legacy_id: int | None, allegati_ids) -> dict[int, object]:
    """{allegato_id: data di lettura} della persona."""
    if not legacy_id:
        return {}
    from ..models_formazione import TrainingDispensaLettura
    return dict(TrainingDispensaLettura.objects.filter(legacy_anagrafica_id=legacy_id, allegato_id__in=list(allegati_ids))
                .values_list("allegato_id", "letta_il"))


def aperture_recenti(giorni: int = GIORNI_CONSULTATE) -> dict[int, int]:
    from ..models_formazione import TrainingDispensaApertura
    da = timezone.now() - timedelta(days=giorni)
    return dict(TrainingDispensaApertura.objects.filter(aperta_il__gte=da).values("allegato_id")
                .annotate(n=Count("pk")).order_by().values_list("allegato_id", "n"))


def registra_apertura(att, request, legacy_id: int | None) -> None:
    from ..models_formazione import TrainingDispensaApertura
    try:
        TrainingDispensaApertura.objects.create(allegato=att, legacy_anagrafica_id=legacy_id,
                                                user=request.user if request.user.is_authenticated else None)
    except Exception:
        logger.warning("Apertura dispensa non registrata (%s)", att.pk, exc_info=True)


def registra_lettura(att, legacy_id: int, user) -> bool:
    """«Ho letto»: idempotente. True se registrata adesso."""
    from ..models_formazione import TrainingDispensaLettura
    _obj, creata = TrainingDispensaLettura.objects.get_or_create(
        allegato=att, legacy_anagrafica_id=legacy_id, defaults={"user": user if getattr(user, "pk", None) else None})
    return creata


# ─────────────────────────────────────────────────────────────────────────────
# Stato del corso per la persona
# ─────────────────────────────────────────────────────────────────────────────

def stato_corsi(legacy_id: int | None, corsi_ids) -> dict[int, dict]:
    """{corso_id: {"tono", "etichetta"}}: da fare (assegnato), iscritto, valido, scaduto."""
    corsi_ids = list(corsi_ids)
    if not legacy_id or not corsi_ids:
        return {}
    from ..models_formazione import TrainingAssignment, TrainingEmployeeRecord, TrainingEnrollment
    from .formazione_completamento import record_valido
    oggi = timezone.localdate()
    out: dict[int, dict] = {}
    ultimi = {}
    for r in (TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=legacy_id, corso_id__in=corsi_ids,
                                                    idoneo=True, annullato_il__isnull=True,
                                                    data_completamento__lte=oggi)
              .order_by("data_completamento", "pk")):
        ultimi[r.corso_id] = r
    for cid, r in ultimi.items():
        if record_valido(r, oggi=oggi):
            out[cid] = {"tono": "ok", "etichetta": f"Valido fino al {r.data_scadenza:%d/%m/%Y}" if r.data_scadenza
                        else f"Fatto il {r.data_completamento:%d/%m/%Y}"}
        elif r.data_scadenza:
            out[cid] = {"tono": "bad", "etichetta": f"Scaduto il {r.data_scadenza:%d/%m/%Y}"}
    # Stessa scadenza dello scadenzario e di «Le mie attività» (TrainingDeadline): se è passata e il
    # corso non è valido, il corso è scaduto anche senza un completamento con scadenza.
    from ..models_formazione import TrainingDeadline
    for d in TrainingDeadline.objects.filter(legacy_anagrafica_id=legacy_id, corso_id__in=corsi_ids, is_required=True,
                                             data_scadenza__lt=oggi):
        if out.get(d.corso_id, {}).get("tono") != "ok":
            out[d.corso_id] = {"tono": "bad", "etichetta": f"Scaduto il {d.data_scadenza:%d/%m/%Y}"}
    for e in (TrainingEnrollment.objects.filter(legacy_anagrafica_id=legacy_id, sessione__corso_id__in=corsi_ids,
                                                stato__in=("ISCRITTO", "IN_CORSO"))
              .exclude(sessione__stato__in=("COMPLETATA", "ANNULLATA"))
              .select_related("sessione").order_by("sessione__data_inizio")):
        prima = out.get(e.sessione.corso_id)
        if prima is None:
            out[e.sessione.corso_id] = {"tono": "warn", "etichetta": f"Iscritto all'edizione del {e.sessione.data_inizio:%d/%m/%Y}"}
        elif prima["tono"] == "bad" and "edizione" not in prima["etichetta"]:
            prima["etichetta"] += f" · iscritto all'edizione del {e.sessione.data_inizio:%d/%m/%Y}"
    for a in (TrainingAssignment.objects.filter(legacy_anagrafica_id=legacy_id, corso_id__in=corsi_ids,
                                                stato__in=STATI_ASSEGNAZIONE_APERTI).order_by("ciclo")):
        prima = out.get(a.corso_id)
        if prima is None:
            out[a.corso_id] = {"tono": "warn", "etichetta": f"Da fare entro il {a.due_date:%d/%m/%Y}" if a.due_date else "Da fare"}
        elif prima["tono"] == "bad" and a.due_date and "edizione" not in prima["etichetta"]:
            prima["etichetta"] += f" · da rifare entro il {a.due_date:%d/%m/%Y}"
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Testo dei PDF e ricerca
# ─────────────────────────────────────────────────────────────────────────────

def estrai_testo(att, *, salva: bool = True) -> bool:
    """Estrae il testo di una dispensa PDF (stessa estrazione di CN-SGI). Mai eccezioni."""
    if not att.is_pdf or not att.file:
        return False
    import os
    import tempfile
    tmp = None
    try:
        from procedure_refresh.sgi_testo import estrai
        # Lo storage privato cifra i file sul disco: si legge decifrato e si estrae da una copia temporanea.
        with att.file.open("rb") as fh:
            dati = fh.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
            out.write(dati)
            tmp = out.name
        ris = estrai(tmp)
        att.testo = ris.testo or ""
        att.offset_pagine = list(ris.offset_pagine or [])
        att.n_pagine = ris.n_pagine or None
    except Exception:
        logger.warning("Testo della dispensa %s non estratto", att.pk, exc_info=True)
        att.testo, att.offset_pagine = "", []
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    att.testo_estratto_il = timezone.now()
    if salva and att.pk:
        att.save(update_fields=["testo", "offset_pagine", "n_pagine", "testo_estratto_il"])
    return bool(att.testo)


def assicura_testi(atts, limite: int = 5) -> None:
    """Estrae il testo delle dispense PDF che non l'hanno ancora (poche per richiesta)."""
    fatti = 0
    for a in atts:
        if fatti >= limite:
            break
        if a.testo_estratto_il is None and a.is_pdf:
            estrai_testo(a)
            fatti += 1


def cerca(q: str, atts) -> list[dict]:
    """Dispense che contengono tutte le parole (titolo, corso o testo), con estratti e pagina."""
    from procedure_refresh.libreria import _estratto, _fine_parola, _pagina, _parole_query, _piega, _radice, _regex
    parole = _parole_query(q or "")
    if not parole:
        return []
    radici = [_radice(p) for p in parole]
    regex_singole = [_regex([r]) for r in radici]
    regex_tutte = _regex(radici)
    out = []
    for a in atts:
        intest = _piega(f"{a.nome_visibile} {a.corso.codice} {a.corso.titolo}")
        testo = a.testo or ""
        piegato = _piega(testo)
        if not all(rx.search(intest) or rx.search(piegato) for rx in regex_singole):
            continue
        estratti = []
        for m in regex_tutte.finditer(piegato):
            pos = m.start()
            fine = _fine_parola(piegato, pos)
            prima, trovato, dopo = _estratto(testo, pos, fine - pos)
            estratti.append({"prima": prima, "trovato": trovato, "dopo": dopo,
                             "pagina": _pagina(a.offset_pagine or [], pos, a.n_pagine, len(testo))})
            if len(estratti) >= 2:
                break
        nel_titolo = sum(1 for rx in regex_singole if rx.search(intest))
        out.append({"a": a, "estratti": estratti, "punteggio": nel_titolo * 10 + len(estratti)})
    out.sort(key=lambda r: (-r["punteggio"], r["a"].nome_visibile.casefold()))
    return out[:60]


# ─────────────────────────────────────────────────────────────────────────────
# Libreria: scaffali (tipi di corso), corsi, schede
# ─────────────────────────────────────────────────────────────────────────────

def scaffale_di(corso) -> dict:
    t = getattr(corso, "tipo", None)
    if t is None:
        return {"id": 0, "nome": "Altri corsi", "colore": COLORE_SENZA_TIPO, "sigla": "ALT"}
    return {"id": t.pk, "nome": t.nome, "colore": t.colore or COLORE_SENZA_TIPO, "sigla": t.nome[:3].upper()}


def scheda(a, *, letture=None, aperture=None, oggi=None) -> dict:
    """Dati di una dispensa nella forma del foglio CN-SGI (``_foglio.html``)."""
    oggi = oggi or timezone.localdate()
    sc = scaffale_di(a.corso)
    letta = (letture or {}).get(a.pk)
    return {
        "pk": a.pk, "a": a, "code": a.corso.codice, "title": a.nome_visibile,
        "scaffale": {"colore": sc["colore"], "sigla": sc["sigla"]},
        "rev": {"revision_code": "", "revision_date": a.created_at},
        "sezione_label": ETICHETTE.get(a.tipo, a.get_tipo_display()),
        "nuova": (oggi - timezone.localtime(a.created_at).date()).days <= GIORNI_NUOVE,
        "letta": letta, "da_leggere": a.richiedi_lettura and not letta,
        "aperture": (aperture or {}).get(a.pk, 0),
    }


def catalogo_sapere(request) -> dict | None:
    """Scheda «Corsi e dispense» nella forma dei cataloghi di Sapere, se c'è qualcosa da leggere."""
    from django.urls import reverse
    try:
        n = visibili(Contesto.da_request(request)).values("corso_id").distinct().count()
    except Exception:
        logger.warning("Catalogo «Corsi e dispense» non calcolabile", exc_info=True)
        return None
    if not n:
        return None
    return {
        "id": "corsi-dispense",
        "href": reverse("anagrafica:dispense_libreria"),
        "titolo": "Corsi e dispense",
        "descrizione": "Le dispense dei corsi di formazione, da leggere nel portale",
        "colore": "#8a3b12",
        "sigla": "FOR",
        "copertina": "",
        "totale": n,
    }
