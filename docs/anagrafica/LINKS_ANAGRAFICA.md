# Anagrafica — Elenco link pagine navigabili

Riferimento per topnav / menu generale. Solo le **pagine navigabili** (GET):
escluse azioni POST/CRUD, export, API e partial HTMX.

- Prefisso URL: `/anagrafica/`
- Namespace Django: `anagrafica` → uso in template: `{% url 'anagrafica:<name>' %}`
- Totale: 44 pagine

| Sezione | Voce | URL | name (`anagrafica:`) |
|---|---|---|---|
| Dashboard | Home modulo | `/anagrafica/` | `index` |
| Dipendenti | Elenco dipendenti | `/anagrafica/dipendenti/` | `dipendenti_list` |
| Dipendenti | Ex dipendenti | `/anagrafica/ex-dipendenti/` | `ex_dipendenti_list` |
| Dipendenti | Nuovo dipendente | `/anagrafica/dipendenti/nuovo/` | `dipendente_create` |
| Dipendenti | Report dipendenti | `/anagrafica/dipendenti/report/` | `dipendenti_report` |
| Visite mediche | Dashboard visite | `/anagrafica/visite-mediche/` | `visite_mediche_dashboard` |
| Visite mediche | Nuova sessione | `/anagrafica/visite-mediche/nuova-sessione/` | `visite_mediche_nuova_sessione` |
| Documenti | Elenco documenti | `/anagrafica/documenti/` | `documenti_list` |
| Scadenzario | Scadenzario unificato | `/anagrafica/scadenzario/` | `scadenzario` |
| Conformità | Report idoneità mansione | `/anagrafica/conformita/` | `conformita_report` |
| Organigramma | Organigramma visuale | `/anagrafica/organigramma/` | `organigramma` |
| Sicurezza | Hub sicurezza | `/anagrafica/sicurezza/` | `sicurezza_hub` |
| Sicurezza | Ricerca | `/anagrafica/sicurezza/ricerca/` | `sicurezza_ricerca` |
| Sicurezza | Guida | `/anagrafica/sicurezza/guida/` | `sicurezza_wizard` |
| Sicurezza | Matrice competenze | `/anagrafica/sicurezza/matrice/` | `matrice_competenze` |
| Onboarding | Elenco pratiche | `/anagrafica/onboarding/` | `onboarding_list` |
| Formazione | Dashboard | `/anagrafica/formazione/` | `formazione_dashboard` |
| Formazione | Ricerca | `/anagrafica/formazione/ricerca/` | `formazione_ricerca` |
| Formazione | Piani formativi | `/anagrafica/formazione/piani/` | `formazione_piani_list` |
| Formazione | Corsi | `/anagrafica/formazione/corsi/` | `formazione_corsi_list` |
| Formazione | E-learning (hub HR) | `/anagrafica/formazione/elearning/` | `formazione_elearning_hub` |
| Formazione | E-learning impostazioni | `/anagrafica/formazione/elearning/impostazioni/` | `formazione_elearning_settings` |
| Formazione | Corsi online (discente) | `/anagrafica/formazione/corsi-online/` | `formazione_online_catalog` |
| Formazione | Istruttori | `/anagrafica/formazione/istruttori/` | `formazione_istruttori_list` |
| Formazione | Sessioni | `/anagrafica/formazione/sessioni/` | `formazione_sessioni_list` |
| Formazione | Scadenzario | `/anagrafica/formazione/scadenzario/` | `formazione_scadenzario` |
| Formazione | Copertura / gap | `/anagrafica/formazione/copertura/` | `formazione_copertura` |
| Formazione | Plan (calendario) | `/anagrafica/formazione/plan/` | `formazione_plan` |
| Formazione · Rischi | Fattori di rischio | `/anagrafica/formazione/rischi/fattori/` | `fattori_rischio_list` |
| Formazione · Rischi | Categorie corso | `/anagrafica/formazione/rischi/categorie/` | `categorie_corso_list` |
| Formazione · Rischi | Esposizioni | `/anagrafica/formazione/rischi/esposizioni/` | `esposizioni_rischio_list` |
| Formazione | Impostazioni attestato | `/anagrafica/formazione/attestato-impostazioni/` | `attestato_impostazioni` |
| Retribuzioni | Import voci retributive | `/anagrafica/retribuzioni/` | `retribuzioni_import` |
| Retribuzioni | Vista globale (pivot) | `/anagrafica/retribuzioni/globale/` | `retribuzioni_globale` |
| Contratti | Import storico contrattuale | `/anagrafica/contratti/` | `contratti_import` |
| Cedolini | Import cedolini | `/anagrafica/cedolini/` | `cedolini_import` |
| Ratei | Lista ratei | `/anagrafica/ratei/` | `ratei_list` |
| Cataloghi | Mansioni | `/anagrafica/mansioni/` | `mansioni_list` |
| Cataloghi | Aree / Reparti | `/anagrafica/aree/` | `aree_list` |
| Cataloghi | Ruoli aziendali | `/anagrafica/ruoli-aziendali/` | `ruoli_aziendali_list` |
| Cataloghi | Ruoli operativi | `/anagrafica/ruoli-operativi/` | `ruoli_operativi_list` |
| Qualifiche | Cruscotto | `/anagrafica/qualifiche/cruscotto/` | `qualifiche_dashboard` |
| Qualifiche | Catalogo qualifiche | `/anagrafica/qualifiche/` | `qualifiche_list` |
| Qualifiche | Scadenzario qualifiche | `/anagrafica/qualifiche/scadenzario/` | `qualifiche_scadenzario` |
| Qualifiche | Sessioni di rinnovo | `/anagrafica/qualifiche/sessioni/` | `qualifica_sessioni_list` |
| Impostazioni | Pannello impostazioni HR | `/anagrafica/impostazioni/` | `impostazioni` |
| Impostazioni | Permessi widget | `/anagrafica/impostazioni-widget/` | `widget_permissions` |

