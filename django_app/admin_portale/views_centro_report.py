"""Centro report: catalogo, registro delle emissioni e profili di layout.

La logica sta in :mod:`core.report_centro`; qui c'è il guscio HTTP della
pagina in Amministrazione (schede Catalogo, Registro, Layout, Guida).
"""
from __future__ import annotations

import csv
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from core.audit import log_action
from django.contrib.auth import get_user_model

from core import naming
from core.models import ReportAssegnazioneLayout, ReportEmissione, ReportPianificazione, ReportProfiloLayout
from core.report_centro import catalogo, layout, pianificazione, registro

from .decorators import legacy_admin_required

SCHEDE = ("catalogo", "registro", "layout", "pianificazioni", "guida")
FINESTRE_GIORNI = (7, 30, 90, 365)
CAMPI_PROFILO = (
    "nome", "descrizione", "logo_url", "colore_primario", "colore_accento", "piede_pagina", "filigrana",
)


def _url_pagina(voce) -> str:
    if not voce.pagina:
        return ""
    try:
        return reverse(voce.pagina)
    except NoReverseMatch:
        return ""


def _int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _assegnazioni() -> dict[tuple[str, str], ReportProfiloLayout]:
    try:
        return {
            (a.ambito, a.chiave): a.profilo
            for a in ReportAssegnazioneLayout.objects.select_related("profilo")
        }
    except DatabaseError:
        return {}


def _contesto_catalogo() -> dict:
    da = timezone.now() - timedelta(days=30)
    try:
        ultime = {
            r["report_chiave"]: r
            for r in ReportEmissione.objects.exclude(report_chiave="")
            .values("report_chiave")
            .annotate(ultima=Max("created_at"), recenti=Count("id", filter=Q(created_at__gte=da)))
            .order_by()
        }
        formati = {}
        for r in (
            ReportEmissione.objects.exclude(report_chiave="")
            .values("report_chiave", "formato")
            .annotate(n=Count("id"))
            .order_by()
        ):
            formati.setdefault(r["report_chiave"], []).append(r["formato"])
        da_catalogare = list(
            ReportEmissione.objects.filter(report_chiave="")
            .values("route_name")
            .annotate(n=Count("id"), ultima=Max("created_at"))
            .order_by("-ultima")[:50]
        )
    except DatabaseError:
        ultime, formati, da_catalogare = {}, {}, []
    assegnazioni = _assegnazioni()
    gruppi = []
    totale = personali = 0
    for modulo in catalogo.moduli():
        righe = []
        profilo_modulo = assegnazioni.get((ReportAssegnazioneLayout.AMBITO_MODULO, modulo.chiave))
        for voce in modulo.voci:
            totale += 1
            personali += int(voce.dati_personali)
            stat = ultime.get(voce.chiave) or {}
            profilo = None
            if voce.accetta_profilo:
                profilo = assegnazioni.get((ReportAssegnazioneLayout.AMBITO_VOCE, voce.chiave)) or profilo_modulo
            righe.append({
                "voce": voce,
                "url": _url_pagina(voce),
                "ultima": stat.get("ultima"),
                "recenti": stat.get("recenti") or 0,
                "formati_osservati": sorted(formati.get(voce.chiave, [])),
                "profilo": profilo,
            })
        gruppi.append({"modulo": modulo, "righe": righe})
    return {
        "gruppi": gruppi,
        "totale_voci": totale,
        "totale_personali": personali,
        "totale_moduli": len(gruppi),
        "da_catalogare": da_catalogare,
    }


def _filtri_registro(request) -> dict:
    giorni = _int(request.GET.get("giorni"), 30)
    if giorni not in FINESTRE_GIORNI:
        giorni = 30
    return {
        "giorni": giorni,
        "modulo": str(request.GET.get("modulo") or "").strip()[:80],
        "formato": str(request.GET.get("formato") or "").strip()[:10],
        "personali": request.GET.get("personali") == "1",
        "voce": str(request.GET.get("voce") or "").strip()[:120],
        "q": str(request.GET.get("q") or "").strip()[:100],
    }


