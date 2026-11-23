"""Collegamenti dell'attività: macchina, attrezzatura, utensili, programmi CAM e CMM, FAI, incontro.

Un servizio solo sopra i modelli che c'erano già, senza un registro in più:

- macchina      → ``TaskExtraRef`` (campo ``macchina``, una riga per macchina); in
                  ``Task.extra_data`` resta la prima, per chi legge ancora quel campo;
- attrezzatura  → ``attrezzature.AttrezzaturaKickoffLink`` (catalogo: ``Attrezzatura``);
- utensile      → ``ProjectUtensile.task`` (catalogo: ``Utensile``);
- CAM, CMM      → ``ProjectTechRef.task`` (anche più di uno per attività);
- FAI           → ``ProjectTechRef.task`` (uno solo per attività);
- incontro      → il punto all'ordine del giorno con ``task_id`` (``KickoffMeeting.agenda_items``).

Le tre viste leggono da qui: la scheda dell'attività (``collegamenti``), il
Percorso (``collegamenti_per_attivita`` + ``manca``) e «Programmi e FAI»
(``registro``). Utensili e attrezzature sono solo codici a catalogo: niente
stati, niente quantità.

Una macchina già impegnata o in manutenzione nel periodo si collega lo stesso:
il conflitto è un avviso (``conflitti_macchina``), mai un blocco.
"""
from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse

from ..models import (
    KickoffMeeting,
    MeetingAgendaItem,
    MeetingStatus,
    ProgrammaFase,
    ProjectTechRef,
    ProjectUtensile,
    Task,
    TaskExtraRef,
    TaskStatus,
    TappaKickoff,
    TechRefKind,
    Utensile,
)
from . import programmi_fasi
from .fai import allinea_da_riga
from .programmi import allinea_stato_riga, sgancia
from .tappe import CAMPO_MACCHINA, _finestra, macchine_disponibili, periodo

logger = logging.getLogger(__name__)

MACCHINA, ATTREZZATURA, UTENSILE, CAM, CMM, FAI, INCONTRO = (
    "macchina", "attrezzatura", "utensile", "cam", "cmm", "fai", "incontro",
)
# nome, plurale, «si può aggiungere un codice nuovo», «ha un catalogo da riusare»
INFO = {
    MACCHINA: {"nome": "Macchina", "plurale": "Macchine", "nuovo": False, "catalogo": False},
    ATTREZZATURA: {"nome": "Attrezzatura", "plurale": "Attrezzature", "nuovo": True, "catalogo": True},
    UTENSILE: {"nome": "Utensile", "plurale": "Utensili", "nuovo": True, "catalogo": True},
    CAM: {"nome": "Programma CAM", "plurale": "Programmi CAM", "nuovo": True, "catalogo": True},
    CMM: {"nome": "Programma CMM", "plurale": "Programmi CMM", "nuovo": True, "catalogo": True},
    FAI: {"nome": "FAI", "plurale": "FAI", "nuovo": True, "catalogo": False},
    INCONTRO: {"nome": "Incontro", "plurale": "Incontri", "nuovo": False, "catalogo": False},
}
TIPI = tuple(INFO)
# Quelli che finiscono nel registro della commessa (l'incontro no: è l'ordine del giorno).
TIPI_REGISTRO = (MACCHINA, ATTREZZATURA, UTENSILE, CAM, CMM, FAI)
KIND = {CAM: TechRefKind.CAM, CMM: TechRefKind.CMM, FAI: TechRefKind.FAI}
TIPO_DI_KIND = {v: k for k, v in KIND.items()}
# Cosa si aspetta ogni tappa del Percorso dalla sua attività.
ATTESI = {
    TappaKickoff.CAM: (CAM, MACCHINA),
    TappaKickoff.CMM: (CMM,),
    TappaKickoff.MACCHINA: (MACCHINA,),
    TappaKickoff.ATTREZZATURA: (ATTREZZATURA,),
    TappaKickoff.UTENSILI: (UTENSILE,),
    TappaKickoff.FAI: (FAI,),
}
LIMITE = 12


class CollegamentoNonValido(ValueError):
    pass


# --- Lettura ----------------------------------------------------------------

def _nome_utente(user) -> str:
    return (user.get_full_name() or user.get_username()) if user is not None else ""


def _voce(tipo: str, chiave: str, codice: str, descrizione: str = "", **extra) -> dict:
    return {
        "tipo": tipo, "nome": INFO[tipo]["nome"], "chiave": chiave, "codice": codice, "descrizione": descrizione,
        "stato": "", "tono": "", "url": "", "href": "", "fasi": [], "ref": None, **extra,
    }


def _voce_ref(ref: ProjectTechRef) -> dict:
    tipo = TIPO_DI_KIND[ref.kind]
    voce = _voce(tipo, f"ref:{ref.pk}", ref.etichetta_breve if ref.is_programma else (ref.code or "da compilare"), ref=ref)
    voce["href"] = ref.open_href if ref.path else ""
    if ref.is_programma:
        voce["descrizione"] = (ref.note or "").strip().partition("\n")[0][:120]
        voce["stato"] = ref.get_fase_display()
        voce["tono"] = programmi_fasi.CLASSE.get(ref.fase, "")
        voce["fasi"] = programmi_fasi.azioni_possibili(ref)
    else:
        record = getattr(ref, "fai_record", None)
        if record is not None:
            voce["descrizione"] = record.get_tipo_display() or "FAI"
            voce["stato"] = record.stato.etichetta
            voce["tono"] = "warn" if ref.is_open else "ok"
            voce["url"] = reverse("tasks:fai_scheda", args=[record.pk])
        else:
            voce["stato"] = "Scheda da compilare"
            voce["tono"] = "warn"
            voce["url"] = f"{reverse('tasks:fai_nuovo')}?project={ref.project_id}&ref={ref.pk}"
    return voce


def _voce_utensile(riga: ProjectUtensile) -> dict:
    return _voce(UTENSILE, f"ut:{riga.pk}", riga.utensile.codice, riga.utensile.descrizione)


