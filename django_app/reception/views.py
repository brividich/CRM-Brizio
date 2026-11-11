"""Pannello della reception nell'HUB: prende il posto del pannello PHP del GuestPortal.

Permessi: ACL v2 con lo stesso permesso di «Accessi esterni» (binding copiati in migrazione), al posto
di ``AdminUsers``. La configurazione sta nel ``.env``. Il «Reset completo» del PHP non esiste più.
"""
from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.models import SiteConfig
from core.net import client_ip

from . import mail, sale, servizi
from .models import (
    Cartellino, CategoriaVisita, ContattoDitta, DittaAccreditata, EventoVisita, Preregistrazione, Referente,
    RichiestaAppuntamento, Visita,
)

CHIAVE_AVVISO_REQUISITI = "chiosco_avviso_requisiti"
STORICO_MAX = 500


def _autore(request) -> str:
    return request.user.get_username()


# Quattro voci in alto; dove una voce raggruppa più pagine, queste diventano schede sotto il titolo.
GRUPPI_MENU = (
    ("oggi", "Oggi", (("cruscotto", "Oggi"), ("registra", "Registra ingresso"))),
    ("inviti", "Inviti", (("preregistrazioni", "Inviti"), ("richieste", "Richieste"))),
    ("storico", "Storico", (("storico", "Storico"),)),
    ("config", "Configurazione", (("referenti", "Referenti"), ("ditte", "Ditte accreditate"), ("cartellini", "Cartellini"),
                                  ("sale", "Sale"), ("impostazioni", "Impostazioni"))),
)
SCHEDE_VISIBILI = {"inviti", "config"}


def _ammessa(request, url: str) -> bool:
    from core.middleware import acl_allows_path

    try:
        return request.user.is_superuser or bool(acl_allows_path(url, django_user=request.user, request=request))
    except Exception:  # noqa: BLE001 - nel dubbio la voce resta: decide comunque il server all'apertura
        return True


def _menu(request, sezione: str = "") -> list[dict]:
    """Voci del pannello che l'utente può aprire (Vedere / Creare-Modificare / Impostazioni in «Ruoli e permessi»).
    Ogni voce porta alla prima pagina ammessa del suo gruppo; ``schede`` sono le pagine ammesse del gruppo."""
    voci = []
    for chiave, etichetta, pagine in GRUPPI_MENU:
        schede = []
        for nome, titolo in pagine:
            url = reverse(f"reception:{nome}")
            if _ammessa(request, url):
                schede.append({"nome": nome, "etichetta": titolo, "url": url})
        if schede:
            voci.append({"chiave": chiave, "etichetta": etichetta, "url": schede[0]["url"], "nome": schede[0]["nome"],
                         "attiva": any(s["nome"] == sezione for s in schede), "schede": schede})
    return voci


def _ctx(request, sezione: str, **dati) -> dict:
    menu = _menu(request, sezione)
    attiva = next((v for v in menu if v["attiva"]), None)
    schede = attiva["schede"] if attiva and attiva["chiave"] in SCHEDE_VISIBILI and len(attiva["schede"]) > 1 else []
    pagine = {s["nome"] for v in menu for s in v["schede"]}
    return {"sezione": sezione, "nativa": bool(getattr(settings, "RECEPTION_NATIVA", False)), "menu": menu, "schede": schede,
            "n_richieste": RichiestaAppuntamento.objects.filter(stato=RichiestaAppuntamento.IN_ATTESA).count(),
            "n_presenti": Visita.objects.filter(stato=Visita.DENTRO).count(),
            "azione_ingresso": "registra" in pagine, "azione_invito": "preregistrazioni" in pagine, **dati}


def _elenco_referenti() -> list[dict]:
    """Per la scelta del referente con ricerca nella pagina (json_script): solo id, nome e reparto."""
    return [{"id": r.pk, "nome": r.nome_elenco, "reparto": r.reparto} for r in Referente.objects.filter(attivo=True)]