def _queryset_registro(filtri: dict):
    qs = ReportEmissione.objects.filter(created_at__gte=timezone.now() - timedelta(days=filtri["giorni"]))
    if filtri["modulo"]:
        qs = qs.filter(modulo=filtri["modulo"])
    if filtri["formato"]:
        qs = qs.filter(formato=filtri["formato"])
    if filtri["personali"]:
        qs = qs.filter(dati_personali=True)
    if filtri["voce"]:
        qs = qs.filter(report_chiave=filtri["voce"])
    if filtri["q"]:
        q = filtri["q"]
        qs = qs.filter(
            Q(utente_display__icontains=q) | Q(nome_file__icontains=q) | Q(titolo__icontains=q)
            | Q(sha256=q.lower()) | Q(route_name=q)
        )
    return qs.order_by("-created_at", "-id")


def _impronte_archivio_hr(impronte: set[str]) -> set[str]:
    """Impronte che hanno una copia nell'archivio della reportistica HR.

    ``ReportGenerato`` (anagrafica) conserva il file per riscaricarlo; il registro
    conserva solo chi lo ha scaricato. Stessa impronta = stesso file: così dal
    registro si arriva alla copia archiviata senza duplicare i dati.
    """
    if not impronte:
        return set()
    try:
        from anagrafica.models_reportistica import ReportGenerato

        return set(ReportGenerato.objects.filter(sha256__in=impronte).values_list("sha256", flat=True))
    except (ImportError, DatabaseError):
        return set()


def _parametri_leggibili(parametri) -> list[str]:
    """``{"anno": "2026", "_route": {"pk": "41"}}`` → ``["anno = 2026", "pk = 41"]``."""
    righe = []
    for chiave, valore in (parametri or {}).items():
        if isinstance(valore, dict):
            righe.extend(f"{k} = {v}" for k, v in valore.items())
        elif isinstance(valore, list):
            righe.append(f"{chiave} = {', '.join(str(v) for v in valore)}")
        else:
            righe.append(f"{chiave} = {valore}")
    return righe


def _contesto_registro(request) -> dict:
    filtri = _filtri_registro(request)
    qs = _queryset_registro(filtri)
    try:
        page = Paginator(qs, 50).get_page(request.GET.get("page"))
        totale = page.paginator.count
        personali = qs.filter(dati_personali=True).count()
    except DatabaseError:
        page, totale, personali = None, 0, 0
    emissioni = list(page.object_list) if page else []
    in_archivio_hr = _impronte_archivio_hr({e.sha256 for e in emissioni if e.sha256})
    righe = []
    for e in emissioni:
        righe.append({
            "e": e,
            "voce": catalogo.voce_per_chiave(e.report_chiave),
            "parametri": _parametri_leggibili(e.parametri),
            "in_archivio_hr": e.sha256 in in_archivio_hr,
        })
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "filtri": filtri,
        "page": page,
        "righe": righe,
        "totale": totale,
        "totale_personali": personali,
        "finestre": FINESTRE_GIORNI,
        "moduli": catalogo.moduli(),
        "formati": ReportEmissione.FORMATO_CHOICES,
        "querystring": query.urlencode(),
        "conservazione_giorni": registro.giorni_conservazione(),
        "conservazione_max": registro.MAX_GIORNI,
    }


def _contesto_layout() -> dict:
    try:
        profili = list(ReportProfiloLayout.objects.annotate(n_assegnazioni=Count("assegnazioni")))
    except DatabaseError:
        profili = []
    assegnazioni = _assegnazioni()
    moduli = []
    for modulo in catalogo.moduli():
        voci = [v for v in modulo.voci if v.accetta_profilo]
        if not voci:
            continue
        moduli.append({
            "modulo": modulo,
            "profilo": assegnazioni.get((ReportAssegnazioneLayout.AMBITO_MODULO, modulo.chiave)),
            "voci": [
                {"voce": v, "profilo": assegnazioni.get((ReportAssegnazioneLayout.AMBITO_VOCE, v.chiave))}
                for v in voci
            ],
        })
    return {"profili": profili, "moduli_layout": moduli}


def _nominativo(u) -> str:
    return naming.nome_completo(u.first_name, u.last_name) or u.username


def _utenti_destinatari():
    User = get_user_model()
    utenti = list(
        User.objects.filter(is_active=True).exclude(email="").only("id", "username", "first_name", "last_name", "email")
    )
    utenti.sort(key=_nominativo)
    return [{"id": u.pk, "nome": _nominativo(u), "email": u.email} for u in utenti]