def _voce_attrezzatura(attrezzatura) -> dict:
    return _voce(ATTREZZATURA, f"att:{attrezzatura.pk}", attrezzatura.codice or "senza codice", attrezzatura.descrizione)


def _voce_macchina(asset) -> dict:
    return _voce(MACCHINA, f"mac:{asset.pk}", asset.asset_tag or f"#{asset.pk}", asset.name, asset=asset)


def _voce_incontro(riga: MeetingAgendaItem, project_id: int) -> dict:
    meeting = riga.meeting
    voce = _voce(
        INCONTRO, f"odg:{meeting.pk}", f"#{meeting.numero}",
        " · ".join(p for p in (meeting.titolo, f"{meeting.data:%d/%m/%Y}" if meeting.data else "") if p),
    )
    voce["stato"] = "All'ordine del giorno" if meeting.stato == MeetingStatus.PIANIFICATO else meeting.get_stato_display()
    voce["tono"] = "info" if meeting.stato == MeetingStatus.PIANIFICATO else ""
    voce["url"] = f"{reverse('tasks:project_meeting_detail', args=[project_id, meeting.pk])}#agenda-item-{riga.item_id}"
    voce["pianificato"] = meeting.stato == MeetingStatus.PIANIFICATO
    return voce


def collegamenti_per_attivita(tasks, *, incontri: bool = True, vuoti: bool = False) -> dict[int, list[dict]]:
    """I collegamenti di più attività con poche query. ``vuoti``: anche il programma ancora da inserire."""
    tasks = [t for t in tasks if t is not None and t.pk]
    ids = [t.pk for t in tasks]
    esito: dict[int, list[dict]] = {pk: [] for pk in ids}
    if not ids:
        return esito
    per_tipo: dict[int, dict[str, list[dict]]] = {pk: {} for pk in ids}

    def metti(task_id, voce):
        per_tipo[task_id].setdefault(voce["tipo"], []).append(voce)

    viste = set()
    for ref in (
        TaskExtraRef.objects.filter(task_id__in=ids, field_code=CAMPO_MACCHINA, asset__isnull=False)
        .select_related("asset").order_by("id")
    ):
        if (ref.task_id, ref.asset_id) not in viste:
            viste.add((ref.task_id, ref.asset_id))
            metti(ref.task_id, _voce_macchina(ref.asset))
    try:
        from attrezzature.models import AttrezzaturaKickoffLink

        visti = set()
        for link in (
            AttrezzaturaKickoffLink.objects.filter(task_id__in=ids).select_related("attrezzatura").order_by("id")
        ):
            if (link.task_id, link.attrezzatura_id) in visti:
                continue
            visti.add((link.task_id, link.attrezzatura_id))
            metti(link.task_id, _voce_attrezzatura(link.attrezzatura))
    except Exception:
        logger.exception("Collegamenti: attrezzature non lette")
    for riga in ProjectUtensile.objects.filter(task_id__in=ids).select_related("utensile").order_by("utensile__codice", "id"):
        metti(riga.task_id, _voce_utensile(riga))
    for ref in (
        ProjectTechRef.objects.filter(task_id__in=ids)
        .select_related("macchina", "fai_record__stato", "assigned_to", "source_meeting")
    ):
        if ref.ha_contenuto or vuoti:
            voce = _voce_ref(ref)
            voce["vuoto"] = not ref.ha_contenuto
            metti(ref.task_id, voce)
    if incontri:
        progetti = {t.pk: t.project_id for t in tasks}
        visti = set()
        for riga in (
            MeetingAgendaItem.objects.filter(task_id__in=ids)
            .exclude(meeting__stato=MeetingStatus.ANNULLATO)
            .select_related("meeting").order_by("-meeting__data", "-meeting_id", "ordine")
        ):
            if (riga.task_id, riga.meeting_id) in visti or riga.meeting.project_id != progetti.get(riga.task_id):
                continue
            visti.add((riga.task_id, riga.meeting_id))
            metti(riga.task_id, _voce_incontro(riga, riga.meeting.project_id))
    for pk in ids:
        esito[pk] = [voce for tipo in TIPI for voce in per_tipo[pk].get(tipo, [])]
    return esito


def collegamenti(task: Task) -> list[dict]:
    return collegamenti_per_attivita([task])[task.pk]


def attesi(task: Task) -> tuple[str, ...]:
    """I collegamenti che l'attività si aspetta: dalla tappa del suo tipo o da quello che «richiede»."""
    categoria = task.category if task.category_id else None
    if categoria is None:
        return ()
    if categoria.tappa in ATTESI:
        return ATTESI[categoria.tappa]
    if categoria.richiede in TIPO_DI_KIND:
        return (TIPO_DI_KIND[categoria.richiede],)
    return ()


def manca(task: Task, voci: list[dict] | None = None) -> list[str]:
    """Tipi attesi e non ancora collegati. Un'attività chiusa o annullata non aspetta più niente."""
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELED):
        return []
    voci = collegamenti(task) if voci is None else voci
    presenti = {v["tipo"] for v in voci if not v.get("vuoto")}
    return [tipo for tipo in attesi(task) if tipo not in presenti]


def manca_testo(tipi: list[str]) -> str:
    return "Manca: " + ", ".join(INFO[t]["nome"][0].lower() + INFO[t]["nome"][1:] if t != FAI else "FAI" for t in tipi) if tipi else ""


def _quando(testo: str) -> str:
    """«2026-11-24 -> 2026-11-28» del controllo asset, scritto «24/11–28/11»."""
    giorni = []
    for pezzo in (testo or "").split("->"):
        try:
            giorni.append(date.fromisoformat(pezzo.strip()))
        except ValueError:
            return (testo or "").strip()
    return "–".join(f"{g:%d/%m}" for g in giorni)