def _data_ora(data: str, ora: str):
    try:
        return timezone.make_aware(datetime.strptime(f"{data} {ora}", "%Y-%m-%d %H:%M"))
    except (ValueError, TypeError):
        return None


@login_required
def cruscotto(request):
    oggi = timezone.localdate()
    inizio = timezone.make_aware(datetime.combine(oggi, datetime.min.time()))
    presenti = Visita.objects.select_related("ospite", "ditta").filter(stato=Visita.DENTRO).order_by("ingresso")
    attesi = Preregistrazione.objects.filter(data_visita=oggi, usata_il__isnull=True, scade_il__gte=timezone.now()).order_by("ora_inizio", "ospite_nome")
    liberi = servizi.cartellini_liberi()
    return render(request, "reception/cruscotto.html", _ctx(
        request, "cruscotto", presenti=presenti, attesi=attesi,
        n_oggi=Visita.objects.filter(ingresso__gte=inizio, ingresso__lt=inizio + timedelta(days=1)).count(),
        n_liberi=len(liberi), liberi=liberi, referenti_json=_elenco_referenti(),
        categorie=CategoriaVisita.objects.filter(attiva=True), dati={}, apri=request.GET.get("nuovo") == "1",
    ))


@login_required
@require_POST
def visita_uscita(request, visita_id):
    try:
        servizi.registra_uscita(visita_id, autore=_autore(request), ip=client_ip(request) or "", origine="PANNELLO")
    except servizi.OperazioneNonValida as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, "reception_uscita", "reception", {"visita": visita_id})
        messages.success(request, "Uscita registrata.")
    return redirect("reception:cruscotto")


@login_required
def registra(request):
    referenti = Referente.objects.filter(attivo=True)
    if request.method == "POST":
        dati = request.POST
        nome, cognome = dati.get("nome", "").strip()[:100], dati.get("cognome", "").strip()[:100]
        referente = referenti.filter(pk=dati.get("referente") or 0).first()
        if not nome or not cognome or referente is None:
            messages.error(request, "Nome, cognome e referente sono obbligatori.")
        else:
            try:
                ospite = servizi.ospite_da_dati(nome=nome, cognome=cognome, email=dati.get("email", "").strip()[:255],
                                                telefono=dati.get("telefono", "").strip()[:50],
                                                azienda=dati.get("azienda", "").strip()[:255], ip="")
                visita = servizi.registra_ingresso(
                    ospite, referente_nome=referente.nome_elenco, referente_email=referente.email,
                    motivo=dati.get("motivo", "Altro"), creata_da="PANNELLO",
                    cartellino=dati.get("cartellino", ""), quando=_data_ora(timezone.localdate().isoformat(), dati.get("ora", "")),
                )
            except servizi.GiaDentro:
                messages.error(request, "Questa persona risulta già dentro.")
            except servizi.CartelliniFiniti:
                messages.error(request, "Il cartellino scelto non è più libero.")
            except servizi.EmailDiAltri:
                messages.error(request, "Questa email è già associata a un'altra persona.")
            else:
                log_action(request, "reception_ingresso_manuale", "reception", {"visita": visita.pk})
                messages.success(request, f"Ingresso registrato, cartellino {visita.cartellino}.")
                return redirect("reception:cruscotto")
    return render(request, "reception/registra.html", _ctx(
        request, "registra", referenti_json=_elenco_referenti(), categorie=CategoriaVisita.objects.filter(attiva=True),
        liberi=servizi.cartellini_liberi(), dati=request.POST,
        referente_scelto=referenti.filter(pk=request.POST.get("referente") or 0).first(),
    ))


