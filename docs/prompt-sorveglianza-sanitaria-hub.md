# TASK: Integrazione modulo Sorveglianza Sanitaria — riconoscimento automatico referti scansionati

## CONTESTO
Sto scansionando in blocco i certificati medici di idoneità (visite periodiche INAIL/D.Lgs 81/08)
forniti dal medico competente. Voglio che il HUB:
1. Riceva un upload multiplo di PDF scansionati (spesso solo immagine, senza layer testo affidabile)
2. Estragga da ciascun PDF: nome dipendente, data del giudizio di idoneità, tipo di esame se presente
3. Abbini automaticamente il referto al dipendente in anagrafica e alla scadenza di sorveglianza sanitaria attesa
4. "Spunti" la visita come effettuata, allegando il PDF rinominato, con una coda di revisione manuale
   per i match incerti (nome OCR sporco, dipendente non trovato, scadenze multiple aperte)

Ho già uno script standalone funzionante e VALIDATO su più certificati reali (pdfplumber + fallback
OCR con pytesseract/pdf2image, lingua ita) che estrae nome e data da questo template specifico
(software Winasped). Ho già impacchettato una versione .exe portable (PyInstaller + Tesseract/Poppler
bundled) usata in produzione a mano dalla segreteria. Lo allego sotto come riferimento per la logica
di estrazione — NON deve restare uno script CLI: la logica va portata dentro il HUB come servizio
richiamabile da un job in background (django-q2), coerente con lo stack esistente. Sentiti libero di
ottimizzare/riscrivere l'implementazione (es. adattarla a un servizio Django, cambiare libreria OCR
se ne trovi una più adatta), ma MANTIENI la logica di estrazione già validata:
- il nome dipendente va letto dal campo anagrafico (accanto a "Data Nascita"), NON dalla riga di
  firma "Il Lavoratore ...:" — quest'ultima è spesso illeggibile perché coperta dalla firma
  manoscritta sopra di essa. Nello script è tenuta solo come fallback secondario.
- la data di riferimento è quella del giudizio di idoneità ("Espresso il ...")
- il fallback OCR scatta solo se il testo diretto del PDF è troppo corto o non contiene il nome
  nel campo atteso — molti PDF hanno già un layer testo sufficiente e non serve OCR

## STEP 0 — INVESTIGAZIONE OBBLIGATORIA (nessun codice prima di questo)
Prima di proporre qualunque modello o architettura:
1. Ispeziona il sottomodulo Formazione (anagrafica/formazione/) e riporta: come è modellato
   TrainingDeadline, come vengono gestite scadenza/periodicità/completamento, come si collega
   a legacy_anagrafica_id, come sono strutturati services/selectors/workflows in quell'app.
2. Verifica se esiste GIÀ, in qualunque punto della codebase (anche parziale/abbozzato), un modello
   per sorveglianza sanitaria, protocollo sanitario, visite mediche, idoneità mansione. Cerca anche
   riferimenti a "medico competente", "idoneità", "protocollo sanitario", "visita medica" in models,
   migrations, fixtures.
3. Verifica come vengono gestiti oggi upload/allegati di documenti sensibili nel HUB (es. modulo
   contratti, licenze, SharePoint docs in Asset) — voglio riutilizzare lo stesso pattern di storage,
   non inventarne uno nuovo.
4. Verifica come è strutturato l'ACL v2 per capire come creare/riusare un gruppo con accesso
   ristretto (dati sanitari = art. 9 GDPR, accesso deve essere granulare, non "tutti gli utenti HUB").

## STEP 1 — ADR (fermati qui e aspetta la mia approvazione prima di scrivere codice)
Sulla base dell'investigazione, produci un ADR che copra:
- Se riusare/estendere uno scheletro esistente o modellare da zero (motiva la scelta)
- Schema dati proposto: dipendente, tipo esame, periodicità attesa, data ultima esecuzione,
  prossima scadenza calcolata, stato (in scadenza/scaduta/completata/in revisione), riferimento
  al PDF allegato, log di chi ha confermato un match manuale e quando
- Architettura della pipeline di estrazione: dove vive il servizio di parsing (riuso/ottimizzazione
  della logica pdfplumber+OCR fallback), come viene invocato da un job django-q2, gestione
  errori/timeout OCR su batch grandi, idempotenza (rilancio sicuro se un file fallisce)
- Algoritmo di matching: fuzzy match nome (proponi libreria e soglia), come si risolve un dipendente
  non trovato o un match ambiguo (>1 candidato sopra soglia), come si sceglie la scadenza corretta
  quando un dipendente ha più esami/scadenze aperte nello stesso periodo
- UI: pagina di upload multiplo, coda di revisione (match auto-confermati vs da confermare a mano),
  vista scadenzario coerente con lo stile esistente (card system navy/cyan, come in Formazione)
- ACL: quale gruppo ha accesso (proponi nome coerente col pattern esistente, es. SMS_TEAM per
  Suggestion Corner), differenza tra chi può caricare/revisionare e chi può solo consultare lo stato