def conflitti_macchina(asset, inizio, fine, *, escludi_task_id=None, visibili=None) -> list[dict]:
    """Cosa impegna la macchina nel periodo: altre attività, ordini di lavoro, verifiche, ticket, carichi.

    Stesso controllo di sempre (``asset_conflicts._asset_availability_report``), letto come
    avviso: non blocca niente. ``visibili`` = id delle attività che chi guarda può vedere;
    delle altre si dice solo che ci sono, senza titolo (``None`` = nessun titolo altrui).
    """
    try:
        from .asset_conflicts import _asset_availability_report

        report = _asset_availability_report(
            asset, inizio, fine, exclude_task_id=escludi_task_id,
            scope_task_ids=set() if visibili is None else visibili,
        )
    except Exception:
        logger.exception("Collegamenti: disponibilità macchina non letta (asset=%s)", asset.pk)
        return []
    return [
        {
            "titolo": str(c.get("title") or "").replace("Attivita gia' assegnata", "Attività già assegnata"),
            "quando": _quando(c.get("when", "")),
            "grave": c.get("severity") == "block",
            "url": c.get("url", ""),
        }
        for c in report.get("conflicts") or []
    ]


def stato_da_conflitti(conflitti: list[dict]) -> tuple[str, str]:
    """(etichetta, tono) della macchina nel periodo."""
    if any(c["grave"] for c in conflitti):
        return "Già impegnata nel periodo", "danger"
    if conflitti:
        return "Da verificare nel periodo", "warn"
    return "Libera", "ok"


def avviso_macchina(conflitti: list[dict], inizio=None, fine=None) -> str:
    """Una riga che dice cosa la impegna e quando. Vuota se la macchina è libera."""
    if not conflitti:
        return ""
    voci = [c["titolo"] + (f" ({c['quando']})" if c["quando"] else "") for c in conflitti[:3]]
    if len(conflitti) > 3:
        voci.append(f"+{len(conflitti) - 3}")
    periodo_testo = f"Dal {inizio:%d/%m} al {fine:%d/%m}: " if inizio and fine else ""
    return periodo_testo + " · ".join(voci)


def stato_macchina(asset, inizio, fine, *, escludi_task_id=None) -> tuple[str, str]:
    """Disponibilità in sola lettura, senza titoli di altre commesse: (etichetta, tono)."""
    return stato_da_conflitti(conflitti_macchina(asset, inizio, fine, escludi_task_id=escludi_task_id))


def _segna_conflitti(voce: dict, task: Task, visibili) -> None:
    inizio, fine = _finestra(task)
    conflitti = conflitti_macchina(voce["asset"], inizio, fine, escludi_task_id=task.pk, visibili=visibili)
    voce["conflitti"] = conflitti
    voce["stato"], voce["tono"] = stato_da_conflitti(conflitti)
    voce["avviso"] = avviso_macchina(conflitti, inizio, fine)


def riquadro(task: Task, *, con_stato_macchina: bool = True, visibili=None) -> dict:
    """Quello che serve al riquadro «Collegamenti» della scheda: voci, cosa manca, tipi attesi."""
    # Il FAI richiesto e non ancora compilato resta in elenco: da lì si apre la scheda FAI.
    voci = [
        v for v in collegamenti_per_attivita([task], vuoti=True)[task.pk]
        if not v.get("vuoto") or v["tipo"] == FAI
    ]
    if con_stato_macchina and task.status not in (TaskStatus.DONE, TaskStatus.CANCELED):
        for voce in voci:
            if voce["tipo"] == MACCHINA:
                _segna_conflitti(voce, task, visibili)
    mancanti = manca(task, voci)
    return {
        "voci": voci,
        "manca": mancanti,
        "manca_testo": manca_testo(mancanti),
        "tipi": [
            {"codice": tipo, "nome": INFO[tipo]["nome"], "serve": tipo in mancanti}
            for tipo in TIPI
        ],
    }


# --- Catalogo ----------------------------------------------------------------

def _commesse(n: int) -> str:
    return f"in {n} commess{'a' if n == 1 else 'e'}" if n else ""


def _spezza(testo: str) -> tuple[str, str]:
    """«codice descrizione»: la prima parola è il codice."""
    codice, _, descrizione = (testo or "").strip().partition(" ")
    return codice.strip(), descrizione.strip()