@login_required
def storico(request):
    oggi = timezone.localdate()
    testo = request.GET.get("q", "").strip()[:80]
    dal, al, stato = request.GET.get("dal") or (oggi - timedelta(days=30)).isoformat(), request.GET.get("al") or oggi.isoformat(), request.GET.get("stato", "")
    visite = Visita.objects.select_related("ospite", "ditta")
    inizio, fine = _data_ora(dal, "00:00"), _data_ora(al, "00:00")
    if inizio:
        visite = visite.filter(ingresso__gte=inizio)
    if fine:
        visite = visite.filter(ingresso__lt=fine + timedelta(days=1))
    if stato in dict(Visita.STATI):
        visite = visite.filter(stato=stato)
    if testo:
        visite = visite.filter(Q(ospite__nome__icontains=testo) | Q(ospite__cognome__icontains=testo) | Q(ospite__azienda__icontains=testo)
                               | Q(ditta__nome__icontains=testo) | Q(referente_nome__icontains=testo))
    righe = list(visite.order_by("-ingresso", "-pk")[:STORICO_MAX + 1])
    return render(request, "reception/storico.html", _ctx(
        request, "storico", righe=righe[:STORICO_MAX], tagliato=len(righe) > STORICO_MAX, massimo=STORICO_MAX,
        q=testo, dal=dal, al=al, stato=stato, stati=Visita.STATI,
    ))


@login_required
def visita_scheda(request, visita_id):
    visita = get_object_or_404(Visita.objects.select_related("ospite", "ditta", "contatto"), pk=visita_id)
    if request.method == "POST":
        azione = request.POST.get("azione")
        autore, ip = _autore(request), client_ip(request) or ""
        try:
            if azione == "riapri":
                servizi.riapri_visita(visita.pk, request.POST.get("cartellino", ""), autore=autore, ip=ip)
                messages.success(request, "Visita riaperta.")
            else:
                quando = _data_ora(request.POST.get("data", ""), request.POST.get("ora", ""))
                if quando is None:
                    raise servizi.OperazioneNonValida("Data o ora di uscita non valida.")
                servizi.correggi_uscita(visita.pk, quando, autore=autore, ip=ip)
                messages.success(request, "Uscita corretta.")
        except servizi.OperazioneNonValida as exc:
            messages.error(request, str(exc))
        else:
            log_action(request, "reception_visita_corretta", "reception", {"visita": visita.pk, "azione": azione})
        return redirect("reception:visita_scheda", visita_id=visita.pk)
    return render(request, "reception/visita.html", _ctx(
        request, "storico", v=visita, eventi=EventoVisita.objects.filter(visita_id_rif=visita.pk),
        liberi=servizi.cartellini_liberi(), giorni_riapertura=servizi.GIORNI_RIAPERTURA,
    ))


@login_required
def preregistrazioni(request):
    if request.method == "POST":
        dati = request.POST
        referente = Referente.objects.filter(attivo=True, pk=dati.get("referente") or 0).first()
        nome, email = dati.get("nome", "").strip()[:200], dati.get("email", "").strip().lower()[:255]
        if not nome or "@" not in email or referente is None:
            messages.error(request, "Nome, email dell'ospite e referente sono obbligatori.")
        else:
            data_visita = _data_ora(dati.get("data_visita", ""), "00:00")
            giorno = data_visita.date() if data_visita else None
            inizio, fine = _ora(dati.get("ora_inizio")), _ora(dati.get("ora_fine"))
            scelta, errore = sala_dal_post(request, giorno, inizio, fine)
            if errore:
                messages.error(request, errore)
                return redirect(reverse("reception:preregistrazioni") + "?nuovo=1")
            scade = _data_ora(dati.get("scade", ""), "23:59") or timezone.now() + timedelta(days=servizi.GIORNI_VALIDITA_CODICE)
            pre = servizi.crea_preregistrazione(
                ospite_nome=nome, ospite_email=email, ospite_azienda=dati.get("azienda", ""), referente=referente,
                motivo=dati.get("motivo", ""), creata_da=_autore(request), scade_il=scade,
                data_visita=giorno, ora_inizio=inizio, ora_fine=fine, sala=scelta,
            )
            log_action(request, "reception_preregistrazione", "reception", {"preregistrazione": pre.pk, "sala": pre.sala_id})
            prenota_sala(request, pre)
            if _manda_invito(request, pre):
                messages.success(request, f"Codice {pre.codice} creato e inviato a {pre.ospite_email}.")
            return redirect("reception:preregistrazioni")
    return render(request, "reception/preregistrazioni.html", _ctx(
        request, "preregistrazioni", referenti_json=_elenco_referenti(),
        categorie=CategoriaVisita.objects.filter(attiva=True), sale_riunioni=list(sale.sale_attive()),
        righe=Preregistrazione.objects.select_related("sala").filter(Q(scade_il__gte=timezone.now()) | Q(usata_il__isnull=False))[:100],
        apri=request.GET.get("nuovo") == "1",
    ))


