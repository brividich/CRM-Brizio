"""MOD.128 MPQ — F2 UI (cruscotto processi qualificati + dettaglio processo).

Viste di **sola lettura** sui modelli additivi ``models_mpq``: aggregano i
processi qualificati/speciali, le abilitazioni persona×processo e le
certificazioni individuali nella "vista MOD.128" di controllo. Le scadenze
(processo *e* certificato individuale) sono classificate con la stessa logica RAG
del cruscotto Qualifiche esistente (fonte coerente).

Convenzioni rispettate:
- nomi persona risolti **fail-safe** dall'anagrafica legacy (fallback ``#<id>``);
- nessuna scrittura: le scadenze/promemoria restano gestite altrove (F5/automazioni);
- ACL formale rimandata a F4 (oggi ``@login_required`` come le altre pagine
  Qualifiche); la voce vive nel gruppo Competenze → Qualifiche.

Importato da ``urls.py`` come modulo dedicato (``from . import views_mpq``).
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models_mpq import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    ProcessoQualificato,
    RequisitoQualifica,
)

TIPI_REQUISITO_PER_PERSONA = RequisitoQualifica.TIPI_PER_PERSONA

from .services.mpq_ruoli import STANDARD as STANDARD_RUOLI  # noqa: E402

_MESI_ABBR = ["gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic"]


def _check_mpq_permission(request, code=None) -> bool:
    """Permesso canonico MOD.128 MPQ (governabile in /admin-portale/acl-canonico/).

    Il bypass superuser/admin legacy è dentro ``evaluate_permission_code_access``;
    altrimenti serve il grant del ruolo sul codice canonico
    (``anagrafica.mpq.view`` / ``.manage``). Allinea la guardia in-view alla
    decisione del middleware ACL canonico: ciò che si imposta lì governa davvero
    l'accesso (in dev/test il middleware è disattivo → qui resta l'unico controllo).
    """
    from core.acl_v2 import evaluate_permission_code_access
    from core.legacy_utils import get_legacy_user
    from .acl_bootstrap import PERM_MPQ_VIEW

    try:
        legacy_user = get_legacy_user(request.user)
    except Exception:
        legacy_user = None
    return bool(evaluate_permission_code_access(
        permission_code=code or PERM_MPQ_VIEW,
        legacy_user=legacy_user, django_user=request.user,
    ).get("allowed"))


def _mpq_denied(request):
    """Risposta comune di diniego: messaggio + ritorno alla dashboard anagrafica."""
    messages.error(request, "Non hai i permessi per i processi qualificati (MOD.128).")
    return redirect("anagrafica:index")


def _nomi_map(legacy_ids) -> dict[int, str]:
    """{legacy_anagrafica_id: 'Cognome Nome'} — fail-safe (fallback a valle '#<id>').

    La sorgente anagrafica legacy può non essere disponibile (es. in test): in
    quel caso ritorna una mappa vuota e il chiamante usa il fallback ``#<id>``.
    """
    nomi: dict[int, str] = {}
    ids = [i for i in set(legacy_ids or []) if i is not None]
    if not ids:
        return nomi
    try:
        from core.legacy_models import AnagraficaDipendente
        rows = (AnagraficaDipendente.objects
                .filter(id__in=ids).values("id", "cognome", "nome"))
        for r in rows:
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            cog = (r.get("cognome") or "").strip()
            nom = (r.get("nome") or "").strip()
            etichetta = f"{cog} {nom}".strip()
            if etichetta:
                nomi[lid] = etichetta
    except Exception:  # pragma: no cover - dipende dalla sorgente legacy
        pass
    return nomi


def _classifica_scadenza(data_scadenza, oggi, s30, s60):
    """Stato RAG di una scadenza (coerente con il cruscotto Qualifiche)."""
    if data_scadenza is None:
        return ("permanente", "Permanente")
    if data_scadenza < oggi:
        return ("scaduta", "Scaduta")
    if data_scadenza <= s30:
        return ("s30", "In scadenza ≤30gg")
    if data_scadenza <= s60:
        return ("s60", "In scadenza ≤60gg")
    return ("valida", "Valida")


@login_required
def mpq_cruscotto(request):
    """Cruscotto MOD.128 — vista trasversale sui processi qualificati.

    KPI (processi per stato, scadenze RAG a livello processo, abilitazioni,
    persone coinvolte), distribuzione per regime, timeline scadenze 12 mesi,
    scadenze urgenti (processo ≤60gg o scaduto) ed elenco processi con link al
    dettaglio. Aggrega senza duplicare: qualsiasi modifica fatta in admin/detail
    si riflette qui.
    """
    if not _check_mpq_permission(request):
        return _mpq_denied(request)

    oggi = timezone.localdate()
    s30 = oggi + timedelta(days=30)
    s60 = oggi + timedelta(days=60)

    processi = list(
        ProcessoQualificato.objects
        .select_related("cliente", "ente_certificatore")
        .annotate(n_abil=Count("abilitazioni", distinct=True))
        .order_by("cliente__nome", "nome")
    )

    stato_labels = dict(ProcessoQualificato.STATO_CHOICES)
    regime_labels = dict(ProcessoQualificato.REGIME_CHOICES)
    stato_count = {c: 0 for c, _ in ProcessoQualificato.STATO_CHOICES}
    regime_count = {c: 0 for c, _ in ProcessoQualificato.REGIME_CHOICES}
    n_scaduti = n_s30 = n_s60 = 0

    # Timeline scadenze processo (prossimi 12 mesi).
    buckets: "OrderedDict[tuple[int, int], int]" = OrderedDict()
    yy, mm = oggi.year, oggi.month
    for _ in range(12):
        buckets[(yy, mm)] = 0
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    primo_del_mese = oggi.replace(day=1)

    righe = []
    urgenti = []
    for p in processi:
        stato_count[p.stato] = stato_count.get(p.stato, 0) + 1
        regime_count[p.regime] = regime_count.get(p.regime, 0) + 1
        scad = p.scadenza_effettiva
        scad_stato, scad_label = _classifica_scadenza(scad, oggi, s30, s60)
        if scad_stato == "scaduta":
            n_scaduti += 1
        elif scad_stato == "s30":
            n_s30 += 1
        elif scad_stato == "s60":
            n_s60 += 1
        if scad and scad >= primo_del_mese and (scad.year, scad.month) in buckets:
            buckets[(scad.year, scad.month)] += 1
        riga = {
            "obj": p,
            "scadenza": scad,
            "scad_stato": scad_stato,
            "scad_label": scad_label,
            "giorni": (scad - oggi).days if scad else None,
            "n_abil": p.n_abil,
            "regime_label": regime_labels.get(p.regime, p.regime),
            "stato_label": stato_labels.get(p.stato, p.stato),
        }
        righe.append(riga)
        if scad is not None and scad <= s60:
            urgenti.append(riga)

    urgenti.sort(key=lambda r: r["scadenza"])
    urgenti = urgenti[:15]

    max_n = max(buckets.values()) if buckets else 0
    timeline = [
        {"label": f"{_MESI_ABBR[m - 1]} {str(y)[2:]}", "n": n,
         "pct": int(round(n / max_n * 100)) if max_n else 0}
        for (y, m), n in buckets.items()
    ]

    distribuzione = [
        {"code": c, "label": regime_labels[c], "n": regime_count[c]}
        for c, _ in ProcessoQualificato.REGIME_CHOICES if regime_count[c]
    ]

    # Certificazioni individuali in scadenza ≤60gg (seconda scadenza, per audit).
    cert_scad = (
        CertificazioneIndividuale.objects
        .filter(stato=CertificazioneIndividuale.STATO_ATTIVA,
                data_scadenza__isnull=False, data_scadenza__lte=s60)
        .count()
    )

    # Persone e abilitazioni attive.
    abil_attive = AbilitazioneProcesso.objects.filter(
        stato=AbilitazioneProcesso.STATO_ATTIVA
    )
    n_abilitazioni = abil_attive.count()
    n_persone = abil_attive.values("legacy_anagrafica_id").distinct().count()

    return render(request, "anagrafica/pages/mpq_cruscotto.html", {
        "oggi": oggi,
        "can_manage": _check_manage(request),
        "processi": righe,
        "n_processi": len(processi),
        "n_attivi": stato_count.get(ProcessoQualificato.STATO_ATTIVO, 0),
        "n_sospesi": stato_count.get(ProcessoQualificato.STATO_SOSPESO, 0),
        "n_revocati": stato_count.get(ProcessoQualificato.STATO_REVOCATO, 0),
        "n_dismessi": (stato_count.get(ProcessoQualificato.STATO_DISMESSO, 0)
                       + stato_count.get(ProcessoQualificato.STATO_NON_RINNOVATO, 0)),
        "n_scaduti": n_scaduti,
        "n_in_scadenza": n_s30 + n_s60,
        "n_s30": n_s30,
        "n_abilitazioni": n_abilitazioni,
        "n_persone": n_persone,
        "n_clienti": ClienteQualificante.objects.filter(is_active=True).count(),
        "cert_scad": cert_scad,
        "distribuzione": distribuzione,
        "timeline": timeline,
        "scadenze_urgenti": urgenti,
    })


@login_required
def mpq_processo_detail(request, processo_id: int):
    """Dettaglio di un processo qualificato (la "riga" del MOD.128 espansa).

    Testata (cliente, regime, livello, scadenza, stato) + clienti addizionali,
    reparti di distribuzione, riferimenti/codici, elenco abilitazioni per ruolo
    (con certificazioni individuali e seconda scadenza) e storico append-only.
    """
    if not _check_mpq_permission(request):
        return _mpq_denied(request)

    processo = get_object_or_404(
        ProcessoQualificato.objects
        .select_related("cliente", "ente_certificatore", "tipo_qualifica"),
        pk=processo_id,
    )
    oggi = timezone.localdate()
    s30 = oggi + timedelta(days=30)
    s60 = oggi + timedelta(days=60)

    abilitazioni = list(
        processo.abilitazioni
        .select_related("dipendente_qualifica")
        .prefetch_related("certificazioni", "certificazioni__ente_certificatore", "ruoli_processo")
        .order_by("legacy_anagrafica_id")
    )
    nomi = _nomi_map([a.legacy_anagrafica_id for a in abilitazioni])

    # Requisiti del processo uguali per tutti (contratto, audit, certificato…).
    requisiti_generici = list(processo.requisiti.all())
    # «Cosa serve a una persona»: l'unico elenco dei requisiti per persona (per ruolo).
    requisiti_persona = list(
        processo.requisiti_persona
        .select_related("corso", "tipo_visita", "tipo_qualifica", "categoria_dpi").prefetch_related("ruoli")
    )
    ha_requisiti = bool(any(r.attivo for r in requisiti_generici)
                        or any(r.attivo for r in requisiti_persona))
    from .services.mpq_persone import contesto_processo, stato_persona
    from .services.mpq_ruoli import nomi_ruoli

    ctx_persone = contesto_processo(processo, abilitazioni)

    ab_stato_labels = dict(AbilitazioneProcesso.STATO_CHOICES)
    righe = []
    for a in abilitazioni:
        certs = []
        for c in a.certificazioni.all():
            c_stato, c_label = _classifica_scadenza(c.data_scadenza, oggi, s30, s60)
            certs.append({"obj": c, "scad_stato": c_stato, "scad_label": c_label})
        if a.nominativo_esterno:
            nome_persona, nome_risolto = f"{a.nominativo_esterno} (esterno)", False
        else:
            nome_persona = nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}"
            nome_risolto = a.legacy_anagrafica_id in nomi
        stato = stato_persona(a, oggi=oggi, contesto=ctx_persone)
        scad_p = stato["scadenza"]
        righe.append({
            "obj": a,
            "nome": nome_persona,
            "nome_risolto": nome_risolto,
            "ruoli": [],
            "ruoli_processo": nomi_ruoli(a),
            "stato_label": ab_stato_labels.get(a.stato, a.stato),
            "certificazioni": certs,
            "conformita": stato if ha_requisiti else None,
            "stato_persona": stato,
            "scadenza_persona": scad_p,
            "scad_persona_stato": _classifica_scadenza(scad_p, oggi, s30, s60)[0] if scad_p else "",
            # Prima voce da sistemare: il pulsante della riga porta lì.
            "da_fare": next((v for v in stato["voci"]
                             if v.get("bloccante", True) and v["stato"] in ("scaduto", "mancante", "in_scadenza")
                             and v.get("req") is not None), None),
        })

    scad = processo.scadenza_effettiva
    scad_stato, scad_label = _classifica_scadenza(scad, oggi, s30, s60)

    from .services.mpq_macchine import righe_macchine

    macchine = righe_macchine(processo, oggi=oggi)

    return render(request, "anagrafica/pages/mpq_processo_detail.html", {
        "oggi": oggi,
        "can_manage": _check_manage(request),
        "processo": processo,
        "scadenza": scad,
        "scad_stato": scad_stato,
        "scad_label": scad_label,
        "clienti_addizionali": list(processo.clienti_addizionali.all()),
        "reparti": list(processo.reparti.all()),
        "riferimenti": list(processo.riferimenti.all()),
        "tipi_per_persona": TIPI_REQUISITO_PER_PERSONA,
        "requisiti_generici": requisiti_generici,
        "ha_requisiti": ha_requisiti,
        "abilitazioni": righe,
        "storico": list(processo.storico.select_related("registrato_da")[:50]),
        "attrezzature": macchine,
        "n_persone_operative": sum(1 for r in righe if r["stato_persona"]["operativa"]),
        "n_macchine_operative": sum(1 for r in macchine if r["operativa"]),
        "ruoli_catalogo": list(processo.ruoli.select_related("competenza")),
        "requisiti_persona": requisiti_persona,
        "requisiti_macchina": list(processo.requisiti_macchina.select_related("piano")),
        "parametri_verifica": list(processo.parametri_verifica.all()),
    })


def _build_vista_groups(processi_qs=None):
    """Aggrega i processi nella "vista MOD.128", **raggruppati per cliente**.

    Ritorna ``[{"cliente": str, "righe": [dict, ...]}, ...]`` dove ogni riga
    replica la struttura del modulo cartaceo (personale per ruolo, scadenze
    processo+individuali, distribuzione a reparto). Sorgente unica condivisa tra
    la vista HTML nativa e l'export .docx (replica-Word). Nomi persona risolti
    fail-safe (fallback ``#<id>``). Il personale organizzativo non è nominale:
    la riga espone il rimando alla dichiarazione invece dei nominativi.
    """
    from collections import OrderedDict

    oggi = timezone.localdate()
    qs = ProcessoQualificato.objects.all() if processi_qs is None else processi_qs
    processi = list(
        qs.select_related("cliente")
        .prefetch_related("reparti", "riferimenti",
                          "abilitazioni", "abilitazioni__certificazioni")
        .order_by("cliente__nome", "nome")
    )

    legacy_ids = set()
    for p in processi:
        for a in p.abilitazioni.all():
            legacy_ids.add(a.legacy_anagrafica_id)
    nomi = _nomi_map(legacy_ids)

    groups_map: "OrderedDict[str, list]" = OrderedDict()
    for p in processi:
        righe = groups_map.setdefault(p.cliente.nome, [])
        qual, add, ctrl, p145, scadenze = [], [], [], [], []
        scad_proc = p.scadenza_effettiva
        if scad_proc:
            scadenze.append(f"Processo: {scad_proc.strftime('%d-%m-%Y')}")
        for a in p.abilitazioni.all():
            if a.stato != AbilitazioneProcesso.STATO_ATTIVA:
                continue
            nome = a.nominativo_esterno or nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}"
            if a.is_qualificato:
                qual.append(nome)
            if a.is_addetto:
                add.append(nome)
            if a.is_controllore:
                ctrl.append(nome)
            if a.is_part145:
                p145.append(nome)
            for c in a.certificazioni.all():
                if c.data_scadenza:
                    etichetta = f"{c.schema} {c.numero}".strip()
                    scadenze.append(
                        f"{nome} · {etichetta}: {c.data_scadenza.strftime('%d-%m-%Y')}"
                    )
        organizzativo = p.personale_modalita == ProcessoQualificato.MODALITA_ORGANIZZATIVO
        org_rif = ""
        if organizzativo:
            org_rif = p.riferimento_dichiarazione or "Personale organizzativo (vedi dichiarazione)"
        righe.append({
            "processo_id": p.id,
            "processo": p.nome,
            "livello": p.livello,
            "regime": p.get_regime_display(),
            "riferimenti": [r.codice for r in p.riferimenti.all()],
            "qualificato": qual,
            "addetto": add,
            "controllore": ctrl,
            "part145": p145,
            "scadenze": scadenze,
            "reparti": [r.nome for r in p.reparti.all()],
            "stato": p.get_stato_display(),
            "stato_code": p.stato,
            "organizzativo": organizzativo,
            "organizzativo_rif": org_rif,
        })

    return [{"cliente": nome, "righe": righe} for nome, righe in groups_map.items()]


@login_required
def mpq_vista(request):
    """Vista "MOD.128" (F3): tabella 8-col per cliente + export **.docx** (replica-Word).

    Deliverable d'audit: la stessa aggregazione alimenta la pagina HTML nativa
    (print-friendly) e il documento Word scaricabile (``?format=docx``). Filtri
    leggeri: solo attivi (default) e per cliente.
    """
    if not _check_mpq_permission(request):
        return _mpq_denied(request)

    oggi = timezone.localdate()
    solo_attivi = request.GET.get("tutti") != "1"
    cliente_id = (request.GET.get("cliente") or "").strip()

    qs = ProcessoQualificato.objects.all()
    if solo_attivi:
        qs = qs.filter(stato=ProcessoQualificato.STATO_ATTIVO)
    if cliente_id.isdigit():
        qs = qs.filter(cliente_id=int(cliente_id))

    gruppi = _build_vista_groups(qs)

    if request.GET.get("format") == "docx":
        try:
            from .mpq_export import build_mod128_docx_bytes
            data = build_mod128_docx_bytes(gruppi, oggi)
        except ImportError:
            messages.error(
                request,
                "Export .docx non disponibile: la libreria python-docx non è installata sul server.")
            return redirect("anagrafica:mpq_vista")
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        resp["Content-Disposition"] = (
            f'attachment; filename="MOD128_vista_{oggi:%Y%m%d}.docx"'
        )
        return resp

    return render(request, "anagrafica/pages/mpq_vista.html", {
        "oggi": oggi,
        "gruppi": gruppi,
        "clienti": ClienteQualificante.objects.filter(is_active=True).order_by("nome"),
        "solo_attivi": solo_attivi,
        "cliente_sel": cliente_id,
        "n_processi": sum(len(g["righe"]) for g in gruppi),
    })


# ───────────────────────────────────────────────────────────────────────────
# Gestione (CRUD) — gated ``anagrafica.mpq.manage``
# ───────────────────────────────────────────────────────────────────────────

def _check_manage(request) -> bool:
    from .acl_bootstrap import PERM_MPQ_MANAGE
    return _check_mpq_permission(request, PERM_MPQ_MANAGE)


def _mpq_log(request, *, processo=None, abilitazione=None, evento="", dettaglio=""):
    """Registra un evento su MpqStorico (append-only), fail-safe."""
    from .models_mpq import MpqStorico
    try:
        MpqStorico.objects.create(
            processo=processo, abilitazione=abilitazione, evento=evento[:200],
            dettaglio=dettaglio, origine=MpqStorico.Origine.MANUALE,
            registrato_da=request.user if request.user.is_authenticated else None,
        )
    except Exception:  # pragma: no cover - lo storico non deve bloccare l'azione
        pass


def _dipendenti_scelte():
    """[(legacy_id, 'Cognome Nome'), ...] per il picker dipendente (fail-safe)."""
    out = []
    try:
        from core.legacy_models import AnagraficaDipendente
        for r in (AnagraficaDipendente.objects
                  .values("id", "cognome", "nome").order_by("cognome", "nome")):
            lid = r.get("id")
            if lid is None:
                continue
            cog = (r.get("cognome") or "").strip()
            nom = (r.get("nome") or "").strip()
            out.append((int(lid), f"{cog} {nom}".strip() or f"#{lid}"))
    except Exception:
        pass
    return out


def _qa_corso_options():
    """Opzioni piano/categoria per il popup crea-al-volo corso (fail-safe)."""
    piani, categorie = [], []
    try:
        from .models import TrainingPlan
        piani = [{"id": p.pk, "nome": str(p)}
                 for p in TrainingPlan.objects.filter(is_active=True).order_by("nome")]
    except Exception:
        pass
    try:
        from .models_rischi import CategoriaCorso
        categorie = [{"id": c.pk, "nome": c.nome}
                     for c in CategoriaCorso.objects.filter(is_active=True).order_by("nome")]
    except Exception:
        pass
    return piani, categorie


@login_required
def mpq_processo_create(request):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import ProcessoQualificatoForm
    if request.method == "POST":
        form = ProcessoQualificatoForm(request.POST)
        if form.is_valid():
            proc = form.save()
            _mpq_log(request, processo=proc, evento="Creazione processo")
            messages.success(request, f"Processo «{proc.nome}» creato.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)
    else:
        form = ProcessoQualificatoForm()
    qa_piani, qa_categorie = _qa_corso_options()
    return render(request, "anagrafica/pages/mpq_processo_form.html", {
        "form": form, "titolo": "Nuovo processo qualificato (MOD.128)",
        "back_url": reverse("anagrafica:mpq_cruscotto"),
        "mpq_requisiti": True, "qa_piani": qa_piani, "qa_categorie": qa_categorie,
    })


@login_required
def mpq_processo_edit(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import ProcessoQualificatoForm
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    if request.method == "POST":
        form = ProcessoQualificatoForm(request.POST, instance=proc)
        if form.is_valid():
            form.save()
            _mpq_log(request, processo=proc, evento="Modifica processo")
            messages.success(request, "Processo aggiornato.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)
    else:
        form = ProcessoQualificatoForm(instance=proc)
    qa_piani, qa_categorie = _qa_corso_options()
    return render(request, "anagrafica/pages/mpq_processo_form.html", {
        "form": form, "titolo": f"Modifica · {proc.nome}",
        "back_url": reverse("anagrafica:mpq_processo_detail", args=[proc.id]),
        "mpq_requisiti": True, "qa_piani": qa_piani, "qa_categorie": qa_categorie,
    })


@login_required
@require_POST
def mpq_processo_delete(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    nome = proc.nome
    proc.delete()
    messages.success(request, f"Processo «{nome}» eliminato.")
    return redirect("anagrafica:mpq_cruscotto")


@login_required
def mpq_cliente_list(request):
    if not _check_manage(request):
        return _mpq_denied(request)
    return render(request, "anagrafica/pages/mpq_clienti.html", {
        "clienti": ClienteQualificante.objects.all().order_by("tipo", "nome"),
    })


@login_required
def mpq_cliente_create(request):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import ClienteQualificanteForm
    if request.method == "POST":
        form = ClienteQualificanteForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f"Cliente/ente «{c.nome}» creato.")
            return redirect("anagrafica:mpq_cliente_list")
    else:
        form = ClienteQualificanteForm()
    return render(request, "anagrafica/pages/mpq_form.html", {
        "form": form, "titolo": "Nuovo cliente/ente qualificante",
        "back_url": reverse("anagrafica:mpq_cliente_list"),
    })


@login_required
def mpq_cliente_edit(request, cliente_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import ClienteQualificanteForm
    cli = get_object_or_404(ClienteQualificante, pk=cliente_id)
    if request.method == "POST":
        form = ClienteQualificanteForm(request.POST, instance=cli)
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente/ente aggiornato.")
            return redirect("anagrafica:mpq_cliente_list")
    else:
        form = ClienteQualificanteForm(instance=cli)
    return render(request, "anagrafica/pages/mpq_form.html", {
        "form": form, "titolo": f"Modifica · {cli.nome}",
        "back_url": reverse("anagrafica:mpq_cliente_list"),
    })


def _abilitazione_form_ctx(form, processo, titolo, *, multi_select=False, ruoli_sel=(), std_sel=("QUALIFICATO",)):
    return {
        "form": form, "titolo": titolo, "processo": processo,
        "ruoli_catalogo": list(processo.ruoli.filter(codice_modulo="")),
        "ruoli_sel": {int(r) for r in ruoli_sel if str(r).isdigit()},
        "ruoli_standard": [(c, n, c in set(std_sel)) for c, n, _f in STANDARD_RUOLI],
        "dipendenti": _dipendenti_scelte(),
        "multi_select": multi_select,
        "back_url": reverse("anagrafica:mpq_processo_detail", args=[processo.id]),
    }


def _ruoli_dal_post(request, processo):
    """Ruoli scelti: quelli del modulo (Qualificato…) per codice + quelli propri per id."""
    from .services.mpq_ruoli import ruoli_dal_form

    return ruoli_dal_form(processo, request.POST.getlist("ruoli_standard"), request.POST.getlist("ruoli_processo"))


def bulk_abilita_processo(processo, legacy_ids, *, ruoli=None, stato,
                          data_ingresso=None, note="", ruoli_processo=()):
    """1.8 — Crea in blocco N ``AbilitazioneProcesso`` (dipendenti interni).

    Idempotente sul vincolo unico (persona×processo) e deduplica gli id ripetuti
    in ingresso. Ritorna ``(creati: list[AbilitazioneProcesso], gia_presenti: int)``.
    I ruoli e i metadati (stato/data/note) sono comuni a tutte le abilitazioni
    create nel batch. Non tocca le abilitazioni già esistenti.
    """
    from django.db import transaction

    from .services.mpq_ruoli import STANDARD, flag_da_ruoli, imposta_ruoli, ruolo_standard

    creati: list = []
    gia = 0
    seen: set = set()
    ruoli_processo = list(ruoli_processo)
    if not ruoli_processo:
        # Compatibilità: ruoli come booleani (default Qualificato).
        ruoli = ruoli if ruoli is not None else {"is_qualificato": True}
        ruoli_processo = [ruolo_standard(processo, c) for c, _n, campo in STANDARD
                          if ruoli.get(campo, campo == "is_qualificato")]
    flag = flag_da_ruoli(ruoli_processo)
    with transaction.atomic():
        for lid in legacy_ids:
            try:
                lid = int(lid)
            except (TypeError, ValueError):
                continue
            if lid in seen:
                continue
            seen.add(lid)
            ab, created = AbilitazioneProcesso.objects.get_or_create(
                legacy_anagrafica_id=lid,
                nominativo_esterno="",
                processo=processo,
                defaults={
                    **flag,
                    "stato": stato,
                    "data_ingresso": data_ingresso,
                    "note": note,
                },
            )
            if created:
                imposta_ruoli(ab, ruoli_processo)
                creati.append(ab)
            else:
                gia += 1
    return creati, gia


@login_required
def mpq_abilitazione_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import AbilitazioneProcessoForm
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    if request.method == "POST":
        form = AbilitazioneProcessoForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            from .services.mpq_ruoli import flag_da_ruoli, imposta_ruoli

            ruoli_scelti = _ruoli_dal_post(request, proc)
            stato = cd.get("stato", AbilitazioneProcesso.STATO_ATTIVA)
            if cd.get("tipo_persona") == AbilitazioneProcessoForm.TIPO_ESTERNO:
                # Qualificatore esterno: una persona per nominativo (nessun bulk).
                ab, created = AbilitazioneProcesso.objects.get_or_create(
                    legacy_anagrafica_id=0,
                    nominativo_esterno=cd.get("nominativo_esterno", ""),
                    processo=proc,
                    defaults={**flag_da_ruoli(ruoli_scelti), "stato": stato,
                              "data_ingresso": cd.get("data_ingresso"),
                              "note": cd.get("note", "")},
                )
                if created:
                    imposta_ruoli(ab, ruoli_scelti)
                    _mpq_log(request, processo=proc, abilitazione=ab, evento="Aggiunta abilitazione")
                    messages.success(request, "Abilitazione aggiunta.")
                else:
                    messages.warning(request, "La persona è già abilitata su questo processo.")
            else:
                # 1.8 — Dipendenti interni: selezione multipla → creazione in blocco.
                legacy_ids = request.POST.getlist("dipendente")
                creati, gia = bulk_abilita_processo(
                    proc, legacy_ids, stato=stato,
                    data_ingresso=cd.get("data_ingresso"), note=cd.get("note", ""),
                    ruoli_processo=ruoli_scelti,
                )
                for ab in creati:
                    _mpq_log(request, processo=proc, abilitazione=ab, evento="Aggiunta abilitazione")
                if creati:
                    messages.success(
                        request,
                        "Abilitazione aggiunta." if len(creati) == 1
                        else f"{len(creati)} abilitazioni aggiunte.",
                    )
                if gia:
                    messages.warning(
                        request,
                        f"{gia} già abilitat{'a' if gia == 1 else 'e'} su questo processo (saltat{'a' if gia == 1 else 'e'}).",
                    )
            return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)
    else:
        form = AbilitazioneProcessoForm()
    return render(request, "anagrafica/pages/mpq_abilitazione_form.html",
                  _abilitazione_form_ctx(form, proc, "Aggiungi persone abilitate",
                                         multi_select=True,
                                         ruoli_sel=request.POST.getlist("ruoli_processo"),
                                         std_sel=(request.POST.getlist("ruoli_standard")
                                                  if request.method == "POST" else ("QUALIFICATO",))))


@login_required
def mpq_abilitazione_edit(request, ab_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import AbilitazioneProcessoForm
    ab = get_object_or_404(
        AbilitazioneProcesso.objects.select_related("processo"), pk=ab_id)
    if request.method == "POST":
        form = AbilitazioneProcessoForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            ab.legacy_anagrafica_id = cd["legacy_anagrafica_id"]
            ab.nominativo_esterno = cd.get("nominativo_esterno", "")
            ab.stato = cd.get("stato", ab.stato)
            ab.data_ingresso = cd.get("data_ingresso")
            ab.note = cd.get("note", "")
            ab.save()
            from .services.mpq_ruoli import imposta_ruoli

            imposta_ruoli(ab, _ruoli_dal_post(request, ab.processo))
            _mpq_log(request, processo=ab.processo, abilitazione=ab, evento="Modifica abilitazione")
            messages.success(request, "Abilitazione aggiornata.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=ab.processo_id)
    else:
        form = AbilitazioneProcessoForm(initial={
            "tipo_persona": (AbilitazioneProcessoForm.TIPO_ESTERNO if ab.nominativo_esterno
                             else AbilitazioneProcessoForm.TIPO_INTERNO),
            "dipendente": ab.legacy_anagrafica_id or "",
            "nominativo_esterno": ab.nominativo_esterno,
            "stato": ab.stato, "data_ingresso": ab.data_ingresso, "note": ab.note,
        })
    ruoli_sel = (request.POST.getlist("ruoli_processo") if request.method == "POST"
                 else [r.pk for r in ab.ruoli_processo.all()])
    std_sel = (request.POST.getlist("ruoli_standard") if request.method == "POST"
               else [r.codice_modulo for r in ab.ruoli_processo.all() if r.codice_modulo])
    return render(request, "anagrafica/pages/mpq_abilitazione_form.html",
                  _abilitazione_form_ctx(form, ab.processo, "Modifica abilitazione",
                                         ruoli_sel=ruoli_sel, std_sel=std_sel))


@login_required
@require_POST
def mpq_abilitazione_delete(request, ab_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    ab = get_object_or_404(AbilitazioneProcesso, pk=ab_id)
    pid = ab.processo_id
    ab.delete()
    messages.success(request, "Abilitazione rimossa.")
    return redirect("anagrafica:mpq_processo_detail", processo_id=pid)


@login_required
def mpq_certificazione_add(request, ab_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import CertificazioneIndividualeForm
    ab = get_object_or_404(
        AbilitazioneProcesso.objects.select_related("processo"), pk=ab_id)
    if request.method == "POST":
        form = CertificazioneIndividualeForm(request.POST, request.FILES)
        if form.is_valid():
            cert = form.save(commit=False)
            cert.abilitazione = ab
            if cert.documento:
                cert.documento_nome_originale = getattr(cert.documento, "name", "")[:255]
            cert.save()
            messages.success(request, "Certificazione aggiunta.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=ab.processo_id)
    else:
        form = CertificazioneIndividualeForm()
    return render(request, "anagrafica/pages/mpq_form.html", {
        "form": form, "titolo": "Aggiungi certificazione individuale",
        "multipart": True,
        "back_url": reverse("anagrafica:mpq_processo_detail", args=[ab.processo_id]),
    })


@login_required
@require_POST
def mpq_certificazione_delete(request, cert_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    cert = get_object_or_404(
        CertificazioneIndividuale.objects.select_related("abilitazione"), pk=cert_id)
    pid = cert.abilitazione.processo_id
    cert.delete()
    messages.success(request, "Certificazione rimossa.")
    return redirect("anagrafica:mpq_processo_detail", processo_id=pid)


@login_required
@require_POST
def mpq_riferimento_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RiferimentoProcessoForm
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    form = RiferimentoProcessoForm(request.POST)
    if form.is_valid():
        rif = form.save(commit=False)
        rif.processo = proc
        rif.save()
        messages.success(request, "Riferimento aggiunto.")
    else:
        messages.error(request, "Codice riferimento non valido.")
    return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)


@login_required
@require_POST
def mpq_riferimento_delete(request, rif_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .models_mpq import RiferimentoProcesso
    rif = get_object_or_404(RiferimentoProcesso, pk=rif_id)
    pid = rif.processo_id
    rif.delete()
    messages.success(request, "Riferimento rimosso.")
    return redirect("anagrafica:mpq_processo_detail", processo_id=pid)


# ── Attrezzature del processo (asset) ────────────────────────────────────────


@login_required
@require_POST
def mpq_attrezzatura_add(request, processo_id: int):
    """Collega un asset (per tag o numero interno) come attrezzatura del processo."""
    if not _check_manage(request):
        return _mpq_denied(request)
    from assets.models import Asset

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    codice = (request.POST.get("asset") or "").strip()[:64]
    asset = None
    if codice:
        asset = (Asset.objects.filter(asset_tag__iexact=codice).first()
                 or Asset.objects.filter(internal_number__iexact=codice).first())
    if asset is None:
        messages.error(request, f"Nessun asset con tag o numero interno «{codice}».")
    elif proc.qualifiche_macchina.filter(asset=asset).exclude(stato="RITIRATA").exists():
        messages.info(request, f"{asset.asset_tag} è già una macchina del processo.")
    else:
        from .services.mpq_macchine import collega

        collega(proc, asset, user=request.user)
        _mpq_log(request, processo=proc, evento=f"Attrezzatura collegata: {asset.asset_tag}",
                 dettaglio=asset.name)
        messages.success(request, f"{asset.asset_tag} collegato al processo: registra la qualifica.")
    return redirect(reverse("anagrafica:mpq_processo_detail", args=[proc.id]) + "#attrezzature")


@login_required
@require_POST
def mpq_attrezzatura_remove(request, processo_id: int, asset_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from assets.models import Asset

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    asset = get_object_or_404(Asset, pk=asset_id)
    if asset.processi_qualificati.filter(pk=proc.pk).exists():
        from .services.mpq_macchine import scollega

        scollega(proc, asset, user=request.user)
        _mpq_log(request, processo=proc, evento=f"Attrezzatura scollegata: {asset.asset_tag}",
                 dettaglio=asset.name)
        messages.success(request, f"{asset.asset_tag} scollegato dal processo.")
    return redirect(reverse("anagrafica:mpq_processo_detail", args=[proc.id]) + "#attrezzature")


# ── Requisiti generici tipizzati del processo (1.14) ──────────────────────────

@login_required
def mpq_requisito_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoQualificaForm
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    if request.method == "POST":
        form = RequisitoQualificaForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.processo = proc
            req.save()
            _mpq_log(request, processo=proc, evento="Requisito aggiunto",
                     dettaglio=f"{req.get_tipo_display()}: {req.descrizione}")
            messages.success(request, "Requisito aggiunto.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)
        messages.error(request, "Dati requisito non validi.")
    else:
        form = RequisitoQualificaForm()
    return render(request, "anagrafica/pages/mpq_requisito_form.html", {
        "form": form, "processo": proc, "titolo": "Nuovo requisito",
    })


@login_required
def mpq_requisito_edit(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoQualificaForm
    req = get_object_or_404(RequisitoQualifica.objects.select_related("processo"), pk=req_id)
    proc = req.processo
    if request.method == "POST":
        form = RequisitoQualificaForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            _mpq_log(request, processo=proc, evento="Requisito modificato",
                     dettaglio=f"{req.get_tipo_display()}: {req.descrizione}")
            messages.success(request, "Requisito aggiornato.")
            return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)
        messages.error(request, "Dati requisito non validi.")
    else:
        form = RequisitoQualificaForm(instance=req)
    return render(request, "anagrafica/pages/mpq_requisito_form.html", {
        "form": form, "processo": proc, "titolo": "Modifica requisito",
    })


@login_required
@require_POST
def mpq_requisito_delete(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    req = get_object_or_404(RequisitoQualifica.objects.select_related("processo"), pk=req_id)
    proc = req.processo
    dettaglio = f"{req.get_tipo_display()}: {req.descrizione}"
    req.delete()
    _mpq_log(request, processo=proc, evento="Requisito rimosso", dettaglio=dettaglio)
    messages.success(request, "Requisito rimosso.")
    return redirect("anagrafica:mpq_processo_detail", processo_id=proc.id)


@login_required
@require_POST
def mpq_requisito_sposta(request, req_id: int):
    """Sposta un requisito «per persona» registrato fra quelli del processo in «Cosa serve a una persona».

    Lo stato uguale per tutti non si copia (ogni persona va verificata): si apre il
    requisito nuovo per completarlo (corso, visita, ricorrenza, ruoli).
    """
    if not _check_manage(request):
        return _mpq_denied(request)
    from django.db import transaction

    from .models_mpq import RequisitoPersona

    req = get_object_or_404(RequisitoQualifica.objects.select_related("processo"), pk=req_id)
    tipo = RequisitoQualifica.TIPO_IN_REQUISITO_PERSONA.get(req.tipo)
    if tipo is None:
        messages.error(request, "Questo requisito vale per tutto il processo: resta qui.")
        return redirect("anagrafica:mpq_processo_detail", processo_id=req.processo_id)
    proc = req.processo
    periodicita = req.periodicita_mesi or None
    with transaction.atomic():
        nuovo = RequisitoPersona.objects.create(
            processo=proc, tipo=tipo, descrizione=req.descrizione[:255],
            ricorrenza=(RequisitoPersona.RICORRENZA_RICORRENTE if periodicita
                        else RequisitoPersona.RICORRENZA_UNA_TANTUM),
            frequenza_mesi=periodicita, bloccante=req.obbligatorio, attivo=req.attivo,
            note="\n".join(x for x in (req.rif_normativo, req.note,
                                        "Spostato da «Requisiti del processo».") if x),
        )
        dettaglio = f"{req.get_tipo_display()}: {req.descrizione}"
        req.delete()
    _mpq_log(request, processo=proc, evento="Requisito spostato fra i requisiti persona",
             dettaglio=dettaglio)
    messages.success(request, "Spostato in «Cosa serve a una persona»: completa ruoli e dettagli e salva.")
    return redirect("anagrafica:mpq_requisito_persona_edit", req_id=nuovo.id)


# ── Crea-al-volo (JSON) di corso/visita/DPI dal form processo (gated manage) ──
# Ritornano {ok, id, label} così l'enhancer li appende al <select> e li seleziona.

@login_required
@require_POST
def mpq_quickadd_visita(request):
    if not _check_manage(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    from .models import TipoVisitaMedica
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        return JsonResponse({"ok": False, "error": "Il nome è obbligatorio."}, status=400)
    try:
        durata = max(1, int(request.POST.get("durata_mesi") or 12))
    except (TypeError, ValueError):
        durata = 12
    obj, _ = TipoVisitaMedica.objects.get_or_create(nome=nome, defaults={"durata_mesi": durata})
    return JsonResponse({"ok": True, "id": obj.pk, "label": obj.nome})


@login_required
@require_POST
def mpq_quickadd_dpi(request):
    if not _check_manage(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    try:
        from dpi.models import CategoriaDPI
    except Exception:
        return JsonResponse({"ok": False, "error": "Modulo DPI non disponibile."}, status=400)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        return JsonResponse({"ok": False, "error": "Il nome è obbligatorio."}, status=400)
    obj, _ = CategoriaDPI.objects.get_or_create(nome=nome)
    return JsonResponse({"ok": True, "id": obj.pk, "label": obj.nome})


@login_required
@require_POST
def mpq_quickadd_corso(request):
    if not _check_manage(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    import re as _re
    from .models import TrainingCourse, TrainingPlan
    titolo = (request.POST.get("titolo") or "").strip()[:300]
    if not titolo:
        return JsonResponse({"ok": False, "error": "Il titolo è obbligatorio."}, status=400)
    try:
        ore = max(0.5, float(request.POST.get("durata_ore_teorica") or 1))
    except (TypeError, ValueError):
        ore = 1
    try:
        validita = max(0, int(request.POST.get("validita_mesi") or 0))
    except (TypeError, ValueError):
        validita = 0
    # Piano: quello scelto, altrimenti primo attivo, altrimenti un piano dedicato.
    piano = None
    pid = (request.POST.get("piano") or "").strip()
    if pid.isdigit():
        piano = TrainingPlan.objects.filter(pk=int(pid)).first()
    if piano is None:
        piano = TrainingPlan.objects.filter(is_active=True).order_by("id").first()
    if piano is None:
        piano = TrainingPlan.objects.create(
            codice="MPQ", nome="Requisiti processi qualificati", created_by=request.user)
    # Categoria di rischio (opzionale) per la derivazione DPI/fattori.
    categoria = None
    cid = (request.POST.get("categoria") or "").strip()
    if cid.isdigit():
        try:
            from .models_rischi import CategoriaCorso
            categoria = CategoriaCorso.objects.filter(pk=int(cid)).first()
        except Exception:
            categoria = None
    base = _re.sub(r"[^A-Z0-9]+", "-", titolo.upper()).strip("-")[:22] or "CORSO"
    codice, n = base, 1
    while TrainingCourse.objects.filter(codice=codice).exists():
        n += 1
        codice = f"{base[:18]}-{n}"
    corso = TrainingCourse.objects.create(
        piano=piano, categoria=categoria, codice=codice, titolo=titolo,
        durata_ore_teorica=ore, validita_mesi=validita, stato="BOZZA",
        created_by=request.user)
    # Il corso nasce come BOZZA (incompleto): restituiamo il link per completarlo.
    return JsonResponse({
        "ok": True, "id": corso.pk, "label": corso.titolo, "bozza": True,
        "edit_url": reverse("anagrafica:formazione_corso_detail", args=[corso.pk]),
    })
