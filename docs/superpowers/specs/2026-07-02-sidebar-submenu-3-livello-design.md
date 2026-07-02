# Design — Sottomenu (3° livello) nella sidebar principale

- **Data**: 2026-07-02
- **Stato**: BOZZA — in attesa di approvazione utente
- **Autore**: sessione AI (brainstorming)
- **Branch**: `feature/skill-matrix-mod187`

## Problema

La sidebar principale ha oggi **2 livelli**: *Categoria* (accordion) → *Modulo* (link singolo).
Alcuni moduli — in primis **Anagrafica** — hanno molti sotto-moduli/sotto-pagine, oggi
raggiungibili solo entrando nel modulo (subnav in-pagina). Si vuole un **3° livello** nella
sidebar: un modulo può espandersi in accordion mostrando i propri sotto-moduli rientrati.

## Decisioni prese (con l'utente)

1. **Comportamento**: accordion a 3° livello (il modulo si espande in giù, sotto-voci rientrate
   nella stessa colonna). *Non* flyout, *non* solo-modulo-attivo.
2. **Ambito & gestione**: capacità **generale**, gestibile dal **NavBuilder**, riusando il campo
   `parent_code` già esistente su `NavigationItem`.
3. **Seed Anagrafica** *(CONFERMATO)*: seed iniziale via migration di alcune sotto-voci chiave, così
   il terzo livello è visibile e funzionante da subito, senza configurazione manuale dell'utente.
4. **Ambito UI** *(CONFERMATO)*: **solo sidebar** (il `topnav`/dropdown resta a 2 livelli per ora).
5. **Chi imposta cosa** *(CONFERMATO — feedback utente: "tu imposta il layout e la possibilità di
   avere un terzo livello")*: lo sviluppatore imposta **layout + capacità del terzo livello** (è la
   parte di lavoro). L'utente **non** deve configurare nulla di tecnico. Il NavBuilder col menù a
   tendina "Modulo padre" resta disponibile come gestione **opzionale** futura, non è un prerequisito
   per l'utente. La gestione via `parent_code` grezzo non viene mai esposta all'utente.

## Approccio

Riusare `core.NavigationItem` con `section='subnav'` + `parent_code`, **agganciando** ogni voce
subnav al modulo topbar il cui `code` coincide con il suo `parent_code`. Nella sidebar quel modulo
diventa un accordion di 3° livello che elenca le sue voci figlie.

### Perché questo approccio

- **Nessuna migration di schema**: `parent_code` esiste già (`core/models.py:262`); l'ACL sulle
  sotto-voci (`required_permission_code` + `NavigationRoleAccess` + `UserNavigationOverride`) è
  già applicata da `_compiled_items_for_role(section="subnav")` in `core/navigation_registry.py`.
  Le sotto-voci ereditano il filtro permessi → **nessun rischio di leak di visibilità**.
- **DRY**: le stesse voci possono alimentare sia il 3° livello in sidebar sia (dove già usata) la
  subnav in-pagina.
- **NavBuilder già pronto**: `parent_code` è già editabile (form di creazione
  `navigation_builder.html:538`, tabella `:804`, payload `views.py:7643`, save `:7861-7939`).
- Coerente con la Prime Directive (conservativo, riusa i pattern SSR/HTMX esistenti).

### Alternative scartate

- **Self-FK `parent` sul topbar** (gerarchia moduli pulita): richiede migration di schema +
  riscrittura NavBuilder. Più pulito in teoria, ma sproporzionato e contro la Prime Directive.
- **Mirror automatico dal modello Anagrafica** (`SubNavLinkAnagrafica`): accoppia due sistemi di
  navigazione, complica ACL/cache. Scartato.

## Regola di aggancio (linkage)

Una voce `subnav` è figlia di 3° livello del modulo topbar **X** se e solo se
`subnav.parent_code == X.code`.

- I `parent_code` odierni sono già chiavi-modulo (`assenze`, `anagrafica`, `dashboard`, ...),
  quindi la convenzione esiste; qui la si rende *visibile* nella sidebar.
- **Task di implementazione**: verificare che i `code` dei `NavigationItem` topbar dei moduli
  interessati coincidano con i `parent_code` usati (allineare dove necessario, senza rompere le
  subnav in-pagina esistenti).

## Componenti da costruire

### 1. Backend — annidamento (`core/context_processors.py`, eventuale helper in `navigation_registry.py`)
- Dopo aver compilato i nodi topbar (`get_topbar_nodes`) e raggruppato per categoria
  (`_group_nav_items`), per ogni modulo raccogliere le voci `subnav` con
  `parent_code == modulo.code` e attaccarle come `node.children` (lista di `NavigationNode`).
