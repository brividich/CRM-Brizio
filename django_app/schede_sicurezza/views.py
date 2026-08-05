from __future__ import annotations

import csv
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Count, F, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.csv_export import safe_csv_writer
from core.public_headers import blinda_risposta_pubblica
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from . import pittogrammi as ghs
from .forms import ProdottoChimicoForm
from .models import SCADENZA_SDS_GIORNI, EstrazioneStato, PresaVisioneScheda, ProdottoChimico, SchedaSicurezza
from .reports import matrice_presa_visione, prodotti_senza_scheda_corrente
from .services.ingestion import estrai_sds, pittogrammi_proposti
from .services.qr import genera_qr_png

logger = logging.getLogger(__name__)

SDS_ALLOWED_EXTENSIONS = {".pdf"}
SDS_ALLOWED_MIMES = {"application/pdf"}
SDS_MAX_BYTES = 25 * 1024 * 1024  # 25 MB

PERM_VIEW = "schede_sicurezza.prodotto.view"
PERM_GESTISCI = "schede_sicurezza.prodotto.gestisci"


# ---------------------------------------------------------------------------
# Helpers ACL v2 (fail-safe: in assenza del sottosistema ricade su
# is_authenticated / is_superuser, mai su un default più permissivo)
# ---------------------------------------------------------------------------

def _can_view(request) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=PERM_VIEW,
            legacy_user=legacy_user,
            django_user=request.user,
        ).get("allowed"))
    except Exception:
        return bool(getattr(request, "user", None) and request.user.is_authenticated)


def _can_gestire(request) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=PERM_GESTISCI,
            legacy_user=legacy_user,
            django_user=request.user,
        ).get("allowed"))
    except Exception:
        return bool(getattr(request, "user", None) and request.user.is_superuser)


# ---------------------------------------------------------------------------
# Risposte pubbliche (QR): nome file e header
# ---------------------------------------------------------------------------

def _nome_file_sds(scheda) -> str:
    """Nome file dell'allegato per il ``Content-Disposition``, normalizzato.

    Il nome del prodotto è testo libero d'anagrafica: può contenere virgolette,
    barre o caratteri non ASCII. Django costruisce già l'header in modo sicuro
    (RFC 6266, niente header injection), ma passare da ``get_valid_filename``
    dà un nome prevedibile e salvabile su qualunque filesystem, invece di un
    ``filename*=utf-8''…`` illeggibile.
    """
    def _pulisci(valore: str) -> str:
        try:
            return get_valid_filename(valore)
        except SuspiciousFileOperation:
            # Nome interamente composto da caratteri scartati (o "."/".."): non
            # e' un errore da propagare, e' un nome da rimpiazzare.
            return ""

    base = _pulisci(scheda.prodotto.nome) or "scheda-sicurezza"
    versione = _pulisci(str(scheda.versione or scheda.pk))
    return f"{base}_v{versione}.pdf" if versione else f"{base}.pdf"


def _risposta_pubblica(response):
    """Header delle due view raggiungibili dal QR, senza login.

    Da quando le superfici pubbliche del portale sono più d'una, la definizione
    degli header vive in ``core.public_headers``: qui resta solo il nome locale
    già usato dalle due view. ``no-store`` è deliberato — una SDS viene
    sostituita quando il fornitore la revisiona, e una copia in cache del
    browser sopravvissuta alla revisione è esattamente il documento che non
    deve essere consultato.
    """
    return blinda_risposta_pubblica(response)


# ---------------------------------------------------------------------------
# Lista + dettaglio prodotto
# ---------------------------------------------------------------------------

# Stato SDS del prodotto: pilota il colore della barra d'accento della card e
# il badge. Unico posto in cui i tre stati sono definiti.
STATO_ACCENTO = {"ok": "#22c55e", "warn": "#f59e0b", "bad": "#ef4444"}