---

## Elenco semplice (solo URL)

```
/anagrafica/
/anagrafica/dipendenti/
/anagrafica/ex-dipendenti/
/anagrafica/dipendenti/nuovo/
/anagrafica/dipendenti/report/
/anagrafica/visite-mediche/
/anagrafica/visite-mediche/nuova-sessione/
/anagrafica/documenti/
/anagrafica/scadenzario/
/anagrafica/conformita/
/anagrafica/organigramma/
/anagrafica/sicurezza/
/anagrafica/sicurezza/ricerca/
/anagrafica/sicurezza/guida/
/anagrafica/sicurezza/matrice/
/anagrafica/onboarding/
/anagrafica/formazione/
/anagrafica/formazione/ricerca/
/anagrafica/formazione/piani/
/anagrafica/formazione/corsi/
/anagrafica/formazione/elearning/
/anagrafica/formazione/elearning/impostazioni/
/anagrafica/formazione/corsi-online/
/anagrafica/formazione/istruttori/
/anagrafica/formazione/sessioni/
/anagrafica/formazione/scadenzario/
/anagrafica/formazione/copertura/
/anagrafica/formazione/plan/
/anagrafica/formazione/rischi/fattori/
/anagrafica/formazione/rischi/categorie/
/anagrafica/formazione/rischi/esposizioni/
/anagrafica/formazione/attestato-impostazioni/
/anagrafica/retribuzioni/
/anagrafica/retribuzioni/globale/
/anagrafica/contratti/
/anagrafica/cedolini/
/anagrafica/ratei/
/anagrafica/mansioni/
/anagrafica/aree/
/anagrafica/ruoli-aziendali/
/anagrafica/ruoli-operativi/
/anagrafica/qualifiche/cruscotto/
/anagrafica/qualifiche/
/anagrafica/qualifiche/scadenzario/
/anagrafica/qualifiche/sessioni/
/anagrafica/impostazioni/
/anagrafica/impostazioni-widget/
```