- Riusare la compilazione ACL-aware già esistente per la sezione `subnav` (stessa cache versioned).
- **Stato attivo**: se un figlio è attivo (match URL/`active_patterns`), il modulo padre risulta
  `active` e `open`; la categoria contenitrice resta `open` come già oggi.

### 2. Template (`core/templates/core/components/sidebar.html`)
- Dentro il ciclo `grp.items` (righe ~51-57): se `item.children` è non vuoto, rendere il modulo
  come pulsante espandibile (pattern gemello di `.sb-category` → `.sb-cat-btn` + blocco figli
  `.sb-subitems`); altrimenti mantenere il link semplice odierno.
- Le voci figlie riusano `.sb-item .sb-sub-item` con un rientro aggiuntivo (nuova classe, es.
  `.sb-sub-item--l3`).

### 3. JS (blocco in coda a `sidebar.html`)
- Nuovo handler toggle per l'accordion di *modulo*, indipendente da quello di *categoria*
  (l'attuale gestisce solo `.sb-category`).
- Auto-apertura del modulo che contiene la voce attiva.
- In sidebar collassata: espandere come già fa il click su categoria.

### 4. CSS (`core/static/core/css/theme.css`)
- Rientro/tipografia per il 3° livello (`.sb-subitems`, `.sb-sub-item--l3`), coerente con la
  palette HUB. Nessun nuovo colore inventato.

### 5. NavBuilder — gestione facile (`admin_portale/.../navigation_builder.html` + `views.py`)
- Nessuna modifica di schema (`parent_code` resta il campo sottostante).
- **Sostituire il campo testo `parent_code`** (form di creazione `:538`, tabella `:804`) con un
  **`<select>` "Modulo padre"** popolato dai moduli topbar disponibili: `option` con label =
  `NavigationItem.label`, value = `NavigationItem.code`. Così l'admin sceglie da un elenco leggibile
  e non può sbagliare/disallineare il codice.
- La view `navigation_builder` passa al template la lista `topbar_modules = [{code, label}, ...]`
  (i `NavigationItem section='topbar'`); i save handler (`views.py:7861`, `:7929`) continuano a
  leggere `parent_code` dal payload — invariati.
- Questo risponde direttamente al feedback "non posso gestirlo": creare una sotto-voce diventa
  «scegli il modulo padre → nome → link».

### 6. Seed Anagrafica (migration `anagrafica` o `core`) — se confermato
- `get_or_create(code=..., defaults={...})` (MAI `update_or_create`, per non sovrascrivere le
  personalizzazioni NavBuilder — cfr. nota in `NavigationItem`).
- Sotto-voci iniziali: solo label + route/url pubbliche (nessun dato sensibile).

## ACL / sicurezza

- Le sotto-voci passano dallo stesso filtro permessi delle altre voci subnav
  (`required_permission_code` risolto da binding canonico, con fallback legacy). Nessun bypass.
- **La visibilità del menu non è un confine di sicurezza**: le view di destinazione restano gated
  server-side. Il 3° livello non introduce nuove route → nessuna modifica a
  `core/middleware.py` `API_ACL_GATE_PATHS`.

## Impatti / rischi

- **Doppia comparsa**: per i moduli che già usano la subnav generica in-pagina, le stesse voci
  comparirebbero anche nella sidebar. Default: **tenerle entrambe** (non-breaking); eventuale
  nascondimento dell'in-pagina in un secondo momento.
- **Cache**: il 3° livello usa la stessa `nav_registry` versioned cache; invalidata da
  `bump_navigation_registry_version()` alla pubblicazione snapshot. Nessuna cache nuova.
- **Altezza sidebar**: con molti moduli espandibili la colonna può diventare alta; mitigato
  dall'accordion (un modulo aperto per volta, come le categorie).

## Testing

- `core` context processor: un modulo con figli subnav espone `children`; ACL nasconde i figli
  non permessi; stato attivo propagato al padre.
- `admin_portale`: NavBuilder salva/legge `parent_code` (già coperto in parte da `tests.py:2542`).
- Rendering sidebar: modulo con figli → accordion; modulo senza figli → link semplice (regressione).
- Comando: `python django_app\manage.py test django_app.core django_app.admin_portale --settings=config.settings.test --keepdb`

## Fuori scope (YAGNI)

- 3° livello nel `topnav`/dropdown (solo sidebar per ora).
- Livelli oltre il 3° (nessun 4° livello).
- Mirror dal modello `SubNavLinkAnagrafica`.
- Nascondere la subnav in-pagina.

## Checklist post-modifica (da CLAUDE.md)

- Aggiornare `CHANGELOG.md` (file modificati + descrizione sotto `[Unreleased]`).
- Aggiornare `README.md` se cambia funzionalità visibile/URL/setup.
- Valutare version-bump (comportamento utente-visibile cambia).