def cerca(project, tipo: str, q: str = "", *, task: Task | None = None, progetti_visibili=None) -> dict:
    """Voci del catalogo che corrispondono, più se il codice scritto è nuovo (``nuovo``)."""
    if tipo not in INFO:
        raise CollegamentoNonValido("Tipo di collegamento non valido.")
    q = (q or "").strip()
    codice, _descrizione = _spezza(q)
    risultati: list[dict] = []
    esiste = False

    if tipo == MACCHINA:
        qs = macchine_disponibili()
        if q:
            qs = qs.filter(Q(asset_tag__icontains=q) | Q(name__icontains=q))
        inizio, fine = _finestra(task) if task is not None else periodo(None, None)
        for asset in qs[:8]:
            stato, tono = stato_macchina(asset, inizio, fine, escludi_task_id=task.pk if task is not None else None)
            risultati.append({"id": asset.pk, "codice": asset.asset_tag or f"#{asset.pk}", "descrizione": asset.name, "stato": stato, "tono": tono, "usi": ""})
    elif tipo == ATTREZZATURA:
        from attrezzature.models import Attrezzatura

        qs = Attrezzatura.objects.exclude(codice="")
        if q:
            qs = qs.filter(Q(codice__icontains=codice or q) | Q(descrizione__icontains=q) | Q(part_number__icontains=q))
        elif project.part_number:
            # Senza testo: prima quelle dello stesso P/N.
            stesse = qs.filter(part_number__iexact=project.part_number)
            qs = stesse if stesse.exists() else qs
        for a in qs.annotate(usi=Count("kickoff_links__project", distinct=True)).order_by("codice", "id")[:LIMITE]:
            risultati.append({"id": a.pk, "codice": a.codice, "descrizione": a.descrizione, "stato": "", "tono": "", "usi": _commesse(a.usi)})
        esiste = bool(codice) and Attrezzatura.objects.filter(codice__iexact=codice).exists()
    elif tipo == UTENSILE:
        qs = Utensile.objects.filter(attivo=True)
        if q:
            qs = qs.filter(Q(codice__icontains=codice or q) | Q(descrizione__icontains=q))
        for u in qs.annotate(usi=Count("commesse__project", distinct=True)).order_by("codice")[:LIMITE]:
            risultati.append({"id": u.pk, "codice": u.codice, "descrizione": u.descrizione, "stato": "", "tono": "", "usi": _commesse(u.usi)})
        esiste = bool(codice) and Utensile.objects.filter(codice__iexact=codice).exists()
    elif tipo in (CAM, CMM):
        visibili = Q(project=project)
        if progetti_visibili is not None:
            visibili |= Q(project__in=progetti_visibili)
        qs = ProjectTechRef.objects.filter(visibili, kind=KIND[tipo]).exclude(code="").select_related("project", "task")
        if q:
            qs = qs.filter(Q(code__icontains=codice or q) | Q(note__icontains=q) | Q(project__part_number__icontains=q))
        gruppi: dict[str, dict] = {}
        for ref in qs.order_by("-id")[:200]:
            chiave = ref.code.lower()
            gruppo = gruppi.setdefault(chiave, {"ref": ref, "progetti": set()})
            gruppo["progetti"].add(ref.project_id)
            # Di questa commessa viene prima; fra quelle, la riga ancora senza attività.
            attuale = gruppo["ref"]
            if ref.project_id == project.pk and (attuale.project_id != project.pk or (attuale.task_id and not ref.task_id)):
                gruppo["ref"] = ref
        for gruppo in list(gruppi.values())[:LIMITE]:
            ref = gruppo["ref"]
            if task is not None and ref.task_id == task.pk:
                continue
            altrove = ref.project_id == project.pk and ref.task_id
            risultati.append({
                "id": ref.pk, "codice": ref.etichetta_breve,
                "descrizione": (ref.note or "").strip().partition("\n")[0][:120] or (
                    "" if ref.project_id == project.pk else f"da {ref.project.part_number or ref.project.name}"
                ),
                "stato": f"già su «{ref.task.title[:40]}»" if altrove else ref.get_fase_display(),
                "tono": "" if altrove else programmi_fasi.CLASSE.get(ref.fase, ""),
                "usi": _commesse(len(gruppo["progetti"])),
                "bloccato": bool(altrove),
            })
        esiste = bool(codice) and codice.lower() in gruppi
        if codice and not esiste:
            esiste = ProjectTechRef.objects.filter(visibili, kind=KIND[tipo], code__iexact=codice).exists()
    elif tipo == FAI:
        qs = ProjectTechRef.objects.filter(project=project, kind=TechRefKind.FAI, task__isnull=True).select_related("fai_record__stato")
        if q:
            qs = qs.filter(code__icontains=codice or q)
        for ref in qs.order_by("-id")[:LIMITE]:
            voce = _voce_ref(ref)
            risultati.append({"id": ref.pk, "codice": voce["codice"], "descrizione": voce["descrizione"] or "senza attività", "stato": voce["stato"], "tono": voce["tono"], "usi": ""})
        esiste = bool(codice) and ProjectTechRef.objects.filter(project=project, kind=TechRefKind.FAI, code__iexact=codice).exists()
    elif tipo == INCONTRO:
        gia = set()
        if task is not None:
            gia = set(MeetingAgendaItem.objects.filter(task=task).values_list("meeting_id", flat=True))
        for m in KickoffMeeting.objects.filter(project=project, stato=MeetingStatus.PIANIFICATO).order_by("data", "numero"):
            if m.pk in gia:
                continue
            testo = f"#{m.numero} {m.titolo}".lower()
            if q and q.lower() not in testo:
                continue
            risultati.append({
                "id": m.pk, "codice": f"#{m.numero}",
                "descrizione": " · ".join(p for p in (m.titolo, f"{m.data:%d/%m/%Y}" if m.data else "") if p),
                "stato": "", "tono": "", "usi": "",
            })

    info = INFO[tipo]
    vuoto = {
        MACCHINA: "Nessuna macchina con questo nome.",
        FAI: "Scrivi il numero del FAI da aprire.",
        INCONTRO: "Nessun incontro pianificato per questa commessa.",
    }.get(tipo, "Scrivi il codice: se è nuovo entra in catalogo e lo ritrovi nelle prossime commesse.")
    return {
        "tipo": tipo,
        "risultati": risultati,
        "nuovo": bool(info["nuovo"] and len(codice) > 1 and not esiste),
        "nuovo_testo": q,
        "nuovo_etichetta": "Aggiungi e collega" if info["catalogo"] else "Apri nuovo FAI",
        "nuovo_frase": "non è in catalogo" if info["catalogo"] else "non c'è in questa commessa",
        "vuoto": vuoto,
    }


# --- Scrittura ---------------------------------------------------------------

def _richiede_progetto(task: Task):
    if not task.project_id:
        raise CollegamentoNonValido("I collegamenti valgono per le attività di una commessa.")
    return task.project


def _macchine(task: Task) -> list[int]:
    """Id delle macchine dell'attività, nell'ordine in cui sono state collegate."""
    ids: list[int] = []
    for asset_id in (
        TaskExtraRef.objects.filter(task=task, field_code=CAMPO_MACCHINA, asset__isnull=False)
        .order_by("id").values_list("asset_id", flat=True)
    ):
        if asset_id not in ids:
            ids.append(asset_id)
    return ids


def _ricorda_prima_macchina(task: Task) -> None:
    """``extra_data["macchina"]`` resta la prima macchina: lo leggono ancora il form e i campi del tipo."""
    ids = _macchine(task)
    dati = dict(task.extra_data or {})
    if ids:
        dati[CAMPO_MACCHINA] = ids[0]
    else:
        dati.pop(CAMPO_MACCHINA, None)
    task.extra_data = dati
    Task.objects.filter(pk=task.pk).update(extra_data=dati)


def _collega_macchina(task: Task, asset) -> dict:
    """Aggiunge la macchina alle altre. Un conflitto nel periodo non impedisce il collegamento: è un avviso."""
    if not TaskExtraRef.objects.filter(task=task, field_code=CAMPO_MACCHINA, asset=asset).exists():
        TaskExtraRef.objects.create(task=task, field_code=CAMPO_MACCHINA, asset=asset)
    _ricorda_prima_macchina(task)
    # I programmi dell'attività girano su quella macchina, se non ne avevano già una.
    ProjectTechRef.objects.filter(task=task, macchina__isnull=True, kind__in=[TechRefKind.CAM, TechRefKind.CMM]).update(macchina=asset)
    return _voce_macchina(asset)


