"""Foglio firme con QR e geometria registrata (catena dell'evidenza, anello 6).

Il registro cartaceo resta l'unico documento che un ispettore accetta senza
discutere. L'obiettivo è farlo diventare **anche il modo di compilare il
portale**, invece di essere una seconda cosa da fare dopo.

Le tre scelte che rendono la cosa fattibile senza riconoscimento del testo:

1. **Il foglio lo genera il portale**, quindi l'elenco e l'ordine delle righe
   sono noti. Vengono *congelati* nel foglio emesso: se dopo si aggiunge un
   iscritto, la riga 7 della scansione resta la persona di allora.
2. **Un QR porta il token del foglio**: al caricamento non c'è nulla da
   scegliere e nessun aggancio da sbagliare.
3. **Quattro marcatori d'angolo** permettono di raddrizzare una scansione
   storta o di scala diversa. Da lì, sapere chi ha firmato non richiede di
   *leggere* la firma: basta misurare se il rettangolo della riga 7 contiene
   inchiostro. È geometria e una soglia, non intelligenza artificiale.

Qui si genera il foglio e si registra la geometria. La lettura della scansione
userà queste stesse coordinate.
"""
from __future__ import annotations

import secrets
from io import BytesIO

__all__ = [
    "MARCATORE_MM",
    "build_foglio_firme_pdf",
    "emetti_foglio_firme",
    "genera_token",
]

# Lato dei quadrati d'angolo e loro distanza dal bordo pagina, in millimetri.
# Sono la terna di riferimento con cui si raddrizza la scansione.
MARCATORE_MM = 6.0
MARGINE_MARCATORE_MM = 8.0


def genera_token() -> str:
    """Token breve, leggibile e non indovinabile, per il QR.

    Niente caratteri ambigui: se qualcuno deve ribatterlo a mano perché il QR
    è rovinato, «0/O» e «1/I» sono una trappola.
    """
    from ..models_formazione import TrainingSignatureSheet

    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(50):
        token = "".join(secrets.choice(alfabeto) for _ in range(10))
        if not TrainingSignatureSheet.objects.filter(token=token).exists():
            return token
    raise RuntimeError("impossibile generare un token univoco per il foglio firme")


def _righe_congelate(lezione) -> list[dict]:
    """Elenco ordinato degli attesi alla giornata, come sarà stampato."""
    from .attestato_pdf import _nomi_map
    from .training_turni import iscritti_attesi_lezione

    attesi = [e.legacy_anagrafica_id for e in iscritti_attesi_lezione(lezione.sessione, lezione)]
    nomi = _nomi_map(attesi)
    coppie = sorted(
        ((lid, nomi.get(lid, f"#{lid}")) for lid in attesi),
        key=lambda c: c[1].casefold(),
    )
    return [
        {"n": n, "legacy_id": lid, "nome": nome}
        for n, (lid, nome) in enumerate(coppie, start=1)
    ]


def _qr_immagine(testo: str):
    """QR come immagine pronta per reportlab."""
    import qrcode
    from reportlab.lib.utils import ImageReader

    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(testo)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


class _TabellaFirme:
    """Raccoglitore della geometria: la tabella disegna, questo annota dove."""

    def __init__(self):
        self.celle: list[dict] = []