def _contesto_pianificazioni(request) -> dict:
    righe = []
    try:
        elenco = list(ReportPianificazione.objects.select_related("proprietario").prefetch_related("destinatari"))
    except DatabaseError:
        elenco = []
    for p in elenco:
        voce = catalogo.voce_per_chiave(p.voce_chiave)
        righe.append({
            "p": p,
            "voce": voce,
            "variante": voce.variante(p.variante) if voce else None,
            "frequenza": pianificazione.descrivi_frequenza(p),
            "destinatari": [_nominativo(u) for u in p.destinatari.all()],
            "proprietario": _nominativo(p.proprietario) if p.proprietario else "",
        })
    modifica_pk = _int(request.GET.get("pianificazione"), 0)
    modifica = next((r["p"] for r in righe if r["p"].pk == modifica_pk), None)
    return {
        "pianificazioni": righe,
        "pianificazione_modifica": modifica,
        "variante_scelta": f"{modifica.voce_chiave}|{modifica.variante}" if modifica else "",
        "destinatari_scelti": {u.pk for u in modifica.destinatari.all()} if modifica else set(),
        "varianti": [
            {"valore": f"{v.chiave}|{var.chiave}", "voce": v, "variante": var}
            for v, var in catalogo.varianti_pianificabili()
        ],
        "utenti": _utenti_destinatari(),
        "giorni_settimana": list(enumerate(("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"))),
        "giorni_mese": list(range(1, 29)),
        "ore": list(range(0, 24)),
    }


@legacy_admin_required
def centro_report(request):
    scheda = str(request.GET.get("tab") or "catalogo").strip().lower()
    if scheda not in SCHEDE:
        scheda = "catalogo"
    context = {"page_title": "Centro report", "scheda": scheda}
    if scheda == "catalogo":
        context.update(_contesto_catalogo())
    elif scheda == "registro":
        context.update(_contesto_registro(request))
    elif scheda == "layout":
        context.update(_contesto_layout())
        modifica = _int(request.GET.get("profilo"), 0)
        context["profilo_modifica"] = (
            ReportProfiloLayout.objects.filter(pk=modifica).first() if modifica else None
        )
    elif scheda == "pianificazioni":
        context.update(_contesto_pianificazioni(request))
    return render(request, "admin_portale/pages/centro_report.html", context)


@legacy_admin_required
def centro_report_registro_csv(request):
    """CSV del registro con gli stessi filtri della scheda (anche questo finisce nel registro)."""
    filtri = _filtri_registro(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="registro-emissioni-report.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow([
        "Data", "Utente", "Impersonato", "Report", "Modulo", "Formato", "File", "Byte",
        "SHA-256", "Dati personali", "Profilo layout", "Parametri", "Route",
    ])
    for e in _queryset_registro(filtri)[:20000]:
        writer.writerow([
            timezone.localtime(e.created_at).strftime("%d/%m/%Y %H:%M:%S"),
            e.utente_display, e.impersonato_display, e.titolo, e.modulo, e.formato, e.nome_file,
            e.dimensione_byte if e.dimensione_byte is not None else "", e.sha256,
            "sì" if e.dati_personali else "no", e.profilo_layout, e.parametri, e.route_name,
        ])
    log_action(request, "centro_report_registro_csv", "admin_portale", filtri)
    return response


def _salva_profilo(request) -> tuple[ReportProfiloLayout | None, str]:
    pk = _int(request.POST.get("profilo_id"), 0)
    profilo = ReportProfiloLayout.objects.filter(pk=pk).first() if pk else ReportProfiloLayout()
    if pk and profilo is None:
        return None, "Profilo non trovato."
    for campo in CAMPI_PROFILO:
        setattr(profilo, campo, str(request.POST.get(campo) or "").strip())
    profilo.colore_primario = profilo.colore_primario.lower()
    profilo.colore_accento = profilo.colore_accento.lower()
    profilo.mostra_data_generazione = request.POST.get("mostra_data_generazione") == "1"
    profilo.mostra_numero_pagina = request.POST.get("mostra_numero_pagina") == "1"
    profilo.is_active = request.POST.get("is_active") == "1"
    if not profilo.nome:
        return None, "Il profilo ha bisogno di un nome."
    if profilo.logo_url and not profilo.logo_url.startswith("/media/"):
        return None, "Il logo deve essere un percorso /media/… (PNG o JPG)."
    try:
        profilo.full_clean()
    except ValidationError as exc:
        return None, " ".join(m for msgs in exc.message_dict.values() for m in msgs)
    profilo.save()
    return profilo, ""


