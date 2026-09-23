# Manutenzione asset — checklist UI/UX (round 2)

Avviata il 23/09/2026 dopo il riordino F1–F4 (menu unico, Calendario, Scadenzario,
Panoramica, KPI, fine della doppia fonte delle scadenze amministrative).
Branch: `feature/assets-manutenzione-ux2`. Ogni voce si spunta quando e' fatta
e testata; la verifica a video (chiaro + scuro) e' nel blocco Chiusura.

## Priorita' alta — togliere i doppioni rimasti

- [x] **1. Panoramica senza numeri ripetuti** — via le tessere "Scadute" e "In scadenza"
  gia' presenti nei riquadri per tipologia; restano non pianificate, OdL aperti,
  rapporti mancanti, in attesa, anzianita' OdL, follow-up, conflitti.
- [x] **2. Via lo switch Operativo/Sintesi** — la Sintesi e' la pagina KPI;
  `?vista=sintesi` sulla Panoramica rimanda a KPI.
- [x] **3. Testate pulite** — i pulsanti che ripetono la barra di sezione escono;
  le azioni di sezione (+ Nuovo intervento, Esporta OdL, + Nuovo piano) compaiono
  solo nelle pagine dove servono.

## Priorita' media — chi usa cosa

- [ ] **4. Da fare = pagina del manutentore** — di default il mio lavoro + quello
  non assegnato, righe grandi da tablet, "Registra" sempre a vista.
- [ ] **5. Crea OdL dal Calendario** — dal pannello dettaglio di un'occorrenza, e
  selezione multipla nella vista Settimana per un OdL unico.
- [ ] **6. Export Scadenzario** — Excel e PDF con gli stessi filtri (`core/table_pdf.py`).
- [ ] **7. Scheda asset sulla stessa fonte** — manutenzioni, adempimenti, licenze e
  contratti dell'asset dal `deadline_feed`, con link al Calendario filtrato.

## Setup

- [ ] **8. Percorso "Imposta la manutenzione"** — 4 passi con stato: catalogo attivita',
  piani, applicazioni agli asset, copertura (asset in uso senza piano).
- [ ] **9. Gruppi asset spiegati** — filtro Gruppo nascosto finche' non esiste un gruppo;
  la pagina Gruppi spiega la differenza con le famiglie.

## Pulizia di fondo

- [x] **10. Colori delle tipologie in un posto solo** — token in
  `maintenance_domain_styles.html`, usati da Calendario e Panoramica.
- [ ] **11. Ultimi numeri sul vecchio motore** — Dashboard officina, "PM compliance"
  dei Report e tessere "Verifiche periodiche" della Dashboard asset allineati alla
  stessa fonte (o ritirati).
- [ ] **12. Contatore su "Da fare"** — badge nel menu laterale con scadute e mie.

## Chiusura

- [ ] Test `assets` + `dashboard` + `core` verdi
- [ ] Verifica a video chiaro + scuro
- [ ] CHANGELOG + README
- [ ] Merge `main` → `release/prod`