def _ora(valore):
    try:
        return datetime.strptime(valore or "", "%H:%M").time()
    except ValueError:
        return None


def sala_dal_post(request, giorno, inizio, fine, *, escludi_pk=None):
    """(sala scelta o None, errore). Nessuna sala scelta = nessun errore."""
    pk = (request.POST.get("sala") or "").strip()
    if not pk.isdigit():
        return None, ""
    scelta = sale.sale_attive().filter(pk=int(pk)).first()
    if scelta is None:
        return None, "La sala scelta non esiste più: scegline un'altra."
    errore = sale.verifica(scelta, giorno, inizio, fine, escludi_pk=escludi_pk)
    return (None, errore) if errore else (scelta, "")


def prenota_sala(request, pre) -> None:
    livello, testo = sale.prenota(pre)
    if testo:
        {"success": messages.success, "warning": messages.warning}.get(livello, messages.info)(request, testo)


def _manda_invito(request, pre) -> bool:
    try:
        mail.invia_invito(pre)
    except Exception:  # noqa: BLE001 - il codice resta valido, si rimanda dall'elenco
        messages.warning(request, f"Codice {pre.codice} creato, ma la mail non è partita: riprova da «Invia».")
        return False
    return True


@login_required
@require_POST
def preregistrazione_azione(request, pk):
    pre = get_object_or_404(Preregistrazione, pk=pk)
    if request.POST.get("azione") == "elimina":
        sale.libera(pre)
        pre.delete()
        log_action(request, "reception_preregistrazione_eliminata", "reception", {"preregistrazione": pk})
        messages.success(request, "Pre-registrazione eliminata.")
    elif _manda_invito(request, pre):
        messages.success(request, f"Invito rimandato a {pre.ospite_email}.")
    return redirect("reception:preregistrazioni")


