/* NOVICROM HUB — da assets/pages/asset_detail.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
(() => {
  // Riquadri richiudibili (details[data-af-acc]): ricorda aperto/chiuso per
  // utente. Lo storage puo' mancare (navigazione privata): allora valgono i default.
  const prefix = 'af-acc:';
  const read = (key) => { try { return window.localStorage.getItem(prefix + key); } catch (e) { return null; } };
  const write = (key, value) => { try { window.localStorage.setItem(prefix + key, value); } catch (e) { /* storage non disponibile */ } };
  document.querySelectorAll('details[data-af-acc]').forEach((box) => {
    const key = box.dataset.afAcc;
    const saved = read(key);
    if (saved === '1') box.open = true;
    else if (saved === '0') box.open = false;
    box.addEventListener('toggle', () => write(key, box.open ? '1' : '0'));
  });
})();
(() => {
  // Schede della pagina asset: raggruppa le sezioni marcate data-af-tab.
  // Senza JS tutto resta visibile in colonna, come prima.
  const page = document.querySelector('.af-page');
  const nav = page && page.querySelector('[data-af-tabs]');
  if (!page || !nav) return;
  // Blocchi che meritano una scheda propria (es. la timeline dentro "Anagrafica").
  page.querySelectorAll('[data-af-move-tab]').forEach((block) => {
    const card = document.createElement('section');
    card.className = 'af-card af-span-full';
    card.dataset.afTab = block.dataset.afMoveTab;
    const body = document.createElement('div');
    body.className = 'af-card-body';
    card.appendChild(body);
    const anchor = page.querySelector('#asset-storico-section') || page.lastElementChild;
    anchor.parentNode.insertBefore(card, anchor);
    body.appendChild(block);
  });
  const panels = Array.from(page.querySelectorAll('[data-af-tab]')).filter((el) => el.textContent.trim() !== '');
  const order = [];
  panels.forEach((el) => { const name = el.dataset.afTab; if (!order.includes(name)) order.push(name); });
  if (order.length < 2) return;
  const slug = (name) => 'tab-' + name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const storeKey = 'af-asset-tab';
  const buttons = {};
  order.forEach((name) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'af-tab';
    btn.setAttribute('role', 'tab');
    btn.textContent = name;
    btn.addEventListener('click', () => select(name, true));
    nav.appendChild(btn);
    buttons[name] = btn;
  });
  nav.setAttribute('role', 'tablist');
  function select(name, remember) {
    if (!buttons[name]) name = order[0];
    order.forEach((n) => buttons[n].setAttribute('aria-selected', n === name ? 'true' : 'false'));
    panels.forEach((el) => {
      if (el.dataset.afTab === name) {
        el.removeAttribute('data-af-hidden');
        if (el.tagName === 'DETAILS') el.open = true;
      } else {
        el.setAttribute('data-af-hidden', '');
      }
    });
    // Contenitori di sezioni senza card visibili: niente spazio vuoto sopra la scheda.
    page.querySelectorAll('.af-sections').forEach((box) => {
      const visible = Array.from(box.children).some((child) => !child.hasAttribute('data-af-hidden'));
      box.style.display = visible ? '' : 'none';
    });
    if (remember) {
      try { localStorage.setItem(storeKey, name); } catch (e) { /* storage non disponibile */ }
      history.replaceState(null, '', '#' + slug(name));
    }
  }
  function fromHash() {
    const id = window.location.hash.slice(1);
    if (!id) return null;
    const byTab = order.find((n) => slug(n) === id);
    if (byTab) return byTab;
    const target = document.getElementById(id);
    const owner = target && target.closest('[data-af-tab]');
    return owner ? owner.dataset.afTab : null;
  }
  let initial = fromHash();
  if (!initial) { try { initial = localStorage.getItem(storeKey); } catch (e) { initial = null; } }
  page.classList.add('af-tabbed');
  nav.hidden = false;
  select(initial || order[0], false);
  window.addEventListener('hashchange', () => {
    const name = fromHash();
    if (!name) return;
    select(name, false);
    // Arrivando da un riquadro del cruscotto, porta in vista la barra delle schede.
    if (window.location.hash.startsWith('#tab-')) nav.scrollIntoView({block: 'start', behavior: 'smooth'});
  });
})();