---

## ✅ Topbar attuale — «Proposta A» a pilastri (implementata)

Migration `0069` (schema) + `0070` (dati). La topbar passa da ~7 dropdown affollati
a **4 pilastri**, con due meccanismi DB-driven nuovi, entrambi gestibili da
**Impostazioni → Navigazione**:

1. **Pilastro = link + sottomenu.** La categoria ha una *landing*
   (`SubnavCategoriaAnagrafica.landing_url_type` / `landing_url_value`): cliccando il
   **testo** del pilastro si va alla **dashboard del sotto-modulo**, il **caret/hover**
   apre comunque il dropdown con gli altri collegamenti. Landing vuota = categoria
   solo-dropdown (comportamento storico).
2. **Mega-menu a colonne.** Il campo `SubnavLinkAnagrafica.gruppo` crea intestazioni
   di sezione dentro il dropdown: link con lo stesso gruppo finiscono nella stessa
   colonna. Usato da **Competenze** (Formazione / Qualifiche / Trasversale).

Struttura seminata dalla `0070` (idempotente, per `url_value`; i link mancanti sono
creati **non di sistema** → liberamente riordinabili/eliminabili):

```text
▦ Dashboard │ ⏰ Scadenzario │ 👥 Persone▾ │ 🎓 Competenze▾ │ 🛡 Compliance▾ │ 🪙 Amministrazione▾ │ ⚙ Impostazioni
```

| Pilastro | Landing (clic sul testo) | Dropdown |
|---|---|---|
| **Persone** | `dipendenti_list` | Elenco · Nuovo · Ex · Organigramma · Onboarding · Documenti · Report · Reparti |
| **Competenze** | `formazione_dashboard` | *Formazione*: Dashboard·Piani·Corsi·Sessioni·Istruttori·E-learning·Corsi online·Copertura — *Qualifiche*: Cruscotto·Catalogo·Sessioni rinnovo — *Trasversale*: Matrice competenze |
| **Compliance** | `sicurezza_hub` | Hub sicurezza · Visite mediche · Conformità mansione |
| **Amministrazione** | `retribuzioni_globale` | Analisi retribuzioni · Import · Contratti · Cedolini · Ratei |

- **Scadenzario unico**: una sola voce diretta verso `anagrafica:scadenzario` (già
  unificato e filtrabile via `?tipo=qualifica|visita|formazione|contratto`).
- **Nascosti dalla topbar** (non eliminati, restano in Impostazioni): `qualifiche_scadenzario`
  (doppione → Scadenzario unico), `mansioni_list` e `onboarding_offboarding` (cataloghi/config).