@login_required
def referenti(request):
    from .views_ricerca import dati_dipendenti

    if request.method == "POST":
        dati = request.POST
        pk = dati.get("pk") or None
        nome, cognome, email = dati.get("nome", "").strip()[:100], dati.get("cognome", "").strip()[:100], dati.get("email", "").strip().lower()[:255]
        azione = dati.get("azione")
        if azione == "stato":
            r = get_object_or_404(Referente, pk=pk)
            r.attivo = not r.attivo
            r.save(update_fields=["attivo"])
        elif azione == "aggiorna":
            esito = _aggiorna_da_anagrafica(dati_dipendenti)
            log_action(request, "reception_referenti_aggiornati", "reception", esito)
            messages.success(request, f"Aggiornati dall'anagrafica: {esito['aggiornati']}. Non più in forza, disattivati: {esito['disattivati']}.")
        elif not nome or not cognome or "@" not in email:
            messages.error(request, "Nome, cognome ed email sono obbligatori. Se il dipendente non ha l'email di notifica in anagrafica, scrivila a mano.")
        else:
            try:
                dipendente_id = int(dati.get("dipendente_id") or 0) or None
            except ValueError:
                dipendente_id = None
            if not pk and dipendente_id:
                # Dipendente scelto dall'anagrafica e già tra i referenti (stessa scheda, o stessa email non
                # collegata ad altri): si aggiorna, non si duplica. A mano un'email doppia resta un errore.
                gia = Referente.objects.filter(
                    Q(dipendente_id=dipendente_id) | Q(email__iexact=email, dipendente_id__isnull=True)).first()
                pk = gia.pk if gia else None
            if Referente.objects.filter(email__iexact=email).exclude(pk=pk).exists():
                messages.error(request, "Questa email è già di un altro referente.")
                return redirect("reception:referenti")
            campi = {"nome": nome, "cognome": cognome, "email": email, "reparto": dati.get("reparto", "").strip()[:100],
                     "telefono": dati.get("telefono", "").strip()[:50], "dipendente_id": dipendente_id}
            if pk:
                Referente.objects.filter(pk=pk).update(**campi)
            else:
                Referente.objects.create(**campi)
            messages.success(request, f"{cognome} {nome} salvato tra i referenti.")
        return redirect("reception:referenti")
    righe = list(Referente.objects.all())
    collegati = {d["id"]: d for d in dati_dipendenti(ids=[r.dipendente_id for r in righe if r.dipendente_id])}
    for r in righe:
        r.cessato = bool(r.dipendente_id and collegati.get(r.dipendente_id, {}).get("cessato"))
    return render(request, "reception/referenti.html", _ctx(
        request, "referenti", righe=righe, modifica=Referente.objects.filter(pk=request.GET.get("modifica") or 0).first(),
        n_collegati=sum(1 for r in righe if r.dipendente_id),
    ))


def _aggiorna_da_anagrafica(dati_dipendenti) -> dict:
    """Riprende dall'anagrafica i referenti collegati; chi non è più in forza viene disattivato. L'email resta se manca."""
    esito = {"aggiornati": 0, "disattivati": 0}
    righe = list(Referente.objects.exclude(dipendente_id__isnull=True))
    dati = {d["id"]: d for d in dati_dipendenti(ids=[r.dipendente_id for r in righe])}
    for r in righe:
        d = dati.get(r.dipendente_id)
        if d is None:
            continue
        if d["cessato"]:
            if r.attivo:
                r.attivo = False
                r.save(update_fields=["attivo"])
                esito["disattivati"] += 1
            continue
        nuovi = {"nome": d["nome"] or r.nome, "cognome": d["cognome"] or r.cognome, "reparto": d["reparto"][:100] or r.reparto,
                 "telefono": d["telefono"][:50] or r.telefono}
        if d["email"] and not Referente.objects.filter(email__iexact=d["email"]).exclude(pk=r.pk).exists():
            nuovi["email"] = d["email"]
        if any(getattr(r, k) != v for k, v in nuovi.items()):
            Referente.objects.filter(pk=r.pk).update(**nuovi)
            esito["aggiornati"] += 1
    return esito


@login_required
def ditte(request):
    if request.method == "POST":
        dati = request.POST
        azione = dati.get("azione")
        if azione == "ditta_stato":
            d = get_object_or_404(DittaAccreditata, pk=dati.get("pk"))
            d.attiva = not d.attiva
            d.save(update_fields=["attiva"])
        elif azione == "contatto_stato":
            c = get_object_or_404(ContattoDitta, pk=dati.get("pk"))
            c.attivo = not c.attivo
            c.save(update_fields=["attivo"])
        elif azione == "contatto":
            d = get_object_or_404(DittaAccreditata, pk=dati.get("pk"))
            nome, cognome = dati.get("nome", "").strip()[:100], dati.get("cognome", "").strip()[:100]
            if nome and cognome:
                ContattoDitta.objects.create(ditta=d, nome=nome, cognome=cognome)
            else:
                messages.error(request, "Nome e cognome sono obbligatori.")
        else:
            nome = dati.get("nome", "").strip()[:200]
            if not nome:
                messages.error(request, "Il nome della ditta è obbligatorio.")
            else:
                try:
                    DittaAccreditata.objects.create(nome=nome, note=dati.get("note", "").strip()[:500])
                except IntegrityError:
                    messages.error(request, "Questa ditta c'è già.")
        return redirect("reception:ditte")
    return render(request, "reception/ditte.html", _ctx(
        request, "ditte", righe=DittaAccreditata.objects.prefetch_related("contatti"),
    ))