- Piano di test: coerente con lo standard del progetto (Formazione ha 275 test specifici) — copertura
  minima per: estrazione OCR su PDF corrotti/illeggibili, fuzzy matching con nomi ambigui, race
  condition su upload concorrenti, permessi ACL negati correttamente
- Edge case da elencare esplicitamente: PDF non leggibile né con testo né con OCR, dipendente
  cessato/non più in anagrafica, referto duplicato (stesso dipendente+data caricato due volte),
  scansione con più pagine/più certificati in un unico PDF

## STEP 2 — GATE ESPLICITO
Non procedere all'implementazione. Presenta l'ADR e FERMATI, aspettando la mia approvazione
esplicita (coerente col mio workflow: architettura prima, poi prompt di fase a implementazione).

## STEP 3 (solo dopo mia approvazione)
Proponi la sequenza di prompt a fasi per l'implementazione (migrations → servizio estrazione →
job background → matching → UI upload → UI coda revisione → ACL → test), seguendo la policy
sequential-only per i subagent (niente esecuzione parallela, RAM limitata).

---

## RIFERIMENTO — script standalone esistente (proof-of-concept, da ottimizzare/riportare nel servizio)

```python
#!/usr/bin/env python3
"""
Rinomina automaticamente i certificati medici di idoneità (Winasped) scansionati,
in base a: Cognome_Nome + Data giudizio di idoneità.

Uso:
    python3 rinomina_certificati.py /percorso/cartella/scansioni

Requisiti:
    pip install pdfplumber pytesseract pdf2image --break-system-packages
    apt-get install tesseract-ocr tesseract-ocr-ita poppler-utils

Formato output file: Cognome_Nome_YYYY-MM-DD.pdf
Se il file esiste già, aggiunge un suffisso numerico (_2, _3, ...).
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

import pdfplumber

# --- OCR fallback (solo se il testo non è estraibile direttamente) ---
try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def get_app_dir() -> Path:
    """Cartella dell'eseguibile (se pacchettizzato con PyInstaller) o dello script .py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def setup_portable_binaries():
    """
    Se esistono le cartelle tesseract-bin/ e poppler-bin/ accanto all'eseguibile,
    le usa al posto di quelle di sistema (per distribuzione portable su altri PC).
    Se non esistono, si affida al PATH di sistema (comportamento dev normale).
    Restituisce il poppler_path da passare a convert_from_path (None = usa PATH).
    """
    app_dir = get_app_dir()
    poppler_path = None

    tesseract_exe = app_dir / "tesseract-bin" / "tesseract.exe"
    if tesseract_exe.exists() and OCR_AVAILABLE:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_exe)
        tessdata_dir = app_dir / "tesseract-bin" / "tessdata"
        if tessdata_dir.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
        print(f"[i] Uso Tesseract portable: {tesseract_exe}")

    poppler_bin = app_dir / "poppler-bin"
    if poppler_bin.exists():
        poppler_path = str(poppler_bin)
        print(f"[i] Uso Poppler portable: {poppler_bin}")

    return poppler_path


# Pattern noti nel template Winasped dei certificati di idoneità
# Ordine di priorità: il campo anagrafico (accanto a Data Nascita) è la fonte primaria,
# perché è testo stampato affidabile. La riga di firma "Il Lavoratore ...:" è tenuta
# come fallback, ma spesso viene coperta/rovinata dalla firma manoscritta sopra di essa.
NAME_PATTERNS = [
    r"Data\s+Nascita\s+\d{2}[-/]\d{2}[-/]\d{4}\s+([A-ZÀ-Ù][A-ZÀ-Ù'\s]{2,40}?)\s*[\n\r]",  # campo anagrafico
    r"Il\s+Lavoratore\s+([A-ZÀ-Ù'\s]+?)\s*:",   # fallback: "Il Lavoratore AMMANNATI ALBERTO:"
]
DATE_PATTERNS = [
    r"Espresso\s+il\s+(\d{2}-\d{2}-\d{4})",      # data del giudizio di idoneità
    r"Trasmesso\s+al\s+lavoratore\s+il\.{1,2}(\d{2}-\d{2}-\d{4})",
]


def extract_text_pdfplumber(pdf_path: Path) -> str:
    """Prova estrazione testo diretta (funziona se il PDF ha già un layer testo/OCR)."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        print(f"  [!] pdfplumber fallito su {pdf_path.name}: {e}")
    return text


def extract_text_ocr(pdf_path: Path, poppler_path: str | None = None) -> str:
    """Fallback OCR per PDF puramente immagine (scansioni senza testo)."""
    if not OCR_AVAILABLE:
        print("  [!] OCR non disponibile: installare pytesseract e pdf2image")
        return ""
    text = ""
    try:
        images = convert_from_path(pdf_path, dpi=300, poppler_path=poppler_path)
        for img in images:
            text += pytesseract.image_to_string(img, lang="ita") + "\n"
    except Exception as e:
        print(f"  [!] OCR fallito su {pdf_path.name}: {e}")
    return text


def get_text(pdf_path: Path, poppler_path: str | None = None) -> str:
    text = extract_text_pdfplumber(pdf_path)
    # Fallback OCR se: (a) testo troppo corto (scansione immagine pura), oppure
    # (b) il nome non è individuabile nel layer testo — capita spesso che il layer
    # testo dello scanner "perda" la riga della firma "Il Lavoratore ...:".
    needs_ocr = len(text.strip()) < 50 or extract_field(text, NAME_PATTERNS) is None
    if needs_ocr:
        print(f"  -> Nome non trovato nel testo diretto, provo OCR per {pdf_path.name}...")
        ocr_text = extract_text_ocr(pdf_path, poppler_path=poppler_path)
        if ocr_text.strip():
            text = text + "\n" + ocr_text
    return text


def extract_field(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def normalize_date(raw_date: str) -> str:
    """'21-05-2024' -> '2024-05-21' (ordinabile)"""
    dd, mm, yyyy = raw_date.split("-")
    return f"{yyyy}-{mm}-{dd}"


def format_name(raw_name: str) -> str:
    """'AKSOY DERYA' -> 'Aksoy Derya' (Title Case, spazi tra le parole)"""
    parts = raw_name.split()
    return " ".join(p.capitalize() for p in parts)


def build_new_filename(text: str, fallback_stem: str) -> str:
    name = extract_field(text, NAME_PATTERNS)
    date = extract_field(text, DATE_PATTERNS)

    name_part = format_name(name) if name else "NOME SCONOSCIUTO"
    date_part = normalize_date(date) if date else "DATA SCONOSCIUTA"

    if name is None or date is None:
        print(f"  [!] Estrazione incompleta (nome={name}, data={date}) — controllare manualmente: {fallback_stem}")

    return f"{name_part} IDONEITA {date_part}.pdf"


def process_folder(folder: Path, dry_run: bool = False, poppler_path: str | None = None):
    pdf_files = sorted(folder.glob("*.pdf"))
    if not pdf_files:
        print(f"Nessun PDF trovato in {folder}")
        return

    used_names = set()

    for pdf_path in pdf_files:
        print(f"\nElaboro: {pdf_path.name}")
        text = get_text(pdf_path, poppler_path=poppler_path)
        if not text.strip():
            print(f"  [X] Impossibile estrarre testo da {pdf_path.name}, salto.")
            continue

        new_name = build_new_filename(text, pdf_path.stem)

        # Gestione duplicati (es. stesso dipendente, stesso giorno, scansioni multiple)
        base_new_name = new_name
        counter = 2
        while new_name in used_names or (folder / new_name).exists():
            stem = base_new_name.rsplit(".pdf", 1)[0]
            new_name = f"{stem}_{counter}.pdf"
            counter += 1
        used_names.add(new_name)

        new_path = folder / new_name
        print(f"  -> {pdf_path.name}  =>  {new_name}")

        if not dry_run:
            shutil.move(str(pdf_path), str(new_path))


def run_interactive():
    """Modalità doppio-click: chiede la cartella, mostra anteprima, chiede conferma."""
    print("=" * 60)
    print(" RINOMINA CERTIFICATI MEDICI - Costruzioni Novicrom")
    print("=" * 60)
    print()
    folder_input = input("Trascina qui la cartella con le scansioni e premi INVIO: ").strip().strip('"')
    folder = Path(folder_input)

    if not folder.is_dir():
        print(f"\n[X] '{folder}' non è una cartella valida.")
        input("\nPremi INVIO per uscire...")
        sys.exit(1)

    poppler_path = setup_portable_binaries()

    print("\n--- ANTEPRIMA (nessun file verrà ancora modificato) ---")
    process_folder(folder, dry_run=True, poppler_path=poppler_path)

    print("\n" + "=" * 60)
    risposta = input("Confermi la rinomina dei file sopra elencati? (s/n): ").strip().lower()
    if risposta in ("s", "si", "sì", "y", "yes"):
        print("\n--- RINOMINA IN CORSO ---")
        process_folder(folder, dry_run=False, poppler_path=poppler_path)
        print("\nFatto! I file sono stati rinominati.")
    else:
        print("\nOperazione annullata. Nessun file è stato modificato.")

    input("\nPremi INVIO per uscire...")


def main():
    # Modalità doppio-click: nessun argomento da riga di comando -> chiedi interattivamente
    if len(sys.argv) == 1:
        run_interactive()
        return

    parser = argparse.ArgumentParser(description="Rinomina certificati medici scansionati per nome dipendente + data")
    parser.add_argument("folder", type=str, help="Cartella contenente le scansioni PDF")
    parser.add_argument("--dry-run", action="store_true", help="Mostra solo l'anteprima, non rinomina i file")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Errore: {folder} non è una cartella valida.")
        sys.exit(1)

    poppler_path = setup_portable_binaries()
    process_folder(folder, dry_run=args.dry_run, poppler_path=poppler_path)
    print("\nCompletato.")


if __name__ == "__main__":
    main()
```