- **Dashboard** resta la home del modulo; **⚙ Impostazioni** resta voce diretta.
- **Migration `0081`**: `aree_list` (`/anagrafica/aree/`, catalogo Reparti/Aree aziendali) esce
  dall'elenco "cataloghi struttura solo in Impostazioni" e diventa voce dedicata nel dropdown
  **Persone** (richiesto esplicitamente, dopo l'inversione gerarchia Reparto/Area di `0080`).
  Resta comunque gestibile anche dal tab "Reparti" del Pannello Impostazioni.

> Estendere/riordinare da Impostazioni → Navigazione: ogni categoria ha i campi
> *Landing / Tipo landing*, ogni link il campo *Gruppo*; la lista `subnav_route_choices`
> espone tutte le pagine dei pilastri come destinazioni selezionabili.

---

## Proposta riorganizzazione topnav (storica — 7 dropdown, superata dalla Proposta A)

Il topnav è DB-driven (`SubnavCategoriaAnagrafica` + `SubnavLinkAnagrafica`) ed è
modificabile dalla sezione **Impostazioni**. Le categorie diventano dropdown;
i link senza categoria restano voci dirette. La posizione di una categoria nel
menu segue il **minimo `ordine`** dei suoi link figli → usare le bande di `ordine`
sotto per ottenere l'ordine top-level desiderato.

Logica: **operatività** (Dipendenti, Formazione, Salute & Sicurezza, Qualifiche, Paghe)
separata dalla **configurazione** (Impostazioni). I cataloghi struttura (Mansioni,
Aree/Reparti, Ruoli) restano tab dentro il Pannello Impostazioni → niente voci dedicate
nel topnav. **Qualifiche** invece ha un dropdown proprio (in crescita).

### 1. Dashboard — link diretto (nessuna categoria)
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 0 | Dashboard | `index` |

### 2. Dipendenti — categoria/dropdown
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 100 | Elenco dipendenti | `dipendenti_list` |
| 110 | Nuovo dipendente | `dipendente_create` |
| 120 | Ex dipendenti | `ex_dipendenti_list` |
| 130 | Organigramma | `organigramma` |
| 140 | Onboarding | `onboarding_list` |
| 150 | Documenti | `documenti_list` |
| 160 | Report dipendenti | `dipendenti_report` |

### 3. Formazione — categoria/dropdown
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 200 | Dashboard formazione | `formazione_dashboard` |
| 210 | Piani formativi | `formazione_piani_list` |
| 220 | Corsi | `formazione_corsi_list` |
| 230 | Sessioni | `formazione_sessioni_list` |
| 240 | Istruttori | `formazione_istruttori_list` |
| 250 | E-learning | `formazione_elearning_hub` |
| 260 | Corsi online | `formazione_online_catalog` |
| 270 | Scadenzario formazione | `formazione_scadenzario` |
| 280 | Copertura / gap | `formazione_copertura` |
| 290 | Plan (calendario) | `formazione_plan` |
| 295 | Ricerca formazione | `formazione_ricerca` |

### 4. Salute & Sicurezza — categoria/dropdown
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 300 | Hub sicurezza | `sicurezza_hub` |
| 310 | Matrice competenze | `matrice_competenze` |
| 320 | Visite mediche | `visite_mediche_dashboard` |
| 330 | Conformità (idoneità) | `conformita_report` |
| 340 | Scadenzario | `scadenzario` |
| 350 | Ricerca sicurezza | `sicurezza_ricerca` |
| 360 | Guida | `sicurezza_wizard` |

### 5. Qualifiche — categoria/dropdown → mini-modulo "Qualifiche & Certificazioni"

Obiettivo: cruscotto dedicato di raccolta/gestione/controllo delle qualifiche e
certificazioni aziendali. **Non duplica i dati**: aggrega le sorgenti uniche già
esistenti (`TipoQualifica`, `DipendenteQualifica`, `QualificaSessione`), le stesse
usate da Formazione, `matrice_competenze`, `conformita_report` e dalla scheda
dipendente. Le modifiche fatte altrove si riflettono qui e viceversa.

**✅ Fase 1 (MVP) IMPLEMENTATA** — migration dati `0064_subnav_qualifiche` (crea la
categoria subnav «Qualifiche» e ci colloca i link sotto, spostando i token di
highlight via dal link «Formazione»). Dropdown seminato:

| ordine | etichetta | name (`anagrafica:`) | stato |
|---|---|---|---|
| 63 | Cruscotto | `qualifiche_dashboard` | ✅ NUOVO (`/qualifiche/cruscotto/`) |
| 64 | Catalogo qualifiche | `qualifiche_list` | esiste (spostato nel dropdown) |
| 65 | Scadenzario qualifiche | `qualifiche_scadenzario` | ✅ NUOVO (`/qualifiche/scadenzario/`) |
| 66 | Sessioni di rinnovo | `qualifica_sessioni_list` | esiste (spostato nel dropdown) |

> «Matrice qualifiche» (`matrice_competenze`) NON è duplicata nel dropdown per non
> creare doppio-highlight con Salute & Sicurezza: è raggiungibile dalla card «Aree del
> modulo» del cruscotto. Gli `ordine` 63-66 collocano il dropdown subito dopo Formazione
> (ordine reale del DB); riordinabile a piacere da Impostazioni.

Contenuto del **Cruscotto** (implementato):
- KPI semaforo: Valide / In scadenza (≤60gg) / Scadute / N° tipi → cliccabili verso lo scadenzario filtrato.
- Timeline scadenze prossimi 12 mesi.
- Distribuzione per categoria (Sicurezza / Professionale / Gestionale / Altro).
- Top 15 scadenze urgenti + prossime sessioni di rinnovo (da `QualificaSessione`).
- «Aree del modulo»: catalogo, scadenzario, matrice, sessioni, conformità (gap), config promemoria scadenze.

**Scadenzario qualifiche** (implementato): tabella `DipendenteQualifica` con stato RAG
(Scaduta/≤30/≤60/Valida/Permanente), filtri per stato/categoria/tipo/reparto ed export CSV.

**Scadenze / promemoria**: già nel modulo `automazioni` (report settimanale
`report_scadenze_settimanale` con categoria qualifiche configurabile + pacchetto
`au12_qualifica_scadenza_notifica`). Il cruscotto le mostra e linka alla config, non le ridefinisce.

> NB: Formazione e Salute & Sicurezza mantengono i loro riferimenti alle qualifiche
> (il discorso formativo resta lì); il cruscotto è una vista trasversale aggiuntiva,
> non li sostituisce.

**✅ Fase 2a IMPLEMENTATA** (migration `0065`, additiva): su `DipendenteQualifica`
campi `numero` / `livello` / `ente` + **evidenza documentale** `documento` (storage
privato fuori webroot, download protetto `dipendente_qualifica_evidenza` ACL admin/HR +
audit) + **verifica HR** `verificata`/`verificata_da`/`verificata_il` (toggle
`dipendente_qualifica_verifica`). Compilabili dal form «Aggiungi qualifica» (scheda
dipendente, multipart); cruscotto KPI «Da verificare»; scadenzario colonne Ente/Evidenza/
Verifica + CSV. I campi vivono sulla stessa `DipendenteQualifica` (single-source: visibili
anche a matrice/conformità/scheda).

**Fase 2b/c (futura)**: rinnovo guidato (da scadenza → sessione/iscrizione precompilata),
storico rinnovi esplicito (catena invece di sovrascrittura). Da valutare l'impatto sulla
convenzione attuale "una DipendenteQualifica corrente per (dipendente, tipo)".

### 6. Paghe & Contratti — categoria/dropdown
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 500 | Retribuzioni — import | `retribuzioni_import` |
| 510 | Retribuzioni — vista globale | `retribuzioni_globale` |
| 520 | Contratti | `contratti_import` |
| 530 | Cedolini | `cedolini_import` |
| 540 | Ratei ferie / ROL | `ratei_list` |

### 7. Impostazioni — categoria/dropdown
| ordine | etichetta | name (`anagrafica:`) |
|---|---|---|
| 900 | Pannello impostazioni HR | `impostazioni` |
| 910 | Permessi widget | `widget_permissions` |
| 920 | Impostazioni attestato | `attestato_impostazioni` |
| 930 | Impostazioni e-learning | `formazione_elearning_settings` |
| 940 | Rischi — Fattori | `fattori_rischio_list` |
| 950 | Rischi — Categorie corso | `categorie_corso_list` |
| 960 | Rischi — Esposizioni | `esposizioni_rischio_list` |

> Nota: dentro **Pannello impostazioni HR** restano accessibili come tab i cataloghi
> Mansioni (`mansioni_list`), Aree/Reparti (`aree_list`), Ruoli aziendali (`ruoli_aziendali_list`),
> Ruoli operativi (`ruoli_operativi_list`). Le **Qualifiche** sono uscite da qui e hanno
> un dropdown top-level dedicato (sezione 5).

