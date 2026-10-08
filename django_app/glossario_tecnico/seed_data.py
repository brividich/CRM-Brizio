"""Elenco iniziale del glossario (seed): termini in «bozza», da validare in Qualità.

Definizioni brevi scritte con parole nostre; nessun testo di norma, nessun valore
numerico di tabella. Delle norme solo il codice. Varianti: (tipo, testo, lingua).
Le sigle aziendali di cui il repository non riporta l'espansione sono descritte
per funzione, con una nota interna da confermare.
"""

DA_CONFERMARE = "Seed: espansione della sigla da confermare dalla Qualità."

T = "traduzione"
S = "sinonimo"
G = "gergo"
A = "abbreviazione"
Y = "simbolo"
E = "grafia_errata"


def _t(termine, en, categoria, definizione, *, simbolo="", esempio="", norma="", varianti=(), note=""):
    return {
        "termine": termine, "termine_en": en, "categoria": categoria, "definizione": definizione,
        "simbolo": simbolo, "esempio_disegno": esempio, "norma_rif": norma,
        "varianti": list(varianti), "note_interne": note,
    }


TERMINI = [
    # ── Lavorazioni ──────────────────────────────────────────────────────────
    _t("tornitura", "turning", "lavorazione",
       "Asportazione di truciolo in cui il pezzo ruota e l'utensile avanza: produce superfici di rotazione "
       "come cilindri, coni, spallamenti e gole.",
       varianti=[(T, "turning", "en"), (G, "tornire", "it")]),
    _t("fresatura", "milling", "lavorazione",
       "Asportazione di truciolo con un utensile multitagliente che ruota mentre il pezzo o l'utensile si "
       "spostano: piani, cave, tasche e profili.",
       varianti=[(T, "milling", "en"), (G, "fresare", "it")]),
    _t("rettifica", "grinding", "lavorazione",
       "Finitura con mola abrasiva per ottenere tolleranze strette e superfici lisce, di solito dopo la "
       "lavorazione di sgrossatura o il trattamento termico.",
       varianti=[(T, "grinding", "en"), (S, "rettificatura", "it"), (G, "rettificare", "it")]),
    _t("alesatura", "reaming", "lavorazione",
       "Finitura di un foro già esistente con alesatore o bareno, per portarlo a diametro e qualità di "
       "superficie precisi.",
       varianti=[(T, "reaming", "en"), (T, "boring", "en"), (G, "alesare", "it")]),
    _t("lamatura", "spot face", "lavorazione",
       "Spianatura cilindrica attorno all'imbocco di un foro, che crea un appoggio piano per la testa di una "
       "vite o di un dado. A disegno si indica con il simbolo di lamatura, il diametro e la profondità.",
       simbolo="⌴", esempio="⌴ ⌀12 ↧2",
       varianti=[(T, "spot face", "en"), (T, "spotface", "en"), (T, "counterbore", "en"),
                 (Y, "⌴", ""), (G, "lamare", "it")]),
    _t("svasatura", "countersink", "lavorazione",
       "Smusso conico all'imbocco di un foro che accoglie la testa svasata di una vite, a filo della "
       "superficie.",
       simbolo="⌵", esempio="⌵ ⌀10 × 90°",
       varianti=[(T, "countersink", "en"), (Y, "⌵", ""), (G, "svasare", "it")]),
    _t("maschiatura", "tapping", "lavorazione",
       "Esecuzione di una filettatura interna in un foro con un maschio, a mano o a macchina.",
       varianti=[(T, "tapping", "en"), (G, "maschiare", "it")]),
    _t("brocciatura", "broaching", "lavorazione",
       "Lavorazione con un utensile a denti progressivi (broccia) che in una sola passata ricava profili "
       "interni o esterni, come cave per linguetta o scanalati.",
       varianti=[(T, "broaching", "en"), (G, "brocciare", "it")]),
    _t("elettroerosione a filo", "wire EDM", "lavorazione",
       "Taglio di materiali conduttivi con un filo elettrodo che asporta materiale per scariche elettriche; "
       "adatta a profili complessi e materiali duri.",
       varianti=[(T, "wire EDM", "en"), (A, "WEDM", ""), (G, "erosione a filo", "it")]),
    _t("elettroerosione a tuffo", "sinker EDM", "lavorazione",
       "Asportazione per scariche elettriche con un elettrodo sagomato che penetra nel pezzo, riproducendone "
       "la forma in negativo.",
       varianti=[(T, "sinker EDM", "en"), (T, "die-sinking EDM", "en"), (G, "erosione a tuffo", "it")]),
    _t("sbavatura", "deburring", "lavorazione",
       "Rimozione delle bave lasciate dalle lavorazioni sugli spigoli, per sicurezza, montaggio e aspetto.",
       varianti=[(T, "deburring", "en"), (G, "sbavare", "it")]),
    _t("smussatura", "chamfering", "lavorazione",
       "Esecuzione di uno smusso, cioè di un piccolo piano inclinato che sostituisce uno spigolo vivo.",
       varianti=[(T, "chamfering", "en"), (T, "chamfer", "en"), (S, "smusso", "it")]),
    _t("raggiatura", "filleting", "lavorazione",
       "Arrotondamento di uno spigolo con un raggio, per ridurre concentrazioni di tensione o spigoli taglienti.",
       varianti=[(T, "fillet", "en"), (T, "edge rounding", "en"), (S, "raccordo", "it")]),
    _t("foratura", "drilling", "lavorazione",
       "Esecuzione di un foro con punta elicoidale o utensile equivalente.",
       varianti=[(T, "drilling", "en"), (G, "forare", "it")]),

    # ── Quotatura ────────────────────────────────────────────────────────────
    _t("quota nominale", "nominal dimension", "quotatura",
       "Valore teorico di una dimensione indicato a disegno, al quale si riferiscono gli scostamenti e la "
       "tolleranza.",
       varianti=[(T, "nominal dimension", "en"), (T, "nominal size", "en"), (S, "dimensione nominale", "it")]),
    _t("diametro", "diameter", "quotatura",
       "Dimensione di un elemento circolare misurata passando per il centro; a disegno è preceduta dal "
       "simbolo di diametro.",
       simbolo="⌀", esempio="⌀20",
       varianti=[(T, "diameter", "en"), (Y, "⌀", ""), (Y, "Ø", "")]),
    _t("profondità", "depth", "quotatura",
       "Estensione di un foro, di una lamatura o di una cava misurata dalla superficie di imbocco; a disegno "
       "può essere indicata con il simbolo di profondità.",
       simbolo="↧", esempio="↧8",
       varianti=[(T, "depth", "en"), (Y, "↧", "")]),
    _t("quota di riferimento", "reference dimension", "quotatura",
       "Quota riportata solo per informazione, senza tolleranza e senza obbligo di controllo; di solito "
       "indicata tra parentesi.",
       varianti=[(T, "reference dimension", "en"), (S, "quota ausiliaria", "it")]),
    _t("quota teoricamente esatta", "theoretically exact dimension", "quotatura",
       "Quota senza tolleranza propria, racchiusa in un riquadro, che posiziona o orienta una zona di "
       "tolleranza geometrica.",
       varianti=[(T, "basic dimension", "en"), (T, "TED", "en"), (S, "quota esatta", "it")]),

    # ── Tolleranze dimensionali ──────────────────────────────────────────────
    _t("scostamento", "deviation", "tolleranza_dimensionale",
       "Differenza tra una dimensione limite (massima o minima) e la quota nominale; può essere superiore o "
       "inferiore.",
       norma="ISO 286-1",
       varianti=[(T, "deviation", "en"), (S, "scostamento limite", "it")]),
    _t("campo di tolleranza", "tolerance interval", "tolleranza_dimensionale",
       "Intervallo tra dimensione massima e minima ammesse; nel sistema ISO è indicato da una lettera "
       "(posizione) e da un numero (grado), per esempio H7 o g6.",
       norma="ISO 286-1", esempio="⌀20 H7",
       varianti=[(T, "tolerance interval", "en"), (T, "tolerance zone", "en"), (S, "tolleranza", "it")]),
    _t("grado di tolleranza", "tolerance grade", "tolleranza_dimensionale",
       "Numero che esprime l'ampiezza della tolleranza nel sistema ISO: più è basso, più la tolleranza è "
       "stretta.",
       norma="ISO 286-1",
       varianti=[(T, "tolerance grade", "en"), (A, "IT", "")]),
    _t("sistema foro base", "hole-basis system", "tolleranza_dimensionale",
       "Sistema di accoppiamento in cui il foro ha sempre la posizione H e il tipo di accoppiamento si "
       "ottiene variando la tolleranza dell'albero.",
       norma="ISO 286-1",
       varianti=[(T, "hole-basis system", "en"), (G, "foro base", "it")]),
    _t("sistema albero base", "shaft-basis system", "tolleranza_dimensionale",
       "Sistema di accoppiamento in cui l'albero ha sempre la posizione h e il tipo di accoppiamento si "
       "ottiene variando la tolleranza del foro.",
       norma="ISO 286-1",
       varianti=[(T, "shaft-basis system", "en"), (G, "albero base", "it")]),
    _t("accoppiamento", "fit", "tolleranza_dimensionale",
       "Relazione tra un foro e un albero della stessa quota nominale: con gioco, incerto o con interferenza "
       "(forzato), secondo le rispettive tolleranze.",
       norma="ISO 286-1", esempio="⌀20 H7/g6",
       varianti=[(T, "fit", "en"), (S, "accoppiamento con gioco", "it"), (S, "accoppiamento forzato", "it"),
                 (S, "accoppiamento incerto", "it"), (T, "interference fit", "en"), (T, "clearance fit", "en")]),
    _t("tolleranze generali", "general tolerances", "tolleranza_dimensionale",
       "Tolleranze applicate a tutte le quote senza tolleranza esplicita, richiamate nel cartiglio con la "
       "norma e la classe scelta.",
       norma="ISO 2768-1",
       varianti=[(T, "general tolerances", "en"), (S, "tolleranze non indicate", "it")]),

    # ── GD&T (ISO 1101) ──────────────────────────────────────────────────────
    _t("rettilineità", "straightness", "gdt",
       "Tolleranza di forma: la linea controllata deve stare tra due rette parallele (o in un cilindro) "
       "distanti quanto la tolleranza.",
       simbolo="⏤", norma="ISO 1101", varianti=[(T, "straightness", "en"), (Y, "⏤", "")]),
    _t("planarità", "flatness", "gdt",
       "Tolleranza di forma: la superficie deve stare tra due piani paralleli distanti quanto la tolleranza.",
       simbolo="⏥", norma="ISO 1101", varianti=[(T, "flatness", "en"), (Y, "⏥", ""), (E, "planarieta", "it")]),
    _t("circolarità", "roundness", "gdt",
       "Tolleranza di forma: ogni sezione circolare deve stare tra due cerchi concentrici distanti quanto la "
       "tolleranza.",
       simbolo="○", norma="ISO 1101",
       varianti=[(T, "roundness", "en"), (T, "circularity", "en"), (S, "rotondità", "it"), (Y, "○", "")]),
    _t("cilindricità", "cylindricity", "gdt",
       "Tolleranza di forma: la superficie cilindrica deve stare tra due cilindri coassiali distanti quanto "
       "la tolleranza.",
       simbolo="⌭", norma="ISO 1101", varianti=[(T, "cylindricity", "en"), (Y, "⌭", "")]),
    _t("profilo di una linea", "line profile", "gdt",
       "Tolleranza di forma o posizione di una linea qualsiasi rispetto al profilo teorico, entro una fascia "
       "di ampiezza pari alla tolleranza.",
       simbolo="⌒", norma="ISO 1101",
       varianti=[(T, "profile of a line", "en"), (T, "line profile", "en"), (Y, "⌒", "")]),
    _t("profilo di una superficie", "surface profile", "gdt",
       "Tolleranza della superficie reale rispetto alla superficie teorica, entro uno spessore pari alla "
       "tolleranza.",
       simbolo="⌓", norma="ISO 1101",
       varianti=[(T, "profile of a surface", "en"), (T, "surface profile", "en"), (Y, "⌓", "")]),
    _t("parallelismo", "parallelism", "gdt",
       "Tolleranza di orientamento: l'elemento deve stare tra due piani o rette paralleli al riferimento.",
       simbolo="∥", norma="ISO 1101", varianti=[(T, "parallelism", "en"), (Y, "∥", ""), (Y, "⫽", "")]),
    _t("perpendicolarità", "perpendicularity", "gdt",
       "Tolleranza di orientamento: l'elemento deve stare entro una zona perpendicolare al riferimento.",
       simbolo="⊥", norma="ISO 1101",
       varianti=[(T, "perpendicularity", "en"), (T, "squareness", "en"), (S, "ortogonalità", "it"), (Y, "⊥", "")]),
    _t("inclinazione", "angularity", "gdt",
       "Tolleranza di orientamento: l'elemento deve stare entro una zona inclinata dell'angolo teorico "
       "rispetto al riferimento.",
       simbolo="∠", norma="ISO 1101", varianti=[(T, "angularity", "en"), (S, "angolarità", "it"), (Y, "∠", "")]),
    _t("localizzazione", "position", "gdt",
       "Tolleranza di posizione: l'asse o il piano dell'elemento deve stare in una zona centrata sulla "
       "posizione teoricamente esatta.",
       simbolo="⌖", norma="ISO 1101",
       varianti=[(T, "position", "en"), (T, "true position", "en"), (S, "posizione", "it"), (Y, "⌖", "")]),
    _t("coassialità", "coaxiality", "gdt",
       "Tolleranza di posizione: l'asse dell'elemento deve stare in un cilindro coassiale all'asse di "
       "riferimento (per un punto si parla di concentricità).",
       simbolo="◎", norma="ISO 1101",
       varianti=[(T, "coaxiality", "en"), (T, "concentricity", "en"), (S, "concentricità", "it"), (Y, "◎", "")]),
    _t("simmetria", "symmetry", "gdt",
       "Tolleranza di posizione: il piano mediano dell'elemento deve stare tra due piani simmetrici rispetto "
       "al riferimento.",
       simbolo="⌯", norma="ISO 1101", varianti=[(T, "symmetry", "en"), (Y, "⌯", "")]),
    _t("oscillazione circolare", "circular run-out", "gdt",
       "Tolleranza di oscillazione: in ogni sezione, ruotando il pezzo attorno all'asse di riferimento, la "
       "lettura dello strumento non deve variare più della tolleranza.",
       simbolo="↗", norma="ISO 1101",
       varianti=[(T, "circular run-out", "en"), (T, "runout", "en"), (S, "eccentricità", "it"), (Y, "↗", "")]),
    _t("oscillazione totale", "total run-out", "gdt",
       "Tolleranza di oscillazione sull'intera superficie: ruotando il pezzo e spostando lo strumento lungo "
       "l'elemento, la lettura non deve variare più della tolleranza.",
       simbolo="⌰", norma="ISO 1101", varianti=[(T, "total run-out", "en"), (Y, "⌰", "")]),
    _t("riferimento", "datum", "gdt",
       "Elemento teorico (piano, asse, punto) ricavato da un elemento reale del pezzo e indicato con una "
       "lettera, rispetto al quale si valutano orientamento, posizione e oscillazione.",
       norma="ISO 5459",
       varianti=[(T, "datum", "en"), (S, "elemento di riferimento", "it"), (S, "datum di riferimento", "it")]),
    _t("condizione di massimo materiale", "maximum material condition", "gdt",
       "Stato dell'elemento con la massima quantità di materiale (foro al minimo, albero al massimo); "
       "applicata a una tolleranza geometrica consente un bonus quando l'elemento se ne allontana.",
       simbolo="Ⓜ", norma="ISO 2692",
       varianti=[(A, "MMC", ""), (A, "MMR", ""), (T, "maximum material condition", "en"), (Y, "Ⓜ", "")]),
    _t("condizione di minimo materiale", "least material condition", "gdt",
       "Stato dell'elemento con la minima quantità di materiale (foro al massimo, albero al minimo); usata "
       "per garantire spessori minimi di parete.",
       simbolo="Ⓛ", norma="ISO 2692",
       varianti=[(A, "LMC", ""), (A, "LMR", ""), (T, "least material condition", "en"), (Y, "Ⓛ", "")]),
    _t("zona di tolleranza proiettata", "projected tolerance zone", "gdt",
       "Zona di tolleranza spostata fuori dal pezzo, sulla lunghezza dell'elemento che vi verrà montato "
       "(per esempio una vite prigioniera).",
       simbolo="Ⓟ", norma="ISO 1101",
       varianti=[(T, "projected tolerance zone", "en"), (S, "zona proiettata", "it"), (Y, "Ⓟ", "")]),
    _t("riquadro di tolleranza", "tolerance frame", "gdt",
       "Rettangolo diviso in caselle che riporta simbolo della caratteristica, valore della tolleranza ed "
       "eventuali riferimenti.",
       varianti=[(T, "feature control frame", "en"), (T, "tolerance frame", "en"), (S, "casella di tolleranza", "it")]),

    # ── Rugosità ─────────────────────────────────────────────────────────────
    _t("rugosità", "surface roughness", "rugosita",
       "Insieme delle piccole irregolarità di una superficie lasciate dalla lavorazione; a disegno si "
       "indica con il simbolo di finitura e un parametro come Ra o Rz.",
       norma="ISO 21920-1",
       varianti=[(T, "surface roughness", "en"), (T, "roughness", "en"), (S, "finitura superficiale", "it")]),
    _t("rugosità media aritmetica", "arithmetic mean roughness", "rugosita",
       "Parametro Ra: media dei valori assoluti delle irregolarità del profilo rispetto alla linea media. È "
       "il parametro di rugosità più usato a disegno.",
       esempio="Ra 0,8", norma="ISO 21920-2",
       varianti=[(A, "Ra", ""), (T, "arithmetic mean roughness", "en")]),
    _t("altezza massima del profilo", "maximum height of profile", "rugosita",
       "Parametro Rz: distanza tra il picco più alto e la valle più profonda nella lunghezza di valutazione; "
       "più sensibile di Ra a graffi e picchi isolati.",
       norma="ISO 21920-2",
       varianti=[(A, "Rz", ""), (T, "maximum height of profile", "en")]),
    _t("simbolo di finitura con asportazione", "material removal required", "rugosita",
       "Simbolo grafico di finitura con il trattino orizzontale: la superficie deve essere ottenuta "
       "asportando materiale.",
       norma="ISO 1302",
       varianti=[(T, "machining required", "en"), (S, "asportazione obbligatoria", "it")]),
    _t("simbolo di finitura senza asportazione", "material removal prohibited", "rugosita",
       "Simbolo grafico di finitura con il cerchio: la superficie deve restare come ottenuta dal processo "
       "precedente, senza asportare materiale.",
       norma="ISO 1302",
       varianti=[(T, "material removal prohibited", "en"), (S, "asportazione vietata", "it")]),

    # ── Filettature ──────────────────────────────────────────────────────────
    _t("filettatura metrica", "metric thread", "filettatura",
       "Filettatura ISO a profilo triangolare indicata con M seguita dal diametro nominale; se il passo non "
       "è indicato è quello grosso.",
       norma="ISO 261", esempio="M8",
       varianti=[(T, "metric thread", "en"), (S, "filetto metrico", "it"), (S, "passo grosso", "it")]),
    _t("filettatura metrica a passo fine", "metric fine thread", "filettatura",
       "Filettatura metrica con passo minore di quello grosso, indicata con M, diametro e passo (per esempio "
       "M8x1); più resistente all'allentamento.",
       norma="ISO 261", esempio="M8x1",
       varianti=[(A, "MF", ""), (T, "metric fine thread", "en"), (S, "passo fine", "it")]),
    _t("passo", "pitch", "filettatura",
       "Distanza tra due creste consecutive di una filettatura, misurata parallelamente all'asse.",
       varianti=[(T, "pitch", "en"), (T, "thread pitch", "en"), (S, "passo del filetto", "it")]),
    _t("classe di tolleranza della filettatura", "thread tolerance class", "filettatura",
       "Indicazione di posizione e grado di tolleranza di una filettatura: lettera maiuscola per la "
       "madrevite (es. 6H), minuscola per la vite (es. 6g).",
       norma="ISO 965-1", esempio="M8-6H",
       varianti=[(T, "thread tolerance class", "en"), (S, "classe del filetto", "it")]),
    _t("filettatura UNC", "Unified National Coarse", "filettatura",
       "Filettatura unificata in pollici a passo grosso, indicata con diametro e numero di filetti per "
       "pollice.",
       varianti=[(A, "UNC", ""), (T, "unified coarse thread", "en")]),
    _t("filettatura UNF", "Unified National Fine", "filettatura",
       "Filettatura unificata in pollici a passo fine, indicata con diametro e numero di filetti per pollice.",
       varianti=[(A, "UNF", ""), (T, "unified fine thread", "en")]),
    _t("madrevite", "internal thread", "filettatura",
       "Filettatura interna, ricavata in un foro, in cui si avvita la vite.",
       varianti=[(T, "internal thread", "en"), (S, "filetto femmina", "it"), (G, "filettatura interna", "it")]),

    # ── Trattamenti termici ──────────────────────────────────────────────────
    _t("tempra", "hardening", "trattamento_termico",
       "Riscaldamento dell'acciaio e raffreddamento rapido per aumentarne la durezza; di solito seguita dal "
       "rinvenimento.",
       varianti=[(T, "hardening", "en"), (T, "quenching", "en"), (G, "temprare", "it")]),
    _t("rinvenimento", "tempering", "trattamento_termico",
       "Riscaldamento successivo alla tempra, a temperatura più bassa, per ridurre la fragilità e le "
       "tensioni mantenendo buona parte della durezza.",
       varianti=[(T, "tempering", "en")]),
    _t("bonifica", "quenching and tempering", "trattamento_termico",
       "Ciclo di tempra seguita da rinvenimento ad alta temperatura, per ottenere un buon compromesso tra "
       "resistenza e tenacità.",
       varianti=[(T, "quench and temper", "en"), (A, "Q&T", "")]),
    _t("cementazione", "case hardening", "trattamento_termico",
       "Arricchimento di carbonio dello strato superficiale seguito da tempra: superficie dura e resistente "
       "all'usura, cuore tenace.",
       varianti=[(T, "carburizing", "en"), (T, "case hardening", "en")]),
    _t("nitrurazione", "nitriding", "trattamento_termico",
       "Diffusione di azoto nello strato superficiale a temperatura relativamente bassa: alta durezza "
       "superficiale con deformazioni ridotte.",
       varianti=[(T, "nitriding", "en")]),
    _t("distensione", "stress relieving", "trattamento_termico",
       "Riscaldamento a temperatura moderata e raffreddamento lento per ridurre le tensioni residue dovute a "
       "saldature o lavorazioni.",
       varianti=[(T, "stress relieving", "en"), (S, "ricottura di distensione", "it"), (S, "stabilizzazione", "it")]),
    _t("ricottura", "annealing", "trattamento_termico",
       "Riscaldamento e raffreddamento lento per addolcire il materiale e renderlo più lavorabile.",
       varianti=[(T, "annealing", "en")]),

    # ── Trattamenti superficiali ─────────────────────────────────────────────
    _t("anodizzazione", "anodizing", "trattamento_superficiale",
       "Ossidazione elettrochimica controllata dell'alluminio che crea uno strato protettivo di ossido, "
       "anche colorabile.",
       varianti=[(T, "anodizing", "en"), (T, "anodising", "en"), (S, "ossidazione anodica", "it")]),
    _t("ossidazione anodica dura", "hard anodizing", "trattamento_superficiale",
       "Anodizzazione a strato spesso e molto duro, per resistenza all'usura dell'alluminio.",
       varianti=[(T, "hard anodizing", "en"), (G, "anodizzazione dura", "it")]),
    _t("passivazione", "passivation", "trattamento_superficiale",
       "Trattamento chimico dell'acciaio inossidabile che rimuove contaminazioni e favorisce lo strato "
       "passivo che lo protegge dalla corrosione.",
       varianti=[(T, "passivation", "en")]),
    _t("pallinatura", "shot peening", "trattamento_superficiale",
       "Bombardamento controllato della superficie con pallini che crea tensioni di compressione e migliora "
       "la resistenza a fatica.",
       varianti=[(T, "shot peening", "en"), (G, "granigliatura controllata", "it")]),
    _t("sabbiatura", "sandblasting", "trattamento_superficiale",
       "Pulizia o preparazione della superficie con getto di materiale abrasivo, per esempio prima della "
       "verniciatura.",
       varianti=[(T, "sandblasting", "en"), (T, "abrasive blasting", "en")]),
    _t("zincatura", "zinc plating", "trattamento_superficiale",
       "Rivestimento di zinco sull'acciaio per proteggerlo dalla corrosione, a caldo o elettrolitico.",
       varianti=[(T, "zinc plating", "en"), (T, "galvanizing", "en")]),

    # ── Controllo qualità ────────────────────────────────────────────────────
    _t("ispezione del primo articolo", "First Article Inspection", "controllo_qualita",
       "Verifica documentata e completa di un primo pezzo prodotto con il processo definitivo, per "
       "dimostrare che tutte le caratteristiche a disegno sono rispettate.",
       norma="AS9102",
       varianti=[(A, "FAI", ""), (T, "first article inspection", "en"), (G, "primo articolo", "it"),
                 (S, "rapporto FAI", "it")]),
    _t("ballonatura", "ballooning", "controllo_qualita",
       "Numerazione progressiva di ogni caratteristica del disegno con un «palloncino», così che ogni "
       "misura del rapporto di controllo sia riconducibile al disegno.",
       varianti=[(T, "ballooning", "en"), (S, "disegno ballonato", "it"), (G, "palloncini", "it")]),
    _t("macchina di misura a coordinate", "coordinate measuring machine", "controllo_qualita",
       "Strumento che rileva la posizione di punti sulla superficie del pezzo con un tastatore e ne ricava "
       "dimensioni e tolleranze geometriche.",
       varianti=[(A, "CMM", ""), (T, "coordinate measuring machine", "en"), (G, "tridimensionale", "it"),
                 (G, "macchina di misura", "it")]),
    _t("calibro passa-non passa", "go/no-go gauge", "controllo_qualita",
       "Calibro fisso con un lato che deve entrare (passa) e uno che non deve entrare (non passa): verifica "
       "rapidamente se una quota è in tolleranza.",
       varianti=[(T, "go/no-go gauge", "en"), (S, "calibro differenziale", "it"), (S, "tampone passa non passa", "it")]),
    _t("caratteristica chiave", "key characteristic", "controllo_qualita",
       "Caratteristica la cui variazione influisce in modo significativo su funzione, sicurezza o montaggio "
       "del prodotto, e che richiede quindi un controllo dedicato.",
       norma="AS9103",
       varianti=[(A, "KC", ""), (T, "key characteristic", "en"), (S, "caratteristica critica", "it")]),
    _t("piano di controllo", "control plan", "controllo_qualita",
       "Documento che elenca, per ogni fase, le caratteristiche da controllare, il metodo, la frequenza e "
       "le reazioni in caso di scostamento.",
       varianti=[(T, "control plan", "en"), (S, "piano dei controlli", "it")]),
    _t("rapporto di collaudo", "inspection report", "controllo_qualita",
       "Registrazione dei risultati delle misure su un pezzo o un lotto, confrontati con i requisiti.",
       varianti=[(T, "inspection report", "en"), (S, "rapporto di controllo", "it"), (G, "verbale di collaudo", "it")]),

    # ── SGI documentale ──────────────────────────────────────────────────────
    _t("non conformità", "nonconformity", "sgi_documentale",
       "Mancato soddisfacimento di un requisito (di prodotto, di processo o del sistema di gestione), da "
       "registrare, trattare e analizzare.",
       norma="ISO 9001",
       varianti=[(A, "NC", ""), (T, "nonconformity", "en"), (T, "non-conformance", "en"), (E, "non conformita", "it")]),
    _t("azione correttiva", "corrective action", "sgi_documentale",
       "Azione che elimina la causa di una non conformità per evitare che si ripeta.",
       norma="ISO 9001",
       varianti=[(A, "AC", ""), (T, "corrective action", "en"), (A, "CA", "")]),
    _t("opportunità di miglioramento", "opportunity for improvement", "sgi_documentale",
       "Spunto emerso da audit, segnalazioni o analisi che non è una non conformità ma può migliorare "
       "processi o prodotti; registrata nel registro OFI.",
       varianti=[(A, "OFI", ""), (T, "opportunity for improvement", "en")]),
    _t("modulo di registrazione", "form", "sgi_documentale",
       "Modulo del sistema di gestione, identificato da un codice MOD, che si compila per registrare "
       "un'attività o un controllo.",
       varianti=[(A, "MOD", ""), (S, "modulistica", "it"), (T, "form", "en")]),
    _t("MT", "", "sgi_documentale",
       "Prefisso dei codici dei documenti procedurali del sistema di gestione (per esempio MT CN 06).",
       varianti=[(A, "MT", "")], note=DA_CONFERMARE),
    _t("MTSI", "", "sgi_documentale",
       "Prefisso di una famiglia di documenti procedurali del sistema di gestione distinta dagli MT.",
       varianti=[(A, "MTSI", "")], note=DA_CONFERMARE),
    _t("IDOR", "", "sgi_documentale",
       "Prefisso dei codici di documenti del sistema di gestione (per esempio IDOR CN 01, che comprende il "
       "manuale del sistema integrato).",
       varianti=[(A, "IDOR", "")], note=DA_CONFERMARE),
    _t("IDPR", "", "sgi_documentale",
       "Prefisso dei codici di una famiglia di documenti del sistema di gestione.",
       varianti=[(A, "IDPR", "")], note=DA_CONFERMARE),
    _t("CN", "", "sgi_documentale",
       "Sigla presente nei codici dei documenti del sistema di gestione (per esempio MT CN 06, IDOR CN 01).",
       varianti=[(A, "CN", "")], note=DA_CONFERMARE),
    _t("revisione del documento", "document revision", "sgi_documentale",
       "Edizione di un documento controllato; solo la revisione in vigore va usata, le precedenti finiscono "
       "tra i documenti superati.",
       varianti=[(A, "Rev.", ""), (T, "revision", "en"), (S, "revisione", "it")]),
]