def _card_prodotto(prodotto) -> dict:
    """Prepara i dati di una card prodotto per il template.

    La scheda corrente arriva dal ``Prefetch`` ``schede_correnti``: il template
    non deve chiamare ``prodotto.scheda_corrente()``, che costerebbe una query
    per riga (due, visto che i template Django non memorizzano il risultato).
    """
    correnti = getattr(prodotto, "schede_correnti", None) or []
    scheda = correnti[0] if correnti else None
    if scheda is None:
        stato = "bad"
    elif scheda.scaduta:
        stato = "warn"
    else:
        stato = "ok"
    # Senza scheda (o con una scheda senza simboli) restano i pittogrammi
    # dichiarati sul prodotto: la card non si svuota in attesa della SDS.
    codici = ghs.normalizza(prodotto.pittogrammi_effettivi(scheda))
    return {
        "prodotto": prodotto,
        "scheda": scheda,
        "stato": stato,
        "accento": STATO_ACCENTO[stato],
        "pittogrammi": ghs.dettaglio(codici),
        "codici": set(codici),
        "n_dpi": getattr(prodotto, "n_dpi", 0),
        # Zero pittogrammi con estrazione OK e' un esito confermato (nessun
        # pericolo dichiarato), non un'estrazione ancora da rivedere: la card
        # non deve implicare un'azione da fare quando non ce n'e' una.
        "estrazione_ok": bool(scheda and scheda.estrazione_stato == EstrazioneStato.OK),
    }


@login_required
def prodotto_list(request):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    from anagrafica.models import Reparto

    query = request.GET.get("q", "").strip()
    reparto_id = request.GET.get("reparto", "").strip()
    famiglia = request.GET.get("famiglia", "").strip()
    stato = request.GET.get("stato", "").strip()
    pittogramma = request.GET.get("pittogramma", "").strip().upper()

    qs = (
        ProdottoChimico.objects.filter(attivo=True)
        .select_related("reparto")
        .annotate(n_dpi=Count("dpi_obbligatori", distinct=True))
        .prefetch_related(Prefetch(
            "schede",
            queryset=SchedaSicurezza.objects.filter(is_corrente=True),
            to_attr="schede_correnti",
        ))
        # Ordinamento a due livelli: le card sono raggruppate per reparto.
        .order_by("reparto__nome", "nome")
    )
    if query:
        qs = qs.filter(
            Q(nome__icontains=query)
            | Q(fornitore__icontains=query)
            | Q(codice_prodotto__icontains=query)
        )
    if reparto_id:
        qs = qs.filter(reparto_id=reparto_id)
    if famiglia:
        qs = qs.filter(famiglia=famiglia)
    # Sottoquery invece di join + distinct: con l'annotate sopra, DISTINCT +
    # ORDER BY su colonna joinata e' la combinazione che fa scattare l'errore
    # 8127 su SQL Server (SQLite la tollera, quindi non si vedrebbe in dev).
    if stato == "senza_scheda":
        qs = qs.filter(pk__in=prodotti_senza_scheda_corrente())
    elif stato == "con_scheda":
        qs = qs.filter(pk__in=SchedaSicurezza.objects.filter(
            is_corrente=True).values("prodotto_id"))
    elif stato == "da_rivedere":
        soglia = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI)
        qs = qs.filter(pk__in=SchedaSicurezza.objects.filter(
            is_corrente=True, data_caricamento__lt=soglia).values("prodotto_id"))

    cards = [_card_prodotto(prodotto) for prodotto in qs]

    # Conteggi della rastrelliera: calcolati prima del filtro per pittogramma,
    # cosi' i numeri non collassano appena se ne seleziona uno.
    conteggi = dict.fromkeys(ghs.CODICI_NOTI, 0)
    for card in cards:
        for codice in card["codici"] & ghs.CODICI_NOTI:
            conteggi[codice] += 1

    if pittogramma:
        cards = [card for card in cards if pittogramma in card["codici"]]

    # Raggruppamento per reparto in Python: la queryset e' gia' ordinata per
    # reparto, e il filtro per pittogramma non e' esprimibile in SQL in modo
    # portabile (JSONField: `contains` non esiste su SQLite).
    gruppi: list[dict] = []
    for card in cards:
        nome_reparto = card["prodotto"].reparto.nome
        if not gruppi or gruppi[-1]["reparto"] != nome_reparto:
            gruppi.append({"reparto": nome_reparto, "cards": [], "n_senza_scheda": 0})
        gruppi[-1]["cards"].append(card)
        if card["stato"] == "bad":
            gruppi[-1]["n_senza_scheda"] += 1

    return render(request, "schede_sicurezza/pages/prodotto_list.html", {
        "gruppi": gruppi,
        "n_mostrati": len(cards),
        "n_senza_scheda": sum(1 for c in cards if c["stato"] == "bad"),
        "n_da_rivedere": sum(1 for c in cards if c["stato"] == "warn"),
        "rastrelliera": [
            {"codice": codice, "nome": nome, "n": conteggi[codice], "attivo": codice == pittogramma}
            for codice, nome in ghs.PITTOGRAMMI_GHS
        ],
        "query": query,
        "reparto_selezionato": reparto_id,
        "famiglia_selezionata": famiglia,
        "stato_selezionato": stato,
        "pittogramma_selezionato": pittogramma,
        "reparti_options": Reparto.objects.filter(is_active=True).order_by("nome"),
        "famiglie_options": (
            ProdottoChimico.objects.exclude(famiglia="")
            .values_list("famiglia", flat=True).distinct().order_by("famiglia")
        ),
        "can_gestire": _can_gestire(request),
    })


