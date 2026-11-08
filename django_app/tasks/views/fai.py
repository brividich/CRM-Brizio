"""Registro FAI: stessi dati del file «Situazione FAI-ISIR» (MT CN 15 §5.10), con la regola."""
from __future__ import annotations

from types import SimpleNamespace

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from urllib.parse import urlencode

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core import ordini_produzione
from produzione import nuovo_op
from core.audit import log_action
from core.csv_export import csv_download_response
from core.paginazione import pagina_elenco

from ..access import can_manage_project, has_task_permission, scoped_projects_queryset, task_permissions_required
from ..fai_regole import aggiungi_mesi
from ..identity import normalize_part_number
from ..models import FaiDocumento, FaiFase, FaiGruppo, FaiOpzione, FaiRecord, FaiTipo, ProjectTechRef, TechRefKind
from ..services.fai import (
    allinea_riga,
    causale_proposta,
    ripetizione_entro,
    stato_articolo,
    numero_piano_automatico,
    prossimo_numero_fai,
    opzioni_attive,
    righe_registro,
    soglie,
    stato_iniziale,
    trova_o_crea_articolo,
)
from ..services.fai_report import conta_situazioni
from ..services.notify import notify_user
from ..tech_paths import normalizza_percorso
from ._shared import _tasks_shell_context, _utenti_riga_rapida


# Le colonne del file, per blocco della scheda: (campo, etichetta, lunghezza massima).
CAMPI_ARTICOLO = (
    ("nome_particolare", "Nome particolare", 255),
    ("revisione", "Rev.", 60),
    ("linea", "Linea", 120),
    ("criticita", "Criticità", 120),
)
CAMPI_CODICI = (
    ("pn_assy", "P/N assy", 120),
    ("pn_alternativo", "P/N alternativo", 120),
    ("rev_alternativo", "Rev. P/N alternativo", 60),
)
CAMPI_RIFERIMENTI = (
    ("fai_numero", "FAI CN n°", 40),
    ("fai_anno", "Anno FAI CN", 20),
    ("op", "OP", 120),
    ("oda_item", "OdA / Item", 120),
    ("invito", "N° invito", 120),
    ("faldone", "Faldone", 40),
    ("cci_numero", "CCI CN n°", 40),
    ("cci_anno", "Anno CCI CN", 20),
)
CAMPI_PIANO = (
    ("descrizione_piano", "Descrizione piano", 500),
    ("avanzamento", "Avanzamento piano", 1000),
)
CAMPI_VERSIONE = (
    ("versione_produzione", "Versione di produzione", 120),
    ("codice_dip", "Codice DIP", 120),
)
CAMPI_TESTO_FILE = CAMPI_ARTICOLO + CAMPI_CODICI + CAMPI_RIFERIMENTI + CAMPI_PIANO + CAMPI_VERSIONE + (
    ("invio_cq", "Invio CQ", 255),
)
CAMPI_DATA_FILE = ("data_chiusura", "data_versione", "data_approvazione_dip")
CAMPI_OPZIONE_FILE = (
    ("chiusura_con", FaiGruppo.CHIUSURA),
    ("stato_versione", FaiGruppo.VERSIONE),
    ("cross_correlation", FaiGruppo.CROSS),
)
CAMPI_DOCUMENTO = (("doc_sdc", "SDC"), ("doc_pfc", "PFC"), ("doc_sintesi", "Sintesi"), ("doc_fai", "FAI"))
# Il blocco piegato della scheda si apre da solo se contiene qualcosa.
NOMI_VERSIONE = (
    "versione_produzione", "stato_versione", "data_versione", "codice_dip", "data_approvazione_dip",
    "invio_cq", "cross_correlation", "doc_sdc", "doc_pfc", "doc_sintesi", "doc_fai",
)


