"""Pagine del Registro accessi, dentro il SOC (``/soc/registro-log/…``, rotte ``security:registro_log*``).

Lettura: chi vede il SOC. Scrittura (fonti, impostazioni, amministratori, verifiche,
download dell'archivio): chi configura il SOC. Il download dei file d'archivio passa
dall'audit del portale.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from security.services.configuration import can_manage_security_config

from . import archivio, regole
from .forms import AmministratoreForm, ApparatoForm, FonteForm, ImpostazioniForm, IndagineForm, VerificaForm
from .models import (
    AccountAD,
    AmministratoreSistema,
    ApparatoInfra,
    EventoRegistro,
    FonteLog,
    Impostazioni,
    Indagine,
    Interruzione,
    SigilloGiorno,
    VerificaAnnuale,
)

MODULO = "registro_log"


def _puo_configurare(request) -> bool:
    return bool(can_manage_security_config(request.user))


def _nego():
    return HttpResponseForbidden("Serve il permesso di configurare il Security Center.")


def _utente(request) -> str:
    return (request.user.get_username() or "")[:150]


# ── Panoramica ───────────────────────────────────────────────────────────────


def _passi(imp, fonti, battito, ads_n, copia_ok) -> list[dict]:
    """«Come iniziare»: cosa manca perché il registro valga per il Garante e la ISO 27001."""
    return [
        {"fatto": imp.attivo, "testo": "Accendere la raccolta", "dove": reverse("security:registro_log_fonti") + "#impostazioni"},
        {"fatto": fonti.filter(ruolo="dc").exists(), "testo": "Aggiungere i controller di dominio",
         "dove": reverse("security:registro_log_fonti") + "?nuova=1#nuova"},
        {"fatto": battito["vivo"], "testo": "Avviare il raccoglitore come servizio di Windows (Setup Wizard o script)",
         "dove": reverse("security:registro_log_fonti") + "#servizio"},
        {"fatto": copia_ok, "testo": "Impostare la seconda copia dell'archivio (NAS o SharePoint)",
         "dove": reverse("security:registro_log_fonti") + "#impostazioni"},
        {"fatto": ads_n > 0, "testo": "Inserire gli amministratori di sistema con la nomina",
         "dove": reverse("security:registro_log_ads")},
        {"fatto": fonti.filter(tipo=FonteLog.TIPO_SYSLOG).exists(), "testo": "Collegare ESXi, switch e firewall via syslog",
         "dove": reverse("security:registro_log_fonti") + "?nuova=1#nuova"},
    ]


def panoramica(request):
    from .ciclo import battito

    imp = Impostazioni.corrente()
    fonti = FonteLog.objects.all()
    b = battito()
    ora = timezone.now()
    oggi_inizio = timezone.localtime(ora).replace(hour=0, minute=0, second=0, microsecond=0)
    ieri = ora - timedelta(hours=24)
    eventi_24 = EventoRegistro.objects.filter(quando__gte=ieri).exclude(categoria__in=regole.CATEGORIE_RISERVATE)
    conta = dict(eventi_24.values_list("categoria").annotate(n=Count("id")).values_list("categoria", "n"))
    ultimo_sigillo = SigilloGiorno.objects.order_by("-giorno").first()
    non_integri = SigilloGiorno.objects.filter(verifica_ok=False).count()
    interruzioni_aperte = Interruzione.objects.filter(al__isnull=True).order_by("-dal")
    ads_n = sum(1 for a in AmministratoreSistema.objects.all() if a.attivo)
    oggi = timezone.localdate()
    sigilli = {s.giorno: s for s in SigilloGiorno.objects.filter(giorno__gte=oggi - timedelta(days=13))}
    grafico = []
    for i in range(13, -1, -1):
        g = oggi - timedelta(days=i)
        s = sigilli.get(g)
        righe = (b["stato"].righe_oggi if b["stato"] and b["stato"].giorno_corrente == g else 0) if g == oggi else (s.righe if s else None)
        grafico.append({"giorno": g, "righe": righe, "stato": "oggi" if g == oggi else ("ko" if s and s.verifica_ok is False
                        else "ok" if s else "manca")})
    # La scala la fanno i giorni chiusi: oggi (in corso, o il primo giorno con lo storico iniziale) non schiaccia gli altri.
    chiusi = [x["righe"] or 0 for x in grafico if x["stato"] != "oggi"]
    massimo = max(chiusi + [1]) if any(chiusi) else max([x["righe"] or 0 for x in grafico] + [1])
    for x in grafico:
        x["altezza"] = min(100, max(3, round((x["righe"] or 0) * 100 / massimo))) if x["righe"] else 0
    passi = _passi(imp, fonti, b, ads_n, bool(imp.copia_cartella or imp.copia_sharepoint))
    importanti = (EventoRegistro.objects.exclude(categoria__in=regole.CATEGORIE_RISERVATE)
                  .filter(Q(gravita__in=("high", "warning")) | Q(privilegiato=True, fuori_orario=True))
                  .order_by("-quando")[:12])
    return render(request, "registro_log/panoramica.html", {
        "imp": imp, "battito": b, "fonti": fonti, "passi": passi, "passi_mancanti": sum(1 for p in passi if not p["fatto"]),
        "kpi": {
            "righe_oggi": b["stato"].righe_oggi if b["stato"] else 0,
            "accessi": conta.get("accesso", 0) + conta.get("accesso_privilegiato", 0),
            "accessi_ads": eventi_24.filter(privilegiato=True, categoria__in=("accesso", "accesso_privilegiato")).count(),
            "falliti": conta.get("accesso_fallito", 0),
            "critici": eventi_24.filter(gravita="high").count(),
            "fonti_ok": fonti.filter(attiva=True).exclude(tipo=FonteLog.TIPO_SYSLOG).filter(stato=FonteLog.STATO_OK).count()
            + fonti.filter(attiva=True, tipo=FonteLog.TIPO_SYSLOG, ultimo_evento_il__gte=ora - timedelta(hours=24)).count(),
            "fonti": fonti.filter(attiva=True).count(),
        },
        "ultimo_sigillo": ultimo_sigillo, "non_integri": non_integri, "interruzioni_aperte": interruzioni_aperte,
        "importanti": importanti, "oggi_inizio": oggi_inizio, "puo_configurare": _puo_configurare(request),
        "grafico": grafico,
        "etichette": regole.CATEGORIE,
    })


# ── Eventi ───────────────────────────────────────────────────────────────────

PERIODI = (("1", "Ultime 24 ore"), ("7", "7 giorni"), ("30", "30 giorni"), ("90", "90 giorni"), ("365", "Un anno"))
FILTRI_RAPIDI = (
    ("", "Tutti"),
    ("ads", "Accessi degli amministratori"),
    ("fuori", "Fuori orario"),
    ("falliti", "Non riusciti"),
    ("modifiche", "Modifiche ad account e gruppi"),
    ("critici", "Critici"),
)


def eventi(request):
    giorni = request.GET.get("giorni") or "7"
    if giorni not in dict(PERIODI):
        giorni = "7"
    qs = EventoRegistro.objects.filter(quando__gte=timezone.now() - timedelta(days=int(giorni))).exclude(
        categoria__in=regole.CATEGORIE_RISERVATE)
    rapido = request.GET.get("vista", "")
    if rapido == "ads":
        qs = qs.filter(privilegiato=True, categoria__in=("accesso", "accesso_privilegiato", "uscita"))
    elif rapido == "fuori":
        qs = qs.filter(fuori_orario=True, categoria__in=("accesso", "accesso_privilegiato"))
    elif rapido == "falliti":
        qs = qs.filter(categoria__in=("accesso_fallito", "account_bloccato"))
    elif rapido == "modifiche":
        qs = qs.filter(categoria__in=("account_creato", "account_eliminato", "account_modificato", "gruppo_privilegiato",
                                      "gruppo_modificato"))
    elif rapido == "critici":
        qs = qs.filter(gravita="high")
    categoria = request.GET.get("categoria", "")
    if categoria in regole.CATEGORIE:
        qs = qs.filter(categoria=categoria)
    fonte = request.GET.get("fonte", "")
    if fonte.isdigit():
        qs = qs.filter(fonte_id=int(fonte))
    testo = (request.GET.get("q") or "").strip()
    if testo:
        qs = qs.filter(Q(account__icontains=testo) | Q(host__icontains=testo) | Q(ip_origine__icontains=testo)
                       | Q(descrizione__icontains=testo) | Q(account_target__icontains=testo))
    if request.GET.get("export") == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["quando", "cosa", "esito", "account", "su", "da", "sistema", "fonte", "evento", "giorno archivio", "riga"])
        righe = list(qs.order_by("-quando", "-id")[:20000])
        for e in righe:
            w.writerow([timezone.localtime(e.quando).strftime("%d/%m/%Y %H:%M:%S"), e.descrizione, e.esito, e.account,
                        e.account_target, e.ip_origine, e.host, e.fonte_nome, e.event_id or "", e.archivio_giorno or "",
                        e.archivio_riga or ""])
        log_action(request, "registro_log_eventi_export", MODULO, {"filtri": request.GET.urlencode()[:500], "righe": len(righe)})
        resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="registro-eventi-{timezone.localdate():%Y%m%d}.csv"'
        return resp
    pagina = Paginator(qs.order_by("-quando", "-id"), 100).get_page(request.GET.get("pagina"))
    parametri = request.GET.copy()
    parametri.pop("pagina", None)
    return render(request, "registro_log/eventi.html", {
        "pagina": pagina, "giorni": giorni, "periodi": PERIODI, "rapidi": FILTRI_RAPIDI, "vista": rapido,
        "categoria": categoria, "categorie": sorted(((k, v) for k, v in regole.CATEGORIE.items()
                                                     if k not in regole.CATEGORIE_RISERVATE), key=lambda x: x[1][0]),
        "fonte": fonte, "fonti": FonteLog.objects.all(), "q": testo, "parametri": parametri.urlencode(),
        "etichette": regole.CATEGORIE,
    })


def evento(request, pk: int):
    ev = get_object_or_404(EventoRegistro, pk=pk)
    indagine = None
    if ev.categoria in regole.CATEGORIE_RISERVATE:
        # Evento riservato: solo dentro un'indagine aperta che lo comprende, e solo per chi configura il SOC.
        indagine = Indagine.objects.filter(pk=request.GET.get("indagine") or 0, chiusa_il__isnull=True).first()
        if not (_puo_configurare(request) and indagine and _indagine_qs(indagine).filter(pk=ev.pk).exists()):
            return _nego()
    riga = archivio.leggi_riga(ev.archivio_giorno, ev.archivio_riga) if ev.archivio_giorno and ev.archivio_riga else None
    if riga is not None:
        log_action(request, "registro_log_riga_letta", MODULO, {"evento": ev.pk, "giorno": str(ev.archivio_giorno),
                                                              "riga": ev.archivio_riga,
                                                              "indagine": indagine.pk if indagine else None})
    return render(request, "registro_log/evento.html", {
        "ev": ev, "riga": json.dumps(riga, ensure_ascii=False, indent=2) if riga else "", "dati": (riga or {}).get("d") or {}, "etichetta": regole.CATEGORIE.get(ev.categoria, (ev.categoria,))[0],
        "stesso_account": EventoRegistro.objects.filter(account=ev.account).exclude(pk=ev.pk).exclude(
            categoria__in=regole.CATEGORIE_RISERVATE).order_by("-quando")[:15] if ev.account else [],
        "indagine": indagine,
    })


# ── Archivio e integrità ─────────────────────────────────────────────────────


def archivio_pagina(request):
    puo = _puo_configurare(request)
    if request.method == "POST":
        if not puo:
            return _nego()
        azione = request.POST.get("azione")
        if azione == "verifica":
            esito = archivio.verifica(list(SigilloGiorno.objects.filter(eliminato_il__isnull=True).order_by("-giorno")[:62]))
            log_action(request, "registro_log_verifica", MODULO, esito | {"rotti": [str(g) for g in esito["rotti"]]})
            if esito["rotti"]:
                messages.error(request, f"Archivio NON integro nei giorni: {', '.join(g.strftime('%d/%m/%Y') for g in esito['rotti'])}.")
            else:
                messages.success(request, f"Verificati {esito['verificati']} giorni: archivio integro.")
        elif azione == "giustifica":
            i = get_object_or_404(Interruzione, pk=request.POST.get("id"))
            testo = (request.POST.get("giustificazione") or "").strip()[:500]
            Interruzione.objects.filter(pk=i.pk).update(giustificazione=testo, giustificata_da=_utente(request),
                                                        giustificata_il=timezone.now() if testo else None)
            log_action(request, "registro_log_giustifica", MODULO, {"interruzione": i.pk, "testo": testo})
            messages.success(request, "Giustificazione salvata.")
        return redirect(reverse("security:registro_log_archivio") + ("#interruzioni" if azione == "giustifica" else ""))
    sigilli = Paginator(SigilloGiorno.objects.order_by("-giorno"), 62).get_page(request.GET.get("pagina"))
    imp = Impostazioni.corrente()
    return render(request, "registro_log/archivio.html", {
        "sigilli": sigilli, "interruzioni": Interruzione.objects.order_by("-dal")[:200], "imp": imp,
        "cartella": archivio.cartella(), "puo_configurare": puo, "come_verificare": archivio.COME_VERIFICARE,
        "totali": {"giorni": SigilloGiorno.objects.count(), "non_integri": SigilloGiorno.objects.filter(verifica_ok=False).count(),
                   "da_copiare": SigilloGiorno.objects.filter(copia_il__isnull=True, eliminato_il__isnull=True).count()},
    })


def archivio_scarica(request, giorno: str):
    if not _puo_configurare(request):
        return _nego()
    try:
        g = date.fromisoformat(giorno)
    except ValueError as exc:
        raise Http404 from exc
    s = SigilloGiorno.objects.filter(giorno=g, eliminato_il__isnull=True).exclude(file="").first()
    if s is None:
        raise Http404("Giorno non presente nell'archivio.")
    if request.GET.get("sigillo"):
        resp = HttpResponse(archivio.meta_sigillo(s), content_type="application/json")
        resp["Content-Disposition"] = f'attachment; filename="registro-{g:%Y-%m-%d}.sigillo.json"'
        return resp
    percorso = archivio.cartella() / s.file
    if not percorso.exists():
        raise Http404("Il file del giorno non c'è più.")
    log_action(request, "registro_log_scarica", MODULO, {"giorno": giorno, "righe": s.righe})
    return FileResponse(open(percorso, "rb"), as_attachment=True, filename=percorso.name)


# ── Fonti e impostazioni ─────────────────────────────────────────────────────


def fonti(request):
    from .ciclo import battito

    puo = _puo_configurare(request)
    imp = Impostazioni.corrente()
    modifica = None
    if request.GET.get("modifica", "").isdigit():
        modifica = FonteLog.objects.filter(pk=int(request.GET["modifica"])).first()
    form_imp = ImpostazioniForm(instance=imp)
    form_fonte = FonteForm(instance=modifica) if modifica else FonteForm(initial={"tipo": FonteLog.TIPO_WINDOWS, "ruolo": "dc"})
    prova = None
    if request.method == "POST":
        if not puo:
            return _nego()
        azione = request.POST.get("azione")
        if azione == "impostazioni":
            form_imp = ImpostazioniForm(request.POST, instance=imp)
            if form_imp.is_valid():
                prima = Impostazioni.corrente().controlli_lavoratori_ok
                obj = form_imp.save(commit=False)
                obj.aggiornato_da = _utente(request)
                if obj.controlli_lavoratori_ok and not prima:
                    obj.controlli_lavoratori_da, obj.controlli_lavoratori_il = _utente(request), timezone.now()
                obj.save()
                if prima and not obj.controlli_lavoratori_ok:
                    FonteLog.objects.update(audit_file="", audit_stampe=False, stampe_nomi=False, audit_usb=False)
                    messages.warning(request, "Conferma tolta: accessi ai file, stampe e USB spenti su tutte le fonti.")
                log_action(request, "registro_log_impostazioni", MODULO, {k: str(v) for k, v in form_imp.cleaned_data.items()})
                messages.success(request, "Impostazioni salvate. Il raccoglitore le applica entro 5 minuti.")
                return redirect(reverse("security:registro_log_fonti") + "#impostazioni")
        elif azione == "fonte":
            form_fonte = FonteForm(request.POST, instance=modifica)
            if form_fonte.is_valid():
                f = form_fonte.save()
                log_action(request, "registro_log_fonte", MODULO, {"fonte": f.pk, "nome": f.nome, "tipo": f.tipo,
                                                                    "nuova": modifica is None})
                messages.success(request, f"Fonte «{f.nome}» salvata. Il raccoglitore la legge entro 5 minuti.")
                return redirect(reverse("security:registro_log_fonti") + "#fonti")
        elif azione == "elimina":
            f = get_object_or_404(FonteLog, pk=request.POST.get("id"))
            FonteLog.objects.filter(pk=f.pk).update(attiva=False)
            log_action(request, "registro_log_fonte_spenta", MODULO, {"fonte": f.pk, "nome": f.nome})
            messages.success(request, f"Fonte «{f.nome}» disattivata. Gli eventi già raccolti restano nell'archivio.")
            return redirect(reverse("security:registro_log_fonti") + "#fonti")
        elif azione == "prova":
            from .sorgenti import windows

            f = get_object_or_404(FonteLog, pk=request.POST.get("id"))
            if f.tipo == FonteLog.TIPO_SYSLOG:
                prova = {"fonte": f, "righe": [f"Indirizzi ammessi: {', '.join(f.lista_ip())}.",
                                               "Il syslog non si prova da qui: guardare «Ultimo messaggio» dopo aver configurato l'apparato."]}
            else:
                host = "" if f.tipo == FonteLog.TIPO_WEF else f.host
                canali = ["ForwardedEvents"] if f.tipo == FonteLog.TIPO_WEF else f.lista_canali()
                prova = {"fonte": f, "righe": windows.prova(host, canali)}
    from core.models import SiteConfig

    try:
        sconosciuti = json.loads(SiteConfig.get("registro_log.syslog_sconosciuti", "") or "{}")
    except ValueError:
        sconosciuti = {}
    elenco = list(FonteLog.objects.all())
    return render(request, "registro_log/fonti.html", {
        "imp": imp, "form_imp": form_imp, "form_fonte": form_fonte, "modifica": modifica, "fonti": elenco,
        "modulo_aperto": bool(modifica or not elenco or form_fonte.errors or request.GET.get("nuova")), "ora": timezone.now(),
        "puo_configurare": puo, "battito": battito(), "prova": prova, "cartella": archivio.cartella(),
        "sconosciuti": sorted(sconosciuti.items(), key=lambda x: -int(x[1].get("messaggi", 0)))[:20],
    })


# ── Indagini (eventi riservati: file, stampe, USB) ───────────────────────────


def _indagine_qs(ind):
    qs = EventoRegistro.objects.filter(categoria__in=regole.CATEGORIE_RISERVATE, quando__date__gte=ind.dal,
                                       quando__date__lte=ind.al)
    nomi = [a.split("\\")[-1].split("@")[0] for a in ind.lista_account()]
    if nomi:
        filtro = Q()
        for n in nomi:
            filtro |= Q(account__iexact=n) | Q(account__iendswith="\\" + n)
        qs = qs.filter(filtro)
    if ind.filtro_testo:
        t = ind.filtro_testo
        qs = qs.filter(Q(oggetto__icontains=t) | Q(descrizione__icontains=t) | Q(host__icontains=t))
    return qs


def indagini(request):
    if not _puo_configurare(request):
        return _nego()
    form = IndagineForm(initial={"dal": timezone.localdate() - timedelta(days=30), "al": timezone.localdate()})
    if request.method == "POST":
        form = IndagineForm(request.POST)
        if form.is_valid():
            ind = form.save(commit=False)
            ind.aperta_da = _utente(request)
            ind.save()
            log_action(request, "registro_log_indagine_aperta", MODULO, {"indagine": ind.pk, "motivo": ind.motivo[:300],
                                                                      "account": ind.account, "dal": str(ind.dal), "al": str(ind.al)})
            return redirect("security:registro_log_indagine", pk=ind.pk)
    imp = Impostazioni.corrente()
    raccolti = FonteLog.objects.filter(attiva=True).filter(Q(audit_stampe=True) | Q(audit_usb=True) | ~Q(audit_file=""))
    return render(request, "registro_log/indagini.html", {
        "form": form, "elenco": Indagine.objects.all()[:200], "imp": imp, "fonti_raccolte": raccolti,
    })


def indagine(request, pk: int):
    if not _puo_configurare(request):
        return _nego()
    ind = get_object_or_404(Indagine, pk=pk)
    if request.method == "POST" and ind.aperta:
        ind.esito = (request.POST.get("esito") or "").strip()
        ind.chiusa_il, ind.chiusa_da = timezone.now(), _utente(request)
        ind.save(update_fields=["esito", "chiusa_il", "chiusa_da"])
        log_action(request, "registro_log_indagine_chiusa", MODULO, {"indagine": ind.pk, "esito": ind.esito[:300]})
        messages.success(request, "Indagine chiusa: i dati non sono più consultabili da qui.")
        return redirect("security:registro_log_indagine", pk=ind.pk)
    qs = _indagine_qs(ind) if ind.aperta else EventoRegistro.objects.none()
    vista = request.GET.get("vista", "file")
    gruppi = {"file": ("file_letto", "file_modificato", "file_eliminato", "file_permessi"), "stampe": ("stampa",),
              "usb": ("usb_collegato",)}
    conteggi = {k: qs.filter(categoria__in=v).count() for k, v in gruppi.items()}
    righe = qs.filter(categoria__in=gruppi.get(vista, gruppi["file"])).order_by("quando", "id")
    if request.GET.get("export") == "csv" and ind.aperta:
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["quando", "account", "cosa", "oggetto", "pagine", "sistema", "da", "giorno archivio", "riga archivio"])
        for e in righe[:100000]:
            w.writerow([timezone.localtime(e.quando).strftime("%d/%m/%Y %H:%M:%S"), e.account, e.descrizione, e.oggetto,
                        e.quantita or "", e.host, e.ip_origine, e.archivio_giorno or "", e.archivio_riga or ""])
        log_action(request, "registro_log_indagine_export", MODULO, {"indagine": ind.pk, "vista": vista, "righe": righe.count()})
        resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="indagine-{ind.pk}-{vista}.csv"'
        return resp
    if ind.aperta:
        log_action(request, "registro_log_indagine_consultata", MODULO, {"indagine": ind.pk, "vista": vista})
    riepilogo = {
        "pagine": sum(x or 0 for x in qs.filter(categoria="stampa").values_list("quantita", flat=True)),
        "eliminati": qs.filter(categoria="file_eliminato").count(),
        "dispositivi": qs.filter(categoria="usb_collegato").values("oggetto").distinct().count(),
    }
    return render(request, "registro_log/indagine.html", {
        "ind": ind, "righe": Paginator(righe, 200).get_page(request.GET.get("pagina")), "vista": vista,
        "conteggi": conteggi, "riepilogo": riepilogo,
    })


# ── Account AD e amministratori di sistema ───────────────────────────────────


def account(request):
    from . import ad

    puo = _puo_configurare(request)
    if request.method == "POST":
        if not puo:
            return _nego()
        a = get_object_or_404(AccountAD, pk=request.POST.get("id"))
        tipo = request.POST.get("tipo", a.tipo)
        if tipo in dict(AccountAD.TIPI):
            a.tipo = tipo
        a.responsabile = (request.POST.get("responsabile") or "").strip()[:255]
        a.nota = (request.POST.get("nota") or "").strip()[:500]
        a.save(update_fields=["tipo", "responsabile", "nota"])
        log_action(request, "registro_log_account", MODULO, {"account": a.sam, "tipo": a.tipo, "responsabile": a.responsabile})
        messages.success(request, f"Account {a.sam} aggiornato.")
        return redirect(reverse("security:registro_log_account") + f"?q={a.sam}")
    qs = AccountAD.objects.filter(sparito_il__isnull=True)
    filtro = request.GET.get("filtro", "")
    if filtro == "privilegiati":
        qs = qs.exclude(gruppi_privilegiati=[])
    elif filtro == "disabilitati":
        qs = qs.filter(abilitato=False)
    elif filtro == "servizio":
        qs = qs.filter(tipo=AccountAD.TIPO_SERVIZIO)
    testo = (request.GET.get("q") or "").strip()
    if testo:
        qs = qs.filter(Q(sam__icontains=testo) | Q(nome__icontains=testo) | Q(anagrafica_nome__icontains=testo)
                       | Q(email__icontains=testo))
    from security.services import letture

    ultimo = None
    try:
        from security.models import SecurityLetturaLog

        ultimo = SecurityLetturaLog.objects.filter(codice="registro_ad").order_by("-avviata_il").first()
    except Exception:  # noqa: BLE001 - la pagina regge anche senza storico
        ultimo = None
    nominati = set()
    for ads in AmministratoreSistema.objects.all():
        if ads.attivo:
            nominati.update(x.split("\\")[-1].split("@")[0].lower() for x in ads.lista_account())
    return render(request, "registro_log/account.html", {
        "nominati": nominati,
        "account": Paginator(qs.order_by("sam"), 100).get_page(request.GET.get("pagina")), "filtro": filtro, "q": testo,
        "segnalazioni": ad.segnalazioni(), "configurato": ad.configurato(), "puo_configurare": puo, "ultimo": ultimo,
        "tipi": AccountAD.TIPI, "totale": AccountAD.objects.filter(sparito_il__isnull=True).count(),
        "lettura_attiva": bool(letture.PER_CODICE.get("registro_ad")),
    })


def amministratori(request):
    puo = _puo_configurare(request)
    modifica = None
    if request.GET.get("modifica", "").isdigit():
        modifica = AmministratoreSistema.objects.filter(pk=int(request.GET["modifica"])).first()
    iniziali = {}
    if not modifica and request.GET.get("account"):
        iniziali = {"account": request.GET["account"][:150], "nome": (request.GET.get("nome") or "")[:255],
                    "nominato_il": timezone.localdate(), "prossima_revisione": timezone.localdate() + timedelta(days=365)}
    form = AmministratoreForm(instance=modifica, initial=iniziali)
    if request.method == "POST":
        if not puo:
            return _nego()
        form = AmministratoreForm(request.POST, request.FILES, instance=modifica)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.aggiornato_da = _utente(request)
            obj.save()
            log_action(request, "registro_log_ads", MODULO, {"ads": obj.pk, "nome": obj.nome, "account": obj.account,
                                                             "revocato_il": str(obj.revocato_il or "")})
            messages.success(request, f"Amministratore «{obj.nome}» salvato.")
            return redirect("security:registro_log_ads")
    elenco = list(AmministratoreSistema.objects.all())
    privilegiati = {a.sam.lower(): a for a in AccountAD.objects.filter(sparito_il__isnull=True).exclude(gruppi_privilegiati=[])}
    oggi = timezone.localdate()
    for a in elenco:
        a.account_ad = [privilegiati.get(x.split("\\")[-1].split("@")[0].lower()) for x in a.lista_account()]
        a.revisione_scaduta = bool(a.attivo and a.prossima_revisione and a.prossima_revisione < oggi)
    return render(request, "registro_log/amministratori.html", {
        "elenco": elenco, "form": form, "modifica": modifica, "puo_configurare": puo,
        "attivi": sum(1 for a in elenco if a.attivo), "precompilato": bool(iniziali),
    })


def amministratore_nomina(request, pk: int):
    a = get_object_or_404(AmministratoreSistema, pk=pk)
    if not a.documento_nomina:
        raise Http404
    log_action(request, "registro_log_nomina_scaricata", MODULO, {"ads": a.pk})
    return FileResponse(a.documento_nomina.open("rb"), as_attachment=True, filename=f"nomina-{a.pk}.pdf")


# ── Verifica annuale ─────────────────────────────────────────────────────────


def verifica(request):
    from . import report

    oggi = timezone.localdate()
    try:
        anno = int(request.GET.get("anno") or request.POST.get("anno") or oggi.year)
    except ValueError:
        anno = oggi.year
    anno = max(2020, min(anno, oggi.year))
    esistente = VerificaAnnuale.objects.filter(anno=anno).first()
    form = VerificaForm(instance=esistente, initial={"eseguita_il": oggi})
    c = report.riepilogo(anno)
    if request.method == "POST":
        if not _puo_configurare(request):
            return _nego()
        form = VerificaForm(request.POST, instance=esistente)
        if form.is_valid():
            v = form.save(commit=False)
            v.anno, v.registrata_da = anno, _utente(request)
            v.riepilogo = {"impronta": c["impronta"], "controlli": c["controlli"], "generato_il": c["generato_il"].isoformat()}
            v.save()
            log_action(request, "registro_log_verifica_annuale", MODULO, {"anno": anno, "esito": v.esito, "impronta": c["impronta"]})
            messages.success(request, f"Verifica {anno} registrata.")
            return redirect(reverse("security:registro_log_verifica") + f"?anno={anno}")
    if request.GET.get("pdf"):
        log_action(request, "registro_log_verifica_pdf", MODULO, {"anno": anno})
        resp = HttpResponse(report.pdf(c, esistente), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="verifica-amministratori-{anno}.pdf"'
        return resp
    return render(request, "registro_log/verifica.html", {
        "c": c, "anno": anno, "anni": list(range(oggi.year, 2019, -1))[:8], "esistente": esistente, "form": form,
        "puo_configurare": _puo_configurare(request), "storico": VerificaAnnuale.objects.all(),
    })


# ── Server e virtualizzazione ────────────────────────────────────────────────


def infra(request):
    from . import infra as svc

    puo = _puo_configurare(request)
    modifica = None
    if request.GET.get("modifica", "").isdigit():
        modifica = ApparatoInfra.objects.filter(pk=int(request.GET["modifica"])).first()
    form = ApparatoForm(instance=modifica, initial={"tipo": ApparatoInfra.TIPO_VSPHERE, "porta": 443})
    if request.method == "POST":
        if not puo:
            return _nego()
        azione = request.POST.get("azione")
        if azione == "leggi":
            app = get_object_or_404(ApparatoInfra, pk=request.POST.get("id"))
            svc.leggi(app)
            app.refresh_from_db()
            if app.errore:
                messages.error(request, f"{app.nome}: {app.errore}")
            else:
                messages.success(request, f"{app.nome} letto: {len(app.problemi or [])} cose da guardare.")
            return redirect("security:registro_log_infra")
        form = ApparatoForm(request.POST, instance=modifica)
        if form.is_valid():
            obj = form.save(commit=False)
            if form.cleaned_data.get("password"):
                obj.password_cifrata = svc.cifra(form.cleaned_data["password"])
            obj.save()
            log_action(request, "registro_log_apparato", MODULO, {"apparato": obj.pk, "nome": obj.nome, "tipo": obj.tipo})
            messages.success(request, f"«{obj.nome}» salvato. Premere «Leggi ora» per la prima lettura.")
            return redirect("security:registro_log_infra")
    return render(request, "registro_log/infra.html", {
        "apparati": ApparatoInfra.objects.all(), "form": form, "modifica": modifica, "puo_configurare": puo,
    })


@require_POST
def infra_elimina(request, pk: int):
    if not _puo_configurare(request):
        return _nego()
    app = get_object_or_404(ApparatoInfra, pk=pk)
    log_action(request, "registro_log_apparato_eliminato", MODULO, {"apparato": app.pk, "nome": app.nome})
    app.delete()
    messages.success(request, "Apparato eliminato.")
    return redirect("security:registro_log_infra")