def _salva_assegnazioni(request) -> int:
    validi = {p.pk: p for p in ReportProfiloLayout.objects.all()}
    chiavi_modulo = {m.chiave for m in catalogo.moduli()}
    chiavi_voce = {v.chiave for v in catalogo.voci() if v.accetta_profilo}
    cambi = 0
    with transaction.atomic():
        for nome, valore in request.POST.items():
            if nome.startswith("modulo__"):
                ambito, chiave, ammesse = ReportAssegnazioneLayout.AMBITO_MODULO, nome[8:], chiavi_modulo
            elif nome.startswith("voce__"):
                ambito, chiave, ammesse = ReportAssegnazioneLayout.AMBITO_VOCE, nome[6:], chiavi_voce
            else:
                continue
            if chiave not in ammesse:
                continue
            profilo = validi.get(_int(valore, 0))
            esistente = ReportAssegnazioneLayout.objects.filter(ambito=ambito, chiave=chiave).first()
            if profilo is None:
                if esistente is not None:
                    esistente.delete()
                    cambi += 1
            elif esistente is None:
                ReportAssegnazioneLayout.objects.create(ambito=ambito, chiave=chiave, profilo=profilo)
                cambi += 1
            elif esistente.profilo_id != profilo.pk:
                esistente.profilo = profilo
                esistente.save(update_fields=["profilo", "updated_at"])
                cambi += 1
    return cambi


def _salva_pianificazione(request) -> tuple[ReportPianificazione | None, str]:
    pk = _int(request.POST.get("pianificazione_id"), 0)
    p = ReportPianificazione.objects.filter(pk=pk).first() if pk else ReportPianificazione(proprietario=request.user)
    if pk and p is None:
        return None, "Pianificazione non trovata."
    voce_chiave, _, variante_chiave = str(request.POST.get("variante") or "").partition("|")
    voce = catalogo.voce_per_chiave(voce_chiave)
    if voce is None or voce.variante(variante_chiave) is None:
        return None, "Scegli il report da inviare."
    nome = str(request.POST.get("nome") or "").strip()[:120]
    if not nome:
        return None, "La pianificazione ha bisogno di un nome."
    frequenza = str(request.POST.get("frequenza") or "")
    if frequenza not in dict(ReportPianificazione.FREQ_CHOICES):
        return None, "Frequenza non valida."
    User = get_user_model()
    ids = [i for i in (_int(x, 0) for x in request.POST.getlist("destinatari")) if i]
    destinatari = list(User.objects.filter(pk__in=ids, is_active=True).exclude(email=""))
    if not destinatari:
        return None, "Scegli almeno un destinatario con email."
    giorno_settimana = min(max(_int(request.POST.get("giorno_settimana"), 0), 0), 6)
    giorno_mese = min(max(_int(request.POST.get("giorno_mese"), 1), 1), 28)
    ora = min(max(_int(request.POST.get("ora"), 7), 0), 23)
    cambia_calendario = (
        not p.pk or p.frequenza != frequenza or p.giorno_settimana != giorno_settimana
        or p.giorno_mese != giorno_mese or p.ora != ora
    )
    p.nome = nome
    p.voce_chiave = voce.chiave
    p.variante = variante_chiave
    p.frequenza = frequenza
    p.giorno_settimana = giorno_settimana
    p.giorno_mese = giorno_mese
    p.ora = ora
    p.attiva = request.POST.get("attiva") == "1"
    if cambia_calendario or p.prossima_esecuzione is None:
        p.prossima_esecuzione = pianificazione.calcola_prossima(p)
    p.save()
    p.destinatari.set(destinatari)
    return p, ""