def _qr_data_uri(testo: str) -> str:
    import qrcode

    buffer = io.BytesIO()
    qrcode.make(testo, box_size=6, border=2).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@login_required
def cartellini(request):
    if request.method == "POST":
        try:
            quanti = max(0, min(int(request.POST.get("quanti") or 0), 200))
        except ValueError:
            quanti = 0
        numeri = [int(n) for n in Cartellino.objects.values_list("numero", flat=True) if str(n).isdigit()]
        partenza = max(numeri, default=0)
        for i in range(1, quanti + 1):
            Cartellino.objects.get_or_create(numero=f"{partenza + i:02d}")
        if quanti:
            log_action(request, "reception_cartellini_aggiunti", "reception", {"quanti": quanti})
            messages.success(request, f"Aggiunti {quanti} cartellini.")
        return redirect("reception:cartellini")
    righe = list(Cartellino.objects.all())
    occupati = dict(Visita.objects.filter(stato=Visita.DENTRO).values_list("cartellino", "ospite__cognome"))
    for c in righe:
        c.occupato = c.numero in occupati
    etichette = [{"numero": c.numero, "qr": _qr_data_uri(c.numero)} for c in righe] if request.GET.get("stampa") else []
    return render(request, "reception/cartellini.html", _ctx(request, "cartellini", righe=righe, etichette=etichette))


@login_required
def sale_config(request):
    """Reception → Configurazione → Sale: quali sale riunioni compaiono negli inviti.

    Le sale sono le stesse del KICK-OFF (una casella Microsoft 365 per sala): da qui si aggiungono e si
    correggono, e si sceglie quali proporre in «Prenota una sala». Le visite non compaiono nel KICK-OFF.
    """
    import re

    from tasks.models import MeetingRoom

    from .models import SalaInviti

    if request.method == "POST":
        dati = request.POST
        nome = " ".join((dati.get("nome") or "").split())[:120]
        email = (dati.get("email") or "").strip().lower()[:254]
        capienza = dati.get("capienza") or ""
        capienza = int(capienza) if capienza.isdigit() and 0 < int(capienza) < 1000 else None
        negli_inviti = dati.get("negli_inviti") == "1"
        pk = dati.get("pk") or ""
        sala = MeetingRoom.objects.filter(pk=int(pk)).first() if pk.isdigit() else None
        if dati.get("azione") == "inviti" and sala is not None:
            # Interruttore rapido dall'elenco
            if negli_inviti:
                SalaInviti.objects.get_or_create(sala=sala)
            else:
                SalaInviti.objects.filter(sala=sala).delete()
            log_action(request, "reception_sala_inviti", "reception", {"sala": sala.pk, "negli_inviti": negli_inviti})
            return redirect("reception:sale")
        if not nome:
            messages.error(request, "Scrivi il nome della sala.")
        elif email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            messages.error(request, "La casella della sala non è un indirizzo email valido.")
        elif MeetingRoom.objects.filter(nome__iexact=nome).exclude(pk=getattr(sala, "pk", None)).exists():
            messages.error(request, f"Esiste già una sala «{nome}».")
        else:
            nuova = sala is None
            if nuova:
                sala = MeetingRoom.objects.create(nome=nome, email=email, capienza=capienza)
            else:
                sala.nome, sala.email, sala.capienza = nome, email, capienza
                sala.save(update_fields=["nome", "email", "capienza"])
            if negli_inviti:
                SalaInviti.objects.get_or_create(sala=sala)
            else:
                SalaInviti.objects.filter(sala=sala).delete()
            log_action(request, "reception_sala_aggiunta" if nuova else "reception_sala_modificata", "reception", {"sala": sala.pk})
            messages.success(request, f"Sala «{sala.nome}» {'aggiunta' if nuova else 'salvata'}.")
            return redirect("reception:sale")
    scelte = set(SalaInviti.objects.values_list("sala_id", flat=True))
    righe = list(MeetingRoom.objects.order_by("ordine", "nome"))
    for s in righe:
        s.negli_inviti = s.pk in scelte
    voluta = request.GET.get("modifica") or ""
    modifica = next((s for s in righe if voluta.isdigit() and s.pk == int(voluta)), None)
    return render(request, "reception/sale.html", _ctx(request, "sale", righe=righe, modifica=modifica))