def build_foglio_firme_pdf(lezione, righe: list[dict], token: str) -> tuple[bytes, dict]:
    """PDF del foglio firme e geometria delle celle.

    Ritorna ``(pdf, geometria)``. La geometria è in **millimetri dall'angolo in
    alto a sinistra** della pagina — non dal basso come vuole il PDF — perché è
    così che si ragiona su un'immagine scansionata.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas

    larghezza, altezza = A4
    buf = BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Foglio firme {token}")

    sessione = lezione.sessione
    corso = sessione.corso

    # ── marcatori d'angolo ────────────────────────────────────────────────
    lato = MARCATORE_MM * mm
    off = MARGINE_MARCATORE_MM * mm
    c.setFillColorRGB(0, 0, 0)
    for x, y in (
        (off, altezza - off - lato),          # alto-sinistra
        (larghezza - off - lato, altezza - off - lato),  # alto-destra
        (off, off),                            # basso-sinistra
        (larghezza - off - lato, off),         # basso-destra
    ):
        c.rect(x, y, lato, lato, stroke=0, fill=1)

    # ── intestazione ──────────────────────────────────────────────────────
    x_testo = 20 * mm
    y = altezza - 22 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x_testo, y, "Registro presenze")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x_testo, y, f"{corso.titolo[:70]}")
    y -= 5 * mm
    data = lezione.data.strftime("%d-%m-%Y") if lezione.data else "—"
    orario = "—"
    if lezione.ora_inizio and lezione.ora_fine:
        orario = f"{lezione.ora_inizio:%H:%M}–{lezione.ora_fine:%H:%M}"
    c.setFont("Helvetica", 9)
    c.drawString(x_testo, y, f"Edizione {sessione.codice_sessione}   ·   Giornata {lezione.numero}"
                             f"   ·   {data}   ·   {orario}")
    y -= 5 * mm
    docente = (lezione.docente_nome or "").strip() or (sessione.docente_nome or "").strip()
    if docente:
        c.drawString(x_testo, y, f"Docente: {docente[:60]}")
        y -= 5 * mm
    if lezione.argomento:
        c.drawString(x_testo, y, f"Argomento: {lezione.argomento[:80]}")
        y -= 5 * mm

    # ── QR con il token ───────────────────────────────────────────────────
    qr_lato = 26 * mm
    qr_x = larghezza - 20 * mm - qr_lato
    qr_y = altezza - 22 * mm - qr_lato + 4 * mm
    c.drawImage(_qr_immagine(token), qr_x, qr_y, qr_lato, qr_lato)
    c.setFont("Helvetica", 7)
    c.drawCentredString(qr_x + qr_lato / 2, qr_y - 3.5 * mm, token)

    # ── tabella a passo fisso ─────────────────────────────────────────────
    # Disegnata a mano e non con un flowable: qui la posizione di ogni cella
    # deve essere nota al millimetro, perché è la stessa che rileggerà la
    # scansione. Un layout che "scorre" non lo garantirebbe.
    x0 = 20 * mm
    x_fine = larghezza - 20 * mm
    w_num, w_firma = 10 * mm, 52 * mm
    w_nome = (x_fine - x0) - w_num - 2 * w_firma
    h_riga = 11 * mm
    y_testa = min(y - 4 * mm, qr_y - 8 * mm)

    colonne = [
        ("#", x0, w_num),
        ("Cognome e Nome", x0 + w_num, w_nome),
        ("Firma ingresso", x0 + w_num + w_nome, w_firma),
        ("Firma uscita", x0 + w_num + w_nome + w_firma, w_firma),
    ]

    c.setFillColorRGB(0.05, 0.15, 0.27)
    c.rect(x0, y_testa - h_riga, x_fine - x0, h_riga, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 8.5)
    for etichetta, cx, cw in colonne:
        c.drawString(cx + 2 * mm, y_testa - h_riga + 4 * mm, etichetta)

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.4)
    c.setFillColorRGB(0, 0, 0)

    def mm_da_alto(y_pdf: float) -> float:
        return (altezza - y_pdf) / mm

    celle: list[dict] = []
    y_riga = y_testa - h_riga
    minime = max(len(righe), 16)
    for idx in range(minime):
        y_riga -= h_riga
        riga = righe[idx] if idx < len(righe) else None
        for _, cx, cw in colonne:
            c.rect(cx, y_riga, cw, h_riga, stroke=1, fill=0)
        c.setFont("Helvetica", 9)
        c.drawCentredString(x0 + w_num / 2, y_riga + 4 * mm, str(riga["n"] if riga else idx + 1))
        if riga:
            c.drawString(x0 + w_num + 2 * mm, y_riga + 4 * mm, riga["nome"][:52])
            for chiave, cx, cw in (
                ("ingresso", x0 + w_num + w_nome, w_firma),
                ("uscita", x0 + w_num + w_nome + w_firma, w_firma),
            ):
                celle.append({
                    "riga": riga["n"],
                    "legacy_id": riga["legacy_id"],
                    "campo": chiave,
                    "x_mm": round(cx / mm, 2),
                    "y_mm": round(mm_da_alto(y_riga + h_riga), 2),
                    "w_mm": round(cw / mm, 2),
                    "h_mm": round(h_riga / mm, 2),
                })
        if y_riga < 30 * mm:
            break

    c.setFont("Helvetica", 9)
    c.drawString(x0, max(y_riga - 10 * mm, 20 * mm),
                 "Firma del docente: ______________________________")

    c.showPage()
    c.save()

    geometria = {
        "versione": 1,
        "pagina_mm": [round(larghezza / mm, 2), round(altezza / mm, 2)],
        "marcatore_mm": MARCATORE_MM,
        "margine_marcatore_mm": MARGINE_MARCATORE_MM,
        "celle": celle,
    }
    return buf.getvalue(), geometria


def emetti_foglio_firme(lezione, user=None):
    """Emette un foglio firme per la giornata e ne restituisce ``(foglio, pdf)``.

    Ogni emissione crea un foglio nuovo: ristampare dopo aver aggiunto un
    iscritto **deve** produrre un documento diverso, altrimenti due fogli con lo
    stesso token porterebbero elenchi diversi.
    """
    from ..models_formazione import TrainingSignatureSheet

    righe = _righe_congelate(lezione)
    token = genera_token()
    pdf, geometria = build_foglio_firme_pdf(lezione, righe, token)
    foglio = TrainingSignatureSheet.objects.create(
        lezione=lezione, token=token, righe=righe, geometria=geometria, emesso_da=user,
    )
    return foglio, pdf