@login_required
def prodotto_form(request, pk: int | None = None):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("schede_sicurezza:prodotto_list")

    prodotto = get_object_or_404(ProdottoChimico, pk=pk) if pk else None

    if request.method == "POST":
        form = ProdottoChimicoForm(request.POST, instance=prodotto)
        if form.is_valid():
            prodotto = form.save()

            # Doppio ingresso: in creazione si può generare anche l'asset di
            # inventario collegato (tipo "Prodotto chimico"). Import in-funzione
            # per non creare una dipendenza dura schede_sicurezza -> assets.
            if pk is None and request.POST.get("crea_asset") and not getattr(prodotto, "asset_container", None):
                from assets.models import Asset

                Asset.objects.create(
                    name=prodotto.nome,
                    asset_type=Asset.TYPE_CHEMICAL,
                    prodotto_chimico=prodotto,
                    asset_category=Asset.default_chemical_category(),
                )

            messages.success(request, "Prodotto salvato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=prodotto.pk)
        messages.error(request, "Controlla i campi evidenziati.")
    else:
        form = ProdottoChimicoForm(instance=prodotto)

    return render(request, "schede_sicurezza/pages/prodotto_form.html", {
        "prodotto": prodotto,
        "form": form,
        "crea_asset_checked": bool(request.POST.get("crea_asset")) if request.method == "POST" else False,
    })


@login_required
def prodotto_detail(request, pk: int):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    prodotto = get_object_or_404(ProdottoChimico.objects.select_related("reparto"), pk=pk)

    if request.method == "POST":
        if not _can_gestire(request):
            messages.error(request, "Accesso non autorizzato.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        if request.POST.get("form_type") == "modifica_campi_estratti":
            scheda_corrente = prodotto.scheda_corrente()
            if scheda_corrente is None:
                messages.error(request, "Nessuna scheda corrente da modificare.")
                return redirect("schede_sicurezza:prodotto_detail", pk=pk)

            def _parse_lista(valore: str) -> list[str]:
                return [v.strip() for v in valore.split(",") if v.strip()]

            # Il selettore invia un valore per ogni simbolo spuntato; il vecchio
            # campo a testo libero ne inviava uno solo, con le virgole dentro.
            # Entrambe le forme restano accettate.
            selezionati = request.POST.getlist("pittogrammi")
            if len(selezionati) == 1:
                selezionati = _parse_lista(selezionati[0])
            scheda_corrente.pittogrammi = ghs.normalizza(selezionati)
            scheda_corrente.frasi_h = _parse_lista(request.POST.get("frasi_h", ""))
            scheda_corrente.frasi_p = _parse_lista(request.POST.get("frasi_p", ""))
            scheda_corrente.classificazione_clp = request.POST.get("classificazione_clp", "").strip()
            scheda_corrente.dpi_testo = request.POST.get("dpi_testo", "").strip()
            scheda_corrente.primo_soccorso = request.POST.get("primo_soccorso", "").strip()
            scheda_corrente.incompatibilita = request.POST.get("incompatibilita", "").strip()
            scheda_corrente.save(update_fields=[
                "pittogrammi", "frasi_h", "frasi_p", "classificazione_clp",
                "dpi_testo", "primo_soccorso", "incompatibilita",
            ])
            # Ricopia sul prodotto: e' il set che il form prodotto ripropone e
            # quello che resta visibile se in futuro la scheda viene sostituita.
            if list(prodotto.pittogrammi or []) != list(scheda_corrente.pittogrammi):
                prodotto.pittogrammi = list(scheda_corrente.pittogrammi)
                prodotto.save(update_fields=["pittogrammi"])
            messages.success(request, "Campi estratti aggiornati.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        pdf_file = request.FILES.get("pdf")
        versione = request.POST.get("versione", "").strip()
        if not pdf_file:
            messages.error(request, "Seleziona un file PDF.")
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        try:
            validate_extension_and_mime(
                pdf_file,
                allowed_extensions=SDS_ALLOWED_EXTENSIONS,
                allowed_mimes=SDS_ALLOWED_MIMES,
                max_bytes=SDS_MAX_BYTES,
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            messages.error(request, str(exc))
            return redirect("schede_sicurezza:prodotto_detail", pk=pk)

        nuova_scheda = SchedaSicurezza.objects.create(
            prodotto=prodotto,
            pdf=pdf_file,
            versione=versione,
            caricata_da=request.user,
            is_corrente=True,
        )
        try:
            estrai_sds(nuova_scheda)
        except Exception:
            logger.exception("Estrazione SDS fallita per scheda %s", nuova_scheda.pk)

        messages.success(request, "Nuova versione della scheda caricata.")
        return redirect("schede_sicurezza:prodotto_detail", pk=pk)

    # Lo storico versioni contiene già la scheda corrente: la si pesca da lì
    # invece di rifare la query dedicata (`scheda_corrente()`).
    schede = list(prodotto.schede.order_by("-data_caricamento"))
    scheda_corrente = next((s for s in schede if s.is_corrente), None)
    return render(request, "schede_sicurezza/pages/prodotto_detail.html", {
        "prodotto": prodotto,
        "schede": schede,
        "scheda_corrente": scheda_corrente,
        "catalogo_pittogrammi": ghs.catalogo(
            selezionati=scheda_corrente.pittogrammi if scheda_corrente else [],
            proposti=pittogrammi_proposti(scheda_corrente) if scheda_corrente else [],
        ),
        "pittogrammi_correnti": ghs.dettaglio(prodotto.pittogrammi_effettivi(scheda_corrente)),
        "can_gestire": _can_gestire(request),
        "qr_url": request.build_absolute_uri(
            reverse("schede_sicurezza:scheda_mobile", args=[str(prodotto.uuid)])
        ),
    })


@login_required
def prodotto_qr(request, pk: int):
    if not _can_view(request):
        raise Http404()
    prodotto = get_object_or_404(ProdottoChimico, pk=pk)
    url = request.build_absolute_uri(
        reverse("schede_sicurezza:scheda_mobile", args=[str(prodotto.uuid)])
    )
    return HttpResponse(genera_qr_png(url), content_type="image/png")


# ---------------------------------------------------------------------------
# Vista mobile (QR) + download PDF + presa visione
# ---------------------------------------------------------------------------

def scheda_mobile(request, uuid):
    # Pubblica, senza login: e' il punto d'arrivo del QR fisico sul contenitore
    # (anche per chi non ha un account, es. un contrattista in officina). Nessuna
    # shell applicativa (sidebar/nav/ACL) per i visitatori anonimi — vedi
    # core/base_public.html. L'uuid (non un PK sequenziale) resta l'unica
    # protezione contro l'enumerazione; la pagina e' `noindex, nofollow`.
    prodotto = get_object_or_404(
        ProdottoChimico.objects.select_related("reparto").prefetch_related("dpi_obbligatori"),
        uuid=uuid,
        attivo=True,
    )
    scheda = prodotto.scheda_corrente()
    if scheda is None:
        raise Http404("Nessuna scheda di sicurezza corrente per questo prodotto.")

    # Contatore aperture del QR: incremento atomico lato DB (nessun read-modify-write,
    # quindi nessun aggiornamento perso fra due scansioni simultanee), poi rispecchiato
    # in memoria solo per il render di questa risposta (nessuna query di rilettura).
    # Conta le APERTURE, non i visitatori: la stessa persona che riapre la pagina conta
    # due volte. Deliberato: nessun fingerprint, nessun cookie, nessun IP registrato.
    ProdottoChimico.objects.filter(pk=prodotto.pk).update(visite_qr=F("visite_qr") + 1)
    prodotto.visite_qr += 1

    # La presa visione e' un atto di un operatore identificato: non ha senso per
    # un visitatore anonimo, che non vede quel blocco (vedi template).
    gia_presa_visione = (
        request.user.is_authenticated
        and PresaVisioneScheda.objects.filter(scheda=scheda, operatore=request.user).exists()
    )
    return _risposta_pubblica(render(request, "schede_sicurezza/pages/scheda_mobile.html", {
        "prodotto": prodotto,
        "scheda": scheda,
        "pittogrammi": ghs.dettaglio(scheda.pittogrammi),
        "gia_presa_visione": gia_presa_visione,
        "base_template": "core/base.html" if request.user.is_authenticated else "core/base_public.html",
    }))


def scheda_mobile_pdf(request, uuid):
    """Download pubblico del PDF corrente, con lo stesso scoping ad uuid della
    scheda mobile: mai un accesso a PK sequenziale (nessuna enumerazione).

    Il file servito è **solo** quello della scheda corrente del prodotto
    indicato: non c'è nessun parametro di percorso o di nome file che il
    chiamante possa influenzare, quindi nessuna superficie di path traversal.
    """
    prodotto = get_object_or_404(ProdottoChimico.objects.select_related("reparto"), uuid=uuid, attivo=True)
    scheda = prodotto.scheda_corrente()
    if scheda is None:
        raise Http404("Nessuna scheda di sicurezza corrente per questo prodotto.")
    try:
        fh = scheda.pdf.open("rb")
    except Exception:
        raise Http404("File non disponibile.")
    return _risposta_pubblica(
        FileResponse(fh, content_type="application/pdf", filename=_nome_file_sds(scheda))
    )


@login_required
def scheda_download(request, pk: int):
    if not _can_view(request):
        raise Http404()
    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=pk)
    try:
        fh = scheda.pdf.open("rb")
    except Exception:
        raise Http404("File non disponibile.")
    return FileResponse(fh, content_type="application/pdf", filename=_nome_file_sds(scheda))


@login_required
@require_POST
def presa_visione_conferma(request, scheda_pk: int):
    if not _can_view(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=scheda_pk)
    note = request.POST.get("note", "").strip()
    _, created = PresaVisioneScheda.objects.get_or_create(
        scheda=scheda, operatore=request.user, defaults={"note": note},
    )
    if created:
        messages.success(request, "Presa visione registrata.")
    else:
        messages.info(request, "Presa visione già registrata per questa versione.")

    if getattr(request, "htmx", False):
        return render(request, "schede_sicurezza/partials/_presa_visione_stato.html", {
            "gia_presa_visione": True,
        })
    return redirect("schede_sicurezza:scheda_mobile", uuid=scheda.prodotto.uuid)


@login_required
def presa_visione_list(request, scheda_pk: int):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")
    scheda = get_object_or_404(SchedaSicurezza.objects.select_related("prodotto"), pk=scheda_pk)
    prese = scheda.prese_visione.select_related("operatore").order_by("-data_presa_visione")
    return render(request, "schede_sicurezza/pages/presa_visione_list.html", {
        "scheda": scheda,
        "prese": prese,
    })


# ---------------------------------------------------------------------------
# Report compliance SDS
# ---------------------------------------------------------------------------

@login_required
def report_compliance(request):
    if not _can_gestire(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dashboard:dashboard")

    formato = request.GET.get("formato", "").strip()
    sezione = request.GET.get("sezione", "").strip()

    if formato == "csv" and sezione == "gap":
        return _csv_gap_sds(prodotti_senza_scheda_corrente())
    if formato == "csv" and sezione == "matrice":
        return _csv_matrice_presa_visione(matrice_presa_visione())

    return render(request, "schede_sicurezza/pages/report_compliance.html", {
        "gap": prodotti_senza_scheda_corrente(),
        "matrice": matrice_presa_visione(),
    })


def _csv_gap_sds(prodotti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_gap_sds.csv"'
    writer = safe_csv_writer(response)
    writer.writerow(["Prodotto", "Reparto", "Fornitore"])
    for p in prodotti:
        writer.writerow([p.nome, p.reparto.nome, p.fornitore])
    return response


def _csv_matrice_presa_visione(reparti):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="schede_sicurezza_matrice_presa_visione.csv"'
    writer = safe_csv_writer(response)
    writer.writerow(["Reparto", "Prodotto", "Versione scheda", "Dipendenti totali", "Confermati", "Percentuale"])
    for reparto in reparti:
        for riga in reparto.righe:
            percentuale = "n/d" if riga.percentuale is None else f"{riga.percentuale}%"
            writer.writerow([
                reparto.reparto_nome, riga.prodotto_nome, riga.scheda_versione,
                riga.totale_dipendenti, riga.confermati, percentuale,
            ])
    return response