def _logo_percorso() -> str:
    from fornitori import chiosco

    return chiosco.logo_percorso()


def _salva_logo(request, azione: str) -> None:
    """Logo del chiosco: PNG, JPG o WEBP fino a 1 MB (niente SVG). Salvato nello storage, servito da /chiosco/logo/."""
    import os
    import time

    from django.core.files.storage import default_storage

    from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
    from fornitori import chiosco

    vecchio = chiosco.logo_percorso()
    if azione == "logo_togli":
        if vecchio and default_storage.exists(vecchio):
            default_storage.delete(vecchio)
        SiteConfig.set(chiosco.CHIAVE_LOGO, "", "Logo del chiosco della reception")
        log_action(request, "reception_logo_tolto", "reception", {})
        messages.success(request, "Logo tolto: il chiosco mostra di nuovo la scritta.")
        return
    upload = request.FILES.get("logo")
    if not upload:
        messages.error(request, "Scegli un file.")
        return
    try:
        validate_extension_and_mime(upload, allowed_extensions=set(chiosco.LOGO_ESTENSIONI),
                                    allowed_mimes=set(chiosco.LOGO_ESTENSIONI.values()),
                                    max_bytes=chiosco.LOGO_MAX_BYTE, label="Logo del chiosco")
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return
    estensione = os.path.splitext(upload.name)[1].lower()
    if vecchio and default_storage.exists(vecchio):
        default_storage.delete(vecchio)
    salvato = default_storage.save(f"{chiosco.LOGO_CARTELLA}/chiosco_logo{estensione}", upload).replace("\\", "/")
    SiteConfig.set(chiosco.CHIAVE_LOGO, f"{salvato}|{int(time.time())}", "Logo del chiosco della reception")
    log_action(request, "reception_logo_caricato", "reception", {"byte": upload.size})
    messages.success(request, "Logo caricato: il chiosco lo mostra dal prossimo caricamento della pagina.")


@login_required
def impostazioni(request):
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione in ("logo", "logo_togli"):
            _salva_logo(request, azione)
            return redirect("reception:impostazioni")
        if azione == "pulisci":
            mesi = int(getattr(settings, "RECEPTION_CONSERVAZIONE_MESI", 12))
            esito = servizi.pulizia_conservazione(mesi)
            log_action(request, "reception_pulizia_manuale", "reception", esito)
            messages.success(request, f"Cancellate {esito['visite']} visite e {esito['ospiti']} ospiti oltre il termine.")
        else:
            attivo = request.POST.get("avviso") == "1"
            SiteConfig.set(CHIAVE_AVVISO_REQUISITI, "1" if attivo else "0", "Chiosco: ditta non in regola, «passa dalla reception»")
            log_action(request, "reception_avviso_requisiti", "reception", {"attivo": attivo})
            messages.success(request, "Impostazione salvata.")
        return redirect("reception:impostazioni")
    mesi = int(getattr(settings, "RECEPTION_CONSERVAZIONE_MESI", 12))
    return render(request, "reception/impostazioni.html", _ctx(
        request, "impostazioni", avviso=SiteConfig.get(CHIAVE_AVVISO_REQUISITI, "0") == "1", mesi=mesi,
        logo_presente=bool(_logo_percorso()),
        n_oltre=servizi.visite_oltre_conservazione(mesi).count(),
    ))