def _azione_pianificazione(request, azione: str):
    url = reverse("admin_portale:centro_report") + "?tab=pianificazioni"
    if azione == "pianificazione_salva":
        p, errore = _salva_pianificazione(request)
        if errore:
            messages.error(request, errore)
            pk = _int(request.POST.get("pianificazione_id"), 0)
            return redirect(url + (f"&pianificazione={pk}" if pk else ""))
        variante = catalogo.voce_per_chiave(p.voce_chiave).variante(p.variante)
        _, esclusi = pianificazione.destinatari_ammessi(p, reverse(variante.route))
        log_action(request, "centro_report_pianificazione_salva", "admin_portale", {
            "pianificazione": p.nome, "report": p.voce_chiave, "variante": p.variante,
            "destinatari": p.destinatari.count(),
        }, oggetto=p)
        prossima = timezone.localtime(p.prossima_esecuzione).strftime("%d/%m/%Y %H:%M")
        messages.success(request, f"Pianificazione «{p.nome}» salvata: prossimo invio {prossima}.")
        if esclusi:
            messages.warning(
                request,
                "Non riceveranno il report (senza accesso a quella pagina o senza email): "
                + ", ".join(_nominativo(u) for u in esclusi[:10]) + ".",
            )
        return redirect(url)
    p = get_object_or_404(ReportPianificazione, pk=_int(request.POST.get("pianificazione_id"), 0))
    if azione == "pianificazione_esegui":
        esito = pianificazione.esegui(p, manuale=True)
        log_action(request, "centro_report_pianificazione_esegui", "admin_portale",
                   {"pianificazione": p.nome, "esito": esito.esito, "messaggio": esito.messaggio}, oggetto=p)
        livello = {p.ESITO_OK: messages.SUCCESS, p.ESITO_PARZIALE: messages.WARNING}.get(esito.esito, messages.ERROR)
        messages.add_message(request, livello, f"«{p.nome}»: {esito.messaggio}")
    elif azione == "pianificazione_attiva":
        p.attiva = not p.attiva
        if p.attiva:
            p.prossima_esecuzione = pianificazione.calcola_prossima(p)
        p.save(update_fields=["attiva", "prossima_esecuzione", "updated_at"])
        log_action(request, "centro_report_pianificazione_attiva", "admin_portale",
                   {"pianificazione": p.nome, "attiva": p.attiva}, oggetto=p)
        messages.success(request, f"«{p.nome}» {'riattivata' if p.attiva else 'sospesa'}.")
    elif azione == "pianificazione_elimina":
        nome = p.nome
        p.delete()
        log_action(request, "centro_report_pianificazione_elimina", "admin_portale", {"pianificazione": nome})
        messages.success(request, f"Pianificazione «{nome}» eliminata.")
    else:
        messages.error(request, "Azione non riconosciuta.")
    return redirect(url)


@legacy_admin_required
@csrf_protect
@require_POST
def centro_report_azione(request):
    azione = str(request.POST.get("azione") or "").strip()
    if azione.startswith("pianificazione_"):
        return _azione_pianificazione(request, azione)
    url_layout = reverse("admin_portale:centro_report") + "?tab=layout"
    if azione == "profilo_salva":
        profilo, errore = _salva_profilo(request)
        if errore:
            messages.error(request, errore)
            pk = _int(request.POST.get("profilo_id"), 0)
            return redirect(url_layout + (f"&profilo={pk}" if pk else ""))
        log_action(request, "centro_report_profilo_salva", "admin_portale", {"profilo": profilo.nome}, oggetto=profilo)
        messages.success(request, f"Profilo «{profilo.nome}» salvato.")
        return redirect(url_layout)
    if azione == "profilo_elimina":
        profilo = get_object_or_404(ReportProfiloLayout, pk=_int(request.POST.get("profilo_id"), 0))
        nome = profilo.nome
        n = profilo.assegnazioni.count()
        profilo.delete()
        log_action(request, "centro_report_profilo_elimina", "admin_portale", {"profilo": nome, "assegnazioni": n})
        messages.success(request, f"Profilo «{nome}» eliminato" + (f" (tolte {n} assegnazioni)." if n else "."))
        return redirect(url_layout)
    if azione == "assegnazioni_salva":
        cambi = _salva_assegnazioni(request)
        log_action(request, "centro_report_assegnazioni", "admin_portale", {"modifiche": cambi})
        messages.success(request, f"Assegnazioni salvate ({cambi} modifiche)." if cambi else "Nessuna modifica alle assegnazioni.")
        return redirect(url_layout)
    if azione == "conservazione":
        giorni = registro.imposta_conservazione(_int(request.POST.get("giorni"), registro.RETENTION_DEFAULT))
        log_action(request, "centro_report_conservazione", "admin_portale", {"giorni": giorni})
        messages.success(
            request,
            "Il registro si conserva per sempre." if giorni == 0 else f"Il registro conserva le emissioni per {giorni} giorni.",
        )
        return redirect(reverse("admin_portale:centro_report") + "?tab=registro")
    messages.error(request, "Azione non riconosciuta.")
    return redirect(reverse("admin_portale:centro_report"))


@legacy_admin_required
def centro_report_anteprima(request, pk: int):
    """Anteprima PDF di un profilo: lo stesso documento dimostrativo del Template PDF."""
    from .views import pdf_template_preview

    profilo = get_object_or_404(ReportProfiloLayout, pk=pk)
    layout.forza_profilo(request, profilo)
    return pdf_template_preview(request)