def _scollega_macchina(task: Task, asset_id: int) -> None:
    TaskExtraRef.objects.filter(task=task, field_code=CAMPO_MACCHINA, asset_id=asset_id).delete()
    _ricorda_prima_macchina(task)


def _collega_utensile(task: Task, utensile: Utensile, user) -> dict:
    project = task.project
    riga = ProjectUtensile.objects.filter(project=project, utensile=utensile, task=task).first()
    if riga is None:
        # Una riga della commessa rimasta senza attività (vecchio Percorso) diventa questa, senza doppioni.
        riga = ProjectUtensile.objects.filter(project=project, utensile=utensile, task__isnull=True).order_by("id").first()
        if riga is not None:
            riga.task = task
            riga.save(update_fields=["task", "updated_at"])
        else:
            riga = ProjectUtensile.objects.create(
                project=project, utensile=utensile, task=task,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
    return _voce_utensile(riga)


def _collega_attrezzatura(task: Task, attrezzatura, user) -> dict:
    from attrezzature.models import AttrezzaturaKickoffLink, AttrezzaturaKickoffRelationType
    from attrezzature.services.kickoff_integration import upsert_kickoff_link

    if not AttrezzaturaKickoffLink.objects.filter(task=task, attrezzatura=attrezzatura).exists():
        libero = AttrezzaturaKickoffLink.objects.filter(project=task.project, attrezzatura=attrezzatura, task__isnull=True).order_by("id").first()
        if libero is not None:
            libero.task = task
            libero.save(update_fields=["task", "updated_at"])
        else:
            upsert_kickoff_link(
                attrezzatura=attrezzatura, kickoff_ref=task.project_id, kickoff_activity_ref=task.pk,
                relationship_type=AttrezzaturaKickoffRelationType.LINKED_EXISTING,
                user=user if getattr(user, "is_authenticated", False) else None,
            )
    return _voce_attrezzatura(attrezzatura)


def _nuova_attrezzatura(project, codice: str, descrizione: str, user):
    """Codice nuovo: entra nel catalogo attrezzature così com'è, senza richieste né verifiche."""
    from attrezzature.models import Attrezzatura, AttrezzaturaPartNumber
    from attrezzature.services.kickoff_integration import normalize_part_number

    autore = user if getattr(user, "is_authenticated", False) else None
    pn = normalize_part_number(project.part_number or "")
    attrezzatura = Attrezzatura.objects.create(
        codice=codice[:80], descrizione=descrizione[:255], part_number=pn,
        origine_import="kickoff", created_by=autore, updated_by=autore,
    )
    if pn:
        AttrezzaturaPartNumber.objects.get_or_create(attrezzatura=attrezzatura, part_number=pn, defaults={"fonte": "kickoff"})
    return attrezzatura


def _collega_ref(task: Task, tipo: str, user, *, sorgente: ProjectTechRef | None = None, codice: str = "", descrizione: str = "") -> dict:
    """Programma o FAI sull'attività. I programmi possono essere più d'uno, il FAI è uno solo."""
    kind = KIND[tipo]
    nome = INFO[tipo]["nome"]
    project = task.project
    righe = list(ProjectTechRef.objects.filter(task=task).order_by("id"))
    if sorgente is not None:
        gia = next((r for r in righe if r.pk == sorgente.pk), None)
        if gia is not None:
            return _voce_ref(gia)
    # La riga «da inserire» nata con l'attività è il posto del primo programma.
    attuale = next((r for r in righe if r.kind == kind and not r.ha_contenuto), None)
    if tipo == FAI:
        fai = next((r for r in righe if r.kind == kind and r.ha_contenuto), None)
        if fai is not None:
            raise CollegamentoNonValido(f"Questa attività ha già «{fai.label}»: il FAI è uno solo per attività.")
    else:
        codice_nuovo = (sorgente.code if sorgente is not None else codice).strip().lower()
        if codice_nuovo and any(r.kind == kind and r.code.lower() == codice_nuovo for r in righe):
            raise CollegamentoNonValido(f"{nome} {codice_nuovo.upper()} è già collegato a questa attività.")
    richiesto = task.category.richiede if task.category_id else ""
    if richiesto and richiesto != kind:
        raise CollegamentoNonValido(
            f"Un'attività di tipo «{task.category.name}» produce {TechRefKind(richiesto).label}: per {nome} serve un'altra attività."
        )
    if task.status == TaskStatus.CANCELED:
        raise CollegamentoNonValido("L'attività è annullata.")
    autore = user if getattr(user, "is_authenticated", False) else None

    if sorgente is not None and sorgente.project_id == project.pk:
        if sorgente.task_id and sorgente.task_id != task.pk:
            raise CollegamentoNonValido(f"«{sorgente.label}» è già collegato a «{sorgente.task.title}».")
        if attuale is not None:
            sgancia(attuale)
        ref = sorgente
    else:
        ref = attuale or ProjectTechRef(project=project, created_by=autore)
        ref.kind = kind
        if sorgente is not None:
            # Programma già usato in un'altra commessa: stesso codice e stessa cartella, qui riparte la sua vita.
            ref.code, ref.path, ref.revisione = sorgente.code, sorgente.path, sorgente.revisione
            ref.macchina_id = ref.macchina_id or sorgente.macchina_id
            ref.note = ref.note or sorgente.note
        else:
            ref.code = codice[:120]
            if descrizione and not ref.note:
                ref.note = descrizione
        if ref.pk and ref.is_programma and ref.code and ref.fase == ProgrammaFase.DA_SCRIVERE:
            ref.fase = ProgrammaFase.IN_SCRITTURA
            ref.revisione = ref.revisione or "A"
    ref.task = task
    ref.assigned_to_id = task.assigned_to_id
    ref.due_date = task.due_date or ref.due_date
    if ref.is_programma and ref.macchina_id is None:
        macchina = TaskExtraRef.objects.filter(task=task, field_code=CAMPO_MACCHINA, asset__isnull=False).order_by("id").first()
        if macchina is not None:
            ref.macchina_id = macchina.asset_id
    ref.save()
    if ref.is_programma:
        programmi_fasi.registra(ref, user, "Collegato all'attività")
    allinea_da_riga(ref)
    allinea_stato_riga(ref, user)
    if ref.is_programma:
        programmi_fasi.chiudi_se_tutti_validati(task, user)
    return _voce_ref(ref)


def _scollega_ref(task: Task, ref: ProjectTechRef, user) -> None:
    """Il programma resta nella commessa «senza attività»; tolto l'ultimo, se il tipo lo richiede torna la riga da inserire."""
    kind = ref.kind
    era_programma = ref.is_programma
    sgancia(ref)
    richiesto = task.category.richiede if task.category_id else ""
    if (
        richiesto == kind and task.status != TaskStatus.CANCELED
        and not ProjectTechRef.objects.filter(task=task, kind=kind).exists()
    ):
        ProjectTechRef.objects.create(
            project_id=task.project_id, kind=kind, task=task, assigned_to_id=task.assigned_to_id, due_date=task.due_date,
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
    elif era_programma:
        # Tolto quello ancora in lavorazione, se gli altri sono tutti validati l'attività è fatta.
        programmi_fasi.chiudi_se_tutti_validati(task, user)


def porta_all_ordine_del_giorno(task: Task, meeting: KickoffMeeting) -> tuple[dict, bool]:
    """Il punto dell'incontro collegato all'attività: lo crea, o riusa quello che c'è già. (punto, creato)."""
    if meeting.project_id != task.project_id:
        raise CollegamentoNonValido("L'incontro è di un'altra commessa.")
    if meeting.stato != MeetingStatus.PIANIFICATO:
        raise CollegamentoNonValido("Si può portare all'ordine del giorno solo di un incontro pianificato.")
    items = [item for item in (meeting.agenda_items or []) if isinstance(item, dict)]
    for item in items:
        if item.get("task_id") == task.pk:
            return item, False
    responsabile = task.assigned_to if task.assigned_to_id else None
    item = {
        "id": uuid4().hex,
        "titolo": task.title[:200],
        "nota": "",
        "task_id": task.pk,
        "task_label": task.title[:200],
        "issue_id": None,
        "action_id": None,
        # Aggiunto prima dell'incontro: è un punto convocato come gli altri.
        "source": "",
        "locked": False,
        "responsabile_id": responsabile.pk if responsabile else None,
        "responsabile_label": _nome_utente(responsabile)[:150],
        "durata_minuti": None,
        "tempo_effettivo_minuti": None,
        "custom_fields": [],
        "done": False,
    }
    items.append(item)
    meeting.agenda_items = items
    meeting.save(update_fields=["agenda_items", "updated_at"])
    return item, True


def togli_dall_ordine_del_giorno(task: Task, meeting: KickoffMeeting) -> int:
    if meeting.project_id != task.project_id or meeting.stato != MeetingStatus.PIANIFICATO:
        raise CollegamentoNonValido("Il punto si toglie solo da un incontro pianificato.")
    items = [item for item in (meeting.agenda_items or []) if isinstance(item, dict)]
    restano = [item for item in items if item.get("task_id") != task.pk or item.get("locked")]
    tolti = len(items) - len(restano)
    if tolti:
        meeting.agenda_items = restano
        meeting.save(update_fields=["agenda_items", "updated_at"])
    return tolti


@transaction.atomic
def collega(task: Task, tipo: str, ident, user, *, progetti_visibili=None) -> dict:
    """Collega una voce che esiste già (dal catalogo o dalla commessa). Torna la voce collegata."""
    project = _richiede_progetto(task)
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        raise CollegamentoNonValido("Voce non valida.") from None
    if tipo == MACCHINA:
        asset = macchine_disponibili().filter(pk=ident).first()
        if asset is None:
            raise CollegamentoNonValido("Macchina non trovata.")
        return _collega_macchina(task, asset)
    if tipo == ATTREZZATURA:
        from attrezzature.models import Attrezzatura

        attrezzatura = Attrezzatura.objects.filter(pk=ident).first()
        if attrezzatura is None:
            raise CollegamentoNonValido("Attrezzatura non trovata.")
        return _collega_attrezzatura(task, attrezzatura, user)
    if tipo == UTENSILE:
        utensile = Utensile.objects.filter(pk=ident).first()
        if utensile is None:
            raise CollegamentoNonValido("Utensile non trovato.")
        return _collega_utensile(task, utensile, user)
    if tipo in KIND:
        visibili = Q(project=project)
        if tipo != FAI and progetti_visibili is not None:
            visibili |= Q(project__in=progetti_visibili)
        sorgente = ProjectTechRef.objects.filter(visibili, pk=ident, kind=KIND[tipo]).select_related("task").first()
        if sorgente is None:
            raise CollegamentoNonValido(f"{INFO[tipo]['nome']} non trovato.")
        return _collega_ref(task, tipo, user, sorgente=sorgente)
    if tipo == INCONTRO:
        meeting = KickoffMeeting.objects.filter(pk=ident, project=project).first()
        if meeting is None:
            raise CollegamentoNonValido("Incontro non trovato.")
        item, _creato = porta_all_ordine_del_giorno(task, meeting)
        riga = MeetingAgendaItem.objects.filter(meeting=meeting, item_id=item["id"]).select_related("meeting").first()
        return _voce_incontro(riga, project.pk)
    raise CollegamentoNonValido("Tipo di collegamento non valido.")


@transaction.atomic
def aggiungi(task: Task, tipo: str, testo: str, user, *, progetti_visibili=None) -> tuple[dict, bool]:
    """«codice descrizione» scritto a mano: se il codice è in catalogo si collega, altrimenti ci entra. (voce, nuovo)."""
    project = _richiede_progetto(task)
    if tipo not in INFO or not INFO[tipo]["nuovo"]:
        raise CollegamentoNonValido("Qui si sceglie fra le voci esistenti.")
    codice, descrizione = _spezza(testo)
    if len(codice) < 2:
        raise CollegamentoNonValido("Scrivi il codice.")
    if tipo == UTENSILE:
        utensile = Utensile.objects.filter(codice__iexact=codice[:80]).first()
        nuovo = utensile is None
        if nuovo:
            utensile = Utensile.objects.create(codice=codice[:80], descrizione=descrizione[:255])
        return _collega_utensile(task, utensile, user), nuovo
    if tipo == ATTREZZATURA:
        from attrezzature.models import Attrezzatura

        attrezzatura = Attrezzatura.objects.filter(codice__iexact=codice[:80]).order_by("id").first()
        nuovo = attrezzatura is None
        if nuovo:
            attrezzatura = _nuova_attrezzatura(project, codice, descrizione, user)
        return _collega_attrezzatura(task, attrezzatura, user), nuovo
    # Programmi e FAI: prima la riga con quel codice che la commessa ha già, poi il catalogo.
    kind = KIND[tipo]
    sorgente = (
        ProjectTechRef.objects.filter(project=project, kind=kind, code__iexact=codice[:120])
        .order_by("task_id", "id").select_related("task").first()
    )
    if sorgente is None and tipo != FAI and progetti_visibili is not None:
        sorgente = ProjectTechRef.objects.filter(project__in=progetti_visibili, kind=kind, code__iexact=codice[:120]).order_by("-id").first()
    if sorgente is not None:
        return _collega_ref(task, tipo, user, sorgente=sorgente), False
    return _collega_ref(task, tipo, user, codice=codice, descrizione=descrizione), True


@transaction.atomic
def scollega(task: Task, chiave: str, user) -> dict:
    """Toglie il collegamento; il codice resta a catalogo. Torna tipo e codice per il messaggio."""
    _richiede_progetto(task)
    prefisso, _, valore = (chiave or "").partition(":")
    if not valore.isdigit():
        raise CollegamentoNonValido("Collegamento non valido.")
    ident = int(valore)
    if prefisso == "mac":
        ref = TaskExtraRef.objects.filter(task=task, field_code=CAMPO_MACCHINA, asset_id=ident).select_related("asset").first()
        if ref is None:
            raise CollegamentoNonValido("Collegamento non trovato.")
        codice = ref.asset.asset_tag
        _scollega_macchina(task, ident)
        return {"tipo": MACCHINA, "codice": codice}
    if prefisso == "att":
        from attrezzature.models import AttrezzaturaKickoffLink

        link = AttrezzaturaKickoffLink.objects.filter(task=task, attrezzatura_id=ident).select_related("attrezzatura")
        primo = link.first()
        if primo is None:
            raise CollegamentoNonValido("Collegamento non trovato.")
        codice = primo.attrezzatura.codice
        link.delete()
        return {"tipo": ATTREZZATURA, "codice": codice}
    if prefisso == "ut":
        riga = ProjectUtensile.objects.filter(pk=ident, task=task).select_related("utensile").first()
        if riga is None:
            raise CollegamentoNonValido("Collegamento non trovato.")
        codice = riga.utensile.codice
        riga.delete()
        return {"tipo": UTENSILE, "codice": codice}
    if prefisso == "ref":
        ref = ProjectTechRef.objects.filter(pk=ident, task=task).first()
        if ref is None:
            raise CollegamentoNonValido("Collegamento non trovato.")
        esito = {"tipo": TIPO_DI_KIND[ref.kind], "codice": ref.code}
        _scollega_ref(task, ref, user)
        return esito
    if prefisso == "odg":
        meeting = KickoffMeeting.objects.filter(pk=ident, project_id=task.project_id).first()
        if meeting is None:
            raise CollegamentoNonValido("Incontro non trovato.")
        if not togli_dall_ordine_del_giorno(task, meeting):
            raise CollegamentoNonValido("Questo punto è fissato nell'ordine del giorno: si toglie dall'incontro.")
        return {"tipo": INCONTRO, "codice": f"#{meeting.numero}"}
    raise CollegamentoNonValido("Collegamento non valido.")


def aggiorna_programma(ref: ProjectTechRef, user, *, codice: str, percorso: str) -> None:
    """Codice e cartella del programma (o numero del FAI) corretti dal riquadro."""
    from ..tech_paths import normalizza_percorso

    try:
        path = normalizza_percorso(percorso)
    except ValueError as exc:
        raise CollegamentoNonValido(str(exc)) from None
    if len(path) > 500:
        raise CollegamentoNonValido("Il percorso è troppo lungo: massimo 500 caratteri.")
    codice = (codice or "").strip()[:120]
    if not codice and not path:
        raise CollegamentoNonValido("Scrivi il codice o la cartella: per toglierlo usa ×.")
    ref.code, ref.path = codice, path
    ref.save(update_fields=["code", "path", "updated_at"])
    if ref.is_programma and ref.code and ref.fase == ProgrammaFase.DA_SCRIVERE:
        ref.fase = ProgrammaFase.IN_SCRITTURA
        ref.revisione = ref.revisione or "A"
        ref.save(update_fields=["fase", "revisione", "updated_at"])
        programmi_fasi.registra(ref, user, "Codice inserito")
    allinea_da_riga(ref)
    allinea_stato_riga(ref, user)


def applica_in_attesa(task: Task, voci, user, *, progetti_visibili=None, incontro: bool = True) -> list[str]:
    """Collegamenti scelti nel form prima che l'attività esistesse. Torna gli avvisi di quelli non riusciti."""
    avvisi: list[str] = []
    for voce in voci if isinstance(voci, list) else []:
        if not isinstance(voce, dict):
            continue
        tipo = str(voce.get("tipo") or "")
        if tipo not in INFO or (tipo == INCONTRO and not incontro):
            continue
        try:
            if voce.get("id"):
                collega(task, tipo, voce.get("id"), user, progetti_visibili=progetti_visibili)
            elif voce.get("testo"):
                aggiungi(task, tipo, str(voce.get("testo"))[:400], user, progetti_visibili=progetti_visibili)
        except CollegamentoNonValido as exc:
            avvisi.append(f"{INFO[tipo]['nome']}: {exc}")
    return avvisi


# --- Registro della commessa -------------------------------------------------

def collega_orfano(task: Task, chiave: str, user) -> dict:
    """Una voce della commessa rimasta senza attività (FAI, programma, utensile, attrezzatura) passa a questa."""
    project = _richiede_progetto(task)
    prefisso, _, valore = (chiave or "").partition(":")
    if not valore.isdigit():
        raise CollegamentoNonValido("Voce non valida.") from None
    ident = int(valore)
    if prefisso == "ref":
        ref = ProjectTechRef.objects.filter(pk=ident, project=project, task__isnull=True).first()
        if ref is None:
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        return collega(task, TIPO_DI_KIND[ref.kind], ref.pk, user)
    if prefisso == "ut":
        riga = ProjectUtensile.objects.filter(pk=ident, project=project, task__isnull=True).first()
        if riga is None:
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        return collega(task, UTENSILE, riga.utensile_id, user)
    if prefisso == "att":
        from attrezzature.models import AttrezzaturaKickoffLink

        if not AttrezzaturaKickoffLink.objects.filter(project=project, attrezzatura_id=ident, task__isnull=True).exists():
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        return collega(task, ATTREZZATURA, ident, user)
    raise CollegamentoNonValido("Voce non valida.")


def elimina_orfano(project, chiave: str) -> dict:
    """Toglie dalla commessa una voce senza attività. Il codice resta a catalogo; un FAI con la scheda non si tocca."""
    prefisso, _, valore = (chiave or "").partition(":")
    if not valore.isdigit():
        raise CollegamentoNonValido("Voce non valida.") from None
    ident = int(valore)
    if prefisso == "ref":
        ref = ProjectTechRef.objects.filter(pk=ident, project=project, task__isnull=True).first()
        if ref is None:
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        if getattr(ref, "fai_record", None) is not None:
            raise CollegamentoNonValido("Questo FAI ha la sua scheda: si gestisce dal Registro FAI.")
        esito = {"tipo": TIPO_DI_KIND[ref.kind], "codice": ref.code}
        ref.delete()
        return esito
    if prefisso == "ut":
        riga = ProjectUtensile.objects.filter(pk=ident, project=project, task__isnull=True).select_related("utensile").first()
        if riga is None:
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        esito = {"tipo": UTENSILE, "codice": riga.utensile.codice}
        riga.delete()
        return esito
    if prefisso == "att":
        from attrezzature.models import AttrezzaturaKickoffLink

        link = AttrezzaturaKickoffLink.objects.filter(project=project, attrezzatura_id=ident, task__isnull=True).select_related("attrezzatura")
        primo = link.first()
        if primo is None:
            raise CollegamentoNonValido("Voce non trovata fra quelle senza attività.")
        esito = {"tipo": ATTREZZATURA, "codice": primo.attrezzatura.codice}
        link.delete()
        return esito
    raise CollegamentoNonValido("Voce non valida.")


FILTRI = (
    ("tutti", "Tutti", TIPI_REGISTRO),
    ("programmi", "Programmi", (CAM, CMM)),
    (FAI, "FAI", (FAI,)),
    (MACCHINA, "Macchine", (MACCHINA,)),
    (ATTREZZATURA, "Attrezzature", (ATTREZZATURA,)),
    (UTENSILE, "Utensili", (UTENSILE,)),
)


def registro(project, *, visibili=None) -> dict:
    """Una riga per collegamento delle attività della commessa, più le voci rimaste senza attività.

    Sulla riga di una macchina resta l'avviso finché nel periodo dell'attività (aperta) c'è un conflitto.
    """
    attivita = list(
        Task.objects.filter(project=project).exclude(status=TaskStatus.CANCELED)
        .select_related("assigned_to", "category").order_by("id")
    )
    per_attivita = collegamenti_per_attivita(attivita, incontri=False, vuoti=True)
    righe: list[dict] = []
    for task in attivita:
        for voce in per_attivita[task.pk]:
            if voce["tipo"] == MACCHINA and task.status != TaskStatus.DONE:
                _segna_conflitti(voce, task, visibili)
                if not voce["conflitti"]:
                    voce["stato"], voce["tono"] = "", ""
            righe.append({**voce, "task": task, "responsabile": _nome_utente(task.assigned_to) if task.assigned_to_id else ""})
    # Senza attività: FAI e programmi della commessa, utensili e attrezzature del vecchio Percorso.
    for ref in (
        ProjectTechRef.objects.filter(project=project, task__isnull=True)
        .select_related("macchina", "fai_record__stato", "assigned_to", "source_meeting").order_by("kind", "id")
    ):
        voce = _voce_ref(ref)
        voce["vuoto"] = not ref.ha_contenuto
        righe.append({**voce, "task": None, "responsabile": _nome_utente(ref.assigned_to) if ref.assigned_to_id else ""})
    for riga in ProjectUtensile.objects.filter(project=project, task__isnull=True).select_related("utensile").order_by("utensile__codice", "id"):
        righe.append({**_voce_utensile(riga), "task": None, "responsabile": ""})
    try:
        from attrezzature.models import AttrezzaturaKickoffLink

        visti = set()
        for link in AttrezzaturaKickoffLink.objects.filter(project=project, task__isnull=True).select_related("attrezzatura").order_by("id"):
            if link.attrezzatura_id in visti:
                continue
            visti.add(link.attrezzatura_id)
            righe.append({**_voce_attrezzatura(link.attrezzatura), "task": None, "responsabile": ""})
    except Exception:
        logger.exception("Registro collegamenti: attrezzature non lette")
    ordine = {tipo: i for i, tipo in enumerate(TIPI_REGISTRO)}
    righe.sort(key=lambda r: (ordine.get(r["tipo"], 99), r["task"] is None, (r["codice"] or "").lower()))
    filtri = [
        {"codice": codice, "nome": nome, "tipi": " ".join(tipi), "conta": sum(1 for r in righe if r["tipo"] in tipi)}
        for codice, nome, tipi in FILTRI
    ]
    return {"righe": righe, "filtri": filtri, "attivita": attivita}