class FaiForm(forms.Form):
    client_name = forms.CharField(max_length=180, required=False)
    part_number = forms.CharField(max_length=120)
    causale = forms.ModelChoiceField(queryset=FaiOpzione.objects.filter(gruppo=FaiGruppo.CAUSALE))
    tipo = forms.ChoiceField(choices=FaiTipo.choices)
    motivo = forms.CharField(required=False, max_length=1000)
    piano = forms.ModelChoiceField(queryset=FaiOpzione.objects.filter(gruppo=FaiGruppo.PIANO))
    piano_numero = forms.CharField(max_length=160, required=False)
    stato = forms.ModelChoiceField(queryset=FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO))
    data_invio = forms.DateField(required=False)
    path = forms.CharField(max_length=500, required=False)
    responsabile = forms.IntegerField(required=False)
    ultima_produzione = forms.DateField(required=False)
    ultima_spedizione = forms.DateField(required=False)
    scadenza_cliente = forms.DateField(required=False)
    note = forms.CharField(required=False, max_length=4000)

    def __init__(self, *args, storico: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, _etichetta, massimo in CAMPI_TESTO_FILE:
            self.fields[nome] = forms.CharField(required=False, max_length=massimo)
        for nome in CAMPI_DATA_FILE:
            self.fields[nome] = forms.DateField(required=False)
        for nome, gruppo in CAMPI_OPZIONE_FILE:
            self.fields[nome] = forms.ModelChoiceField(queryset=FaiOpzione.objects.filter(gruppo=gruppo), required=False)
        for nome, _etichetta in CAMPI_DOCUMENTO:
            self.fields[nome] = forms.ChoiceField(choices=[("", "")] + FaiDocumento.choices, required=False)
        # Il file non diceva il perché né il tipo: su un FAI storico non si possono pretendere.
        if storico:
            for nome in ("causale", "tipo", "piano"):
                self.fields[nome].required = False

    def clean_path(self):
        try:
            return normalizza_percorso(self.cleaned_data.get("path"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_responsabile(self):
        pk = self.cleaned_data.get("responsabile")
        if pk is None:
            return None
        from ..forms import task_active_users_queryset

        utente = task_active_users_queryset().filter(pk=pk).first()
        if utente is None:
            raise forms.ValidationError("Responsabile non valido.")
        return utente

    def clean(self):
        dati = super().clean()
        causale = dati.get("causale")
        if causale and causale.motivo_se_delta and dati.get("tipo") == FaiTipo.DELTA and not (dati.get("motivo") or "").strip():
            self.add_error("motivo", "Qui la procedura prevede il FAI completo: scrivi perché basta un Delta FAI.")
        return dati


def _vede_tutto(request) -> bool:
    return has_task_permission(request, "tasks_admin")


def _fai_visibili(request):
    """Cliente e P/N sono dati commerciali: fuori dal proprio ambito si vedono solo con la gestione."""
    records = FaiRecord.objects.select_related("articolo", "project", "responsabile", "causale", "piano", "stato")
    if _vede_tutto(request):
        return records
    return records.filter(project__in=scoped_projects_queryset(request))


def _gestisce(request, record: FaiRecord) -> bool:
    return _vede_tutto(request) or bool(record.project and can_manage_project(request, record.project))


def _puo_modificare(request, record: FaiRecord) -> bool:
    return record.responsabile_id == request.user.pk or _gestisce(request, record)


def _puo_creare(request, project) -> bool:
    if _vede_tutto(request):
        return True
    if project is None:
        return False
    return can_manage_project(request, project) or request.user.pk in project.team_user_ids


def _esporta(righe):
    response, writer = csv_download_response("registro_fai.csv", delimiter=";")
    writer.writerow([
        "Cliente", "P/N", "Numero piano", "Tipo", "Perché", "Stato FAI", "Data invio",
        "Fine ultima produzione", "Ultima spedizione", "Situazione", "Responsabile",
    ])
    for riga in righe:
        fai, articolo = riga["fai"], riga["articolo"]
        writer.writerow([
            articolo.client_name, articolo.part_number, fai.piano_numero, fai.get_tipo_display(),
            fai.causale.etichetta if fai.causale else "",
            fai.stato.etichetta, fai.data_invio or "", articolo.ultima_produzione or "",
            articolo.ultima_spedizione or "", riga["situazione"].etichetta,
            (fai.responsabile.get_full_name() or fai.responsabile.username) if fai.responsabile else "",
        ])
    return response


_TESTO_TUTTI = [c for c in CAMPI_TESTO_FILE if c[0] != "invio_cq"]


def colonne_tutti() -> list[str]:
    return (
        ["Cliente", "P/N", "Numero piano", "Tipo", "Stato", "Data invio", "Chiusura con", "Data chiusura"]
        + [c[1] for c in _TESTO_TUTTI]
        + ["Stato versione", "Data versione", "Data approvazione DIP", "Invio CQ", "Cross-correlation"]
        + [c[1] for c in CAMPI_DOCUMENTO]
        + ["Note"]
    )


def righe_tutti(records) -> list[list]:
    """Le stesse colonne del file, per chi deve ancora passargli i dati."""
    return [
        [
            f.articolo.client_name, f.articolo.part_number, f.piano_numero, f.get_tipo_display(), f.stato.etichetta,
            f.data_invio or "", f.chiusura_con.etichetta if f.chiusura_con else "", f.data_chiusura or "",
        ]
        + [getattr(f, c[0]) for c in _TESTO_TUTTI]
        + [
            f.stato_versione.etichetta if f.stato_versione else "", f.data_versione or "",
            f.data_approvazione_dip or "", f.invio_cq, f.cross_correlation.etichetta if f.cross_correlation else "",
        ]
        + [getattr(f, f"get_{c[0]}_display")() for c in CAMPI_DOCUMENTO]
        + [f.note]
        for f in records.select_related("chiusura_con", "stato_versione", "cross_correlation")
    ]


def _esporta_tutti(records):
    response, writer = csv_download_response("situazione_fai.csv", delimiter=";")
    writer.writerow(colonne_tutti())
    writer.writerows(righe_tutti(records))
    return response


def _tutti_i_fai(request):
    """Una riga per FAI, come il file: filtri sul server, il resto lo fa la tabella del portale."""
    records = _fai_visibili(request).select_related("chiusura_con")
    clienti = list(
        records.exclude(articolo__client_name="").order_by("articolo__client_name")
        .values_list("articolo__client_name", flat=True).distinct()
    )
    stati = FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO)
    cliente = (request.GET.get("cliente") or "").strip()
    stato = request.GET.get("stato", "")
    q = (request.GET.get("q") or "").strip()
    if cliente:
        records = records.filter(articolo__client_name=cliente)
    if stato.isdigit():
        records = records.filter(stato_id=int(stato))
    if q:
        records = records.filter(
            Q(articolo__part_number__icontains=q) | Q(articolo__client_name__icontains=q) | Q(piano_numero__icontains=q)
            | Q(op__icontains=q) | Q(oda_item__icontains=q) | Q(nome_particolare__icontains=q)
            | Q(fai_numero__icontains=q) | Q(pn_assy__icontains=q) | Q(pn_alternativo__icontains=q)
        )
    if request.GET.get("formato") == "csv":
        log_action(request, "kickoff_fai_esporta", "tasks", {"elenco": "tutti", "righe": records.count()})
        return _esporta_tutti(records)
    pagina = pagina_elenco(request, records)
    mesi = soglie().mesi_ripetizione
    for fai in pagina:
        fai.scadenza = aggiungi_mesi(fai.data_chiusura, mesi) if fai.data_chiusura else None
    return render(request, "tasks/fai_tutti.html", {
        **_tasks_shell_context(request, active="fai"),
        "page_title": "Registro FAI",
        "page_obj": pagina,
        "totale": pagina.paginator.count,
        "clienti": clienti,
        "stati": stati,
        "cliente": cliente,
        "stato_scelto": int(stato) if stato.isdigit() else None,
        "q": q,
        "fai_puo_creare": _vede_tutto(request),
    })


@task_permissions_required("tasks_view")
def fai_registro(request):
    if request.GET.get("per") == "fai":
        return _tutti_i_fai(request)
    tutte = righe_registro(_fai_visibili(request))
    limiti = soglie()
    conteggi = conta_situazioni(tutte)

    viste = (
        ("", "Tutti"),
        ("da_ripetere", "Da ripetere"),
        ("da_verificare", f"Oltre {limiti.mesi_verifica} mesi"),
        ("in_corso", "In corso"),
        ("date_mancanti", "Senza date"),
    )
    vista = request.GET.get("vista", "")
    vista = vista if vista in dict(viste) else ""
    q = (request.GET.get("q") or "").strip()
    righe = [r for r in tutte if not vista or r["situazione"].codice == vista]
    if q:
        testo = q.lower()
        righe = [
            r for r in righe
            if testo in f"{r['articolo'].client_name} {r['articolo'].part_number} {r['fai'].piano_numero}".lower()
        ]
    # Prima quello che richiede una decisione, poi il resto.
    ordine = {"da_ripetere": 0, "da_verificare": 1, "in_corso": 2, "date_mancanti": 3, "in_regola": 4}
    righe.sort(key=lambda r: (ordine[r["situazione"].codice], r["articolo"].part_number.lower()))

    if request.GET.get("formato") == "csv":
        log_action(request, "kickoff_fai_esporta", "tasks", {"vista": vista, "righe": len(righe)})
        return _esporta(righe)

    return render(request, "tasks/fai_registro.html", {
        **_tasks_shell_context(request, active="fai"),
        "page_title": "Registro FAI",
        "righe": righe,
        "viste": [
            {"codice": codice, "etichetta": etichetta, "conta": conteggi.get(codice, 0) if codice else len(tutte)}
            for codice, etichetta in viste
        ],
        "vista": vista,
        "q": q,
        "mesi_verifica": limiti.mesi_verifica,
        "fai_puo_creare": _vede_tutto(request),
    })


def _utenti(project) -> dict:
    if project:
        return _utenti_riga_rapida(project)
    from ..forms import task_active_users_queryset, user_display_label

    return {"team": [], "altri": [(u.pk, user_display_label(u)) for u in task_active_users_queryset()]}


def _intero(valore):
    if isinstance(valore, FaiOpzione):
        return valore.pk
    return int(valore) if str(valore or "").isdigit() else None


def _iso(giorno) -> str:
    """Il campo date vuole l'ISO, sia dal record sia dal POST da ripresentare."""
    return giorno.isoformat() if giorno else ""


def _dati_originali(record) -> list[tuple[str, str]]:
    """La riga del file con nomi leggibili, non con quelli interni."""
    nomi = {"cliente": "Cliente", "pn": "P/N", "stato": "Stato piano FAI"}
    for campo in FaiRecord._meta.fields:
        nomi.setdefault(campo.name, str(campo.verbose_name))
    return [(nomi.get(nome, nome), valore) for nome, valore in record.origine_excel.items()]


def _campi(form) -> dict[str, dict]:
    return {
        nome: {"nome": nome, "etichetta": etichetta, "massimo": massimo, "valore": form[nome].value(), "errori": form[nome].errors}
        for nome, etichetta, massimo in CAMPI_TESTO_FILE
    }


def _campi_opzione(form, record, nome, etichetta, gruppo) -> dict:
    corrente = getattr(record, nome) if record else None
    return {
        "nome": nome, "etichetta": etichetta, "scelta": _intero(form[nome].value()),
        "opzioni": opzioni_attive(gruppo, corrente),
    }


def _dati_op(op: dict, part_number: str = "") -> dict:
    """L'OP dell'elenco unico, con le sue anomalie e il controllo del P/N."""
    pn_op = normalize_part_number(op.get("pn"))
    return {
        **op,
        "anomalie": ordini_produzione.conta_anomalie(op),
        "url_anomalie": f"{reverse('gestione_anomalie_page')}?{urlencode({'op': op['op'], 'filter': 'tutti'})}",
        "url_scheda": reverse("produzione:scheda", args=[op["id"]]) if str(op.get("id", "")).isdigit() else "",
        "pn_diverso": bool(pn_op and part_number and pn_op != normalize_part_number(part_number)),
    }


def _op_collegato(form) -> dict | None:
    titolo = (form["op"].value() or "").strip()
    if not titolo or not ordini_produzione.disponibile():
        return None
    op = ordini_produzione.per_titolo(titolo)
    if op is None:
        return {"trovato": False, "op": titolo}
    return {"trovato": True, **_dati_op(op, form["part_number"].value() or "")}


@task_permissions_required("tasks_view", api=True)
def fai_op(request):
    """OP dell'elenco unico per il campo OP della scheda: ``?q=`` cerca, ``?op=`` legge uno."""
    if not ordini_produzione.disponibile():
        return JsonResponse({"ok": True, "disponibile": False, "risultati": []})
    titolo = (request.GET.get("op") or "").strip()
    if titolo:
        op = ordini_produzione.per_titolo(titolo)
        dati = _dati_op(op, request.GET.get("pn", "")) if op else None
        return JsonResponse({"ok": True, "disponibile": True, "op": dati})
    return JsonResponse({"ok": True, "disponibile": True, "risultati": ordini_produzione.cerca(request.GET.get("q", ""))})


def _contesto_scheda(request, form, record, project, ref, *, modificabile: bool) -> dict:
    articolo = record.articolo if record else None
    limiti = soglie()
    annullato = bool(record and record.stato.fase == FaiFase.ANNULLATO)
    return {
        "f": _campi(form),
        "op_collegato": _op_collegato(form),
        "nuovo_op": nuovo_op.contesto(request) if modificabile else None,
        "situazione": stato_articolo(articolo, record, limiti=limiti) if record and not annullato else None,
        "ripetizione": ripetizione_entro(articolo, record, limiti) if record and not annullato else None,
        "ha_versione": any(form[nome].value() for nome in NOMI_VERSIONE),
        "campo_chiusura": _campi_opzione(form, record, "chiusura_con", "Chiusura con", FaiGruppo.CHIUSURA),
        "campo_versione": _campi_opzione(form, record, "stato_versione", "Stato versione", FaiGruppo.VERSIONE),
        "campo_cross": _campi_opzione(form, record, "cross_correlation", "Cross-correlation", FaiGruppo.CROSS),
        "campi_documento": [
            {"nome": nome, "etichetta": etichetta, "valore": form[nome].value() or ""}
            for nome, etichetta in CAMPI_DOCUMENTO
        ],
        "scelte_documento": FaiDocumento.choices,
        "valore_invio_cq": form["invio_cq"].value() or "",
        "fai_storico": bool(record and record.chiave_import),
        "dati_originali": _dati_originali(record) if record else [],
        **_tasks_shell_context(request, active="tech_refs" if project else "fai", project=project),
        "page_title": "Scheda FAI",
        "form": form,
        "record": record,
        "fai_project": project,
        "fai_ref": ref,
        "fai_attivita": (ref or (record.tech_ref if record else None) or SimpleNamespace(task=None)).task,
        "modificabile": modificabile,
        "puo_eliminare": bool(record and _gestisce(request, record)),
        "causali": opzioni_attive(FaiGruppo.CAUSALE, record.causale if record else None),
        "piani": opzioni_attive(FaiGruppo.PIANO, record.piano if record else None),
        "stati": opzioni_attive(FaiGruppo.STATO, record.stato if record else None),
        "tipi": FaiTipo.choices,
        "scelta_causale": _intero(form["causale"].value()),
        "scelta_piano": _intero(form["piano"].value()),
        "scelta_stato": _intero(form["stato"].value()),
        "utenti": _utenti(project),
        "responsabile_scelto": _intero(form["responsabile"].value()),
        "storico": articolo.fai.select_related("causale", "stato").exclude(pk=record.pk) if articolo else [],
    }


def _iniziali(record, project, ref, richiesta) -> dict:
    if record:
        articolo = record.articolo
        return {
            "client_name": articolo.client_name, "part_number": articolo.part_number, "causale": record.causale_id,
            "tipo": record.tipo, "motivo": record.motivo, "piano": record.piano_id,
            "piano_numero": record.piano_numero, "stato": record.stato_id, "data_invio": _iso(record.data_invio),
            "path": record.path, "responsabile": record.responsabile_id,
            "ultima_produzione": _iso(articolo.ultima_produzione), "ultima_spedizione": _iso(articolo.ultima_spedizione),
            "scadenza_cliente": _iso(articolo.scadenza_cliente), "note": record.note,
            **{c[0]: getattr(record, c[0]) for c in CAMPI_TESTO_FILE},
            **{nome: _iso(getattr(record, nome)) for nome in CAMPI_DATA_FILE},
            **{nome: getattr(record, f"{nome}_id") for nome, _g in CAMPI_OPZIONE_FILE},
            **{c[0]: getattr(record, c[0]) for c in CAMPI_DOCUMENTO},
        }
    causale = causale_proposta(richiesta.GET.get("causale", ""))
    piani = opzioni_attive(FaiGruppo.PIANO)
    stato = stato_iniziale()
    return {
        "client_name": project.client_name if project else "",
        # Dalla scheda dell'OP (Ordini di produzione) arrivano OP e P/N.
        "part_number": project.part_number if project else richiesta.GET.get("pn", "")[:120],
        "op": richiesta.GET.get("op", "")[:120],
        "causale": causale.pk if causale else None,
        "tipo": causale.tipo_proposto if causale else "",
        "piano": piani[0].pk if piani else None,
        "piano_numero": ref.code if ref else "",
        "stato": stato.pk if stato else None,
        "path": ref.path if ref else "",
        "responsabile": ref.assigned_to_id if ref else None,
        "fai_anno": str(timezone.localdate().year),
        "fai_numero": prossimo_numero_fai(timezone.localdate().year),
    }


@task_permissions_required("tasks_view")
def fai_scheda(request, fai_id: int | None = None):
    """Nuovo FAI (dal registro o da una commessa) oppure scheda di quello esistente."""
    record = get_object_or_404(_fai_visibili(request), pk=fai_id) if fai_id else None
    project = record.project if record else None
    ref = None
    if record is None:
        sorgente = request.POST if request.method == "POST" else request.GET
        if (sorgente.get("project") or "").isdigit():
            project = scoped_projects_queryset(request).filter(pk=int(sorgente["project"])).first()
            if project is None:
                raise Http404
        if project and (sorgente.get("ref") or "").isdigit():
            ref = ProjectTechRef.objects.filter(
                pk=int(sorgente["ref"]), project=project, kind=TechRefKind.FAI, fai_record__isnull=True
            ).first()

    # Chi ha ricevuto la riga, o l'attività che la chiede, deve poter compilare la scheda.
    modificabile = _puo_modificare(request, record) if record else (
        _puo_creare(request, project) or bool(ref and ref.assigned_to_id == request.user.pk)
    )
    if not record and not modificabile:
        raise PermissionDenied

    if request.method == "POST":
        if request.POST.get("azione") == "elimina":
            if not (record and _gestisce(request, record)):
                raise PermissionDenied
            return _elimina(request, record)
        if not modificabile:
            raise PermissionDenied
        form = FaiForm(request.POST, storico=bool(record and record.chiave_import))
        if form.is_valid():
            record = _salva(request, form.cleaned_data, record, project, ref)
            messages.success(request, f"FAI di {record.articolo.part_number} salvato.")
            return _torna(project)
    else:
        form = FaiForm(initial=_iniziali(record, project, ref, request), storico=bool(record and record.chiave_import))
    return render(
        request, "tasks/fai_scheda.html", _contesto_scheda(request, form, record, project, ref, modificabile=modificabile)
    )


def _torna(project):
    if project:
        return redirect("tasks:project_tech_refs", project.pk)
    return redirect("tasks:fai_registro")


def _elimina(request, record: FaiRecord):
    project, articolo, riga = record.project, record.articolo, record.tech_ref
    dettaglio = {"id": record.pk, "project_id": record.project_id, "part_number": articolo.part_number}
    with transaction.atomic():
        record.delete()
        if riga is not None and riga.task_id:
            # L'attività chiede ancora il FAI: la richiesta resta, vuota.
            riga = ProjectTechRef.objects.get(pk=riga.pk)
            riga.code, riga.path = "", ""
            riga.reopen()
            riga.save()
        elif riga is not None:
            riga.delete()
        if not articolo.fai.exists():
            articolo.delete()
    log_action(request, "kickoff_fai_elimina", "tasks", dettaglio)
    messages.success(request, f"FAI di {dettaglio['part_number']} eliminato.")
    return _torna(project)


def _salva(request, dati, record, project, ref) -> FaiRecord:
    prima = record.responsabile_id if record else None
    with transaction.atomic():
        articolo = trova_o_crea_articolo(dati["client_name"], dati["part_number"])
        articolo.ultima_produzione = dati["ultima_produzione"]
        articolo.ultima_spedizione = dati["ultima_spedizione"]
        articolo.scadenza_cliente = dati["scadenza_cliente"]
        articolo.save()

        nuovo = record is None
        if nuovo:
            record = FaiRecord(project=project, tech_ref=ref, created_by=request.user)
        record.articolo = articolo
        for campo in ("causale", "tipo", "motivo", "piano", "stato", "path", "note"):
            setattr(record, campo, dati[campo])
        record.data_invio = dati["data_invio"]
        for nome, _etichetta, _massimo in CAMPI_TESTO_FILE:
            setattr(record, nome, dati[nome].strip())
        for nome in CAMPI_DATA_FILE:
            setattr(record, nome, dati[nome])
        for nome, _gruppo in CAMPI_OPZIONE_FILE:
            setattr(record, nome, dati[nome])
        for nome, _etichetta in CAMPI_DOCUMENTO:
            setattr(record, nome, dati[nome])
        record.responsabile = dati["responsabile"]
        record.piano_numero = dati["piano_numero"].strip()
        if not record.piano_numero and record.piano and record.piano.numerazione_auto:
            record.piano_numero = numero_piano_automatico(articolo)
        record.save()
        allinea_riga(record, request.user)

    log_action(request, "kickoff_fai_salva", "tasks", {
        "id": record.pk, "project_id": record.project_id, "nuovo": nuovo, "tipo": record.tipo,
        "causale": record.causale.etichetta if record.causale else "", "stato": record.stato.etichetta,
    })
    if record.responsabile and record.responsabile_id not in (prima, request.user.pk):
        notify_user(
            record.responsabile,
            f"Sei responsabile del FAI di {articolo.part_number}.",
            reverse("tasks:fai_scheda", args=[record.pk]),
        )
    return record
