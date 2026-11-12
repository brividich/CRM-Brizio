/* Riga rapida «attività» dentro un incontro (_quick_task_bar.html).
 * Invio salva senza ricaricare; il responsabile resta, l'inizio passa al giorno
 * dopo la fine appena scritta e si riparte dal titolo. */
(function () {
  'use strict';

  function csrf() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function giornoDopo(iso) {
    var parti = iso.split('-').map(Number);
    var d = new Date(Date.UTC(parti[0], parti[1] - 1, parti[2] + 1));
    return d.toISOString().slice(0, 10);
  }

  function dataIt(iso) {
    var p = iso.split('-');
    return p[2] + '/' + p[1] + '/' + p[0];
  }

  document.querySelectorAll('[data-qt-bar]').forEach(function (bar) {
    function f(nome) { return bar.querySelector('[data-qt="' + nome + '"]'); }
    var title = f('title');
    if (!title) { return; }
    var owner = f('owner');
    var start = f('start');
    var due = f('due');
    var save = f('save');
    var err = f('err');
    var log = f('log');
    var count = bar.querySelector('[data-qt-count]');
    var inCorso = false;

    var inizioProposto = start.value;

    function valore(nome) {
      var campo = f(nome);
      return campo ? campo.value : '';
    }

    function mostraEsito(testo) {
      err.textContent = testo;
      err.hidden = !testo;
      err.classList.add('qt-ok');
    }

    /* I campi dell'attrezzatura compaiono solo per la scelta che li chiede. */
    function sincronizzaAttrezzatura() {
      var modo = valore('tooling');
      bar.querySelectorAll('[data-qt-show]').forEach(function (campo) {
        campo.hidden = campo.dataset.qtShow.split(' ').indexOf(modo) < 0;
      });
    }

    function azzeraOpzioni() {
      ['existing', 'category', 'tool-existing', 'tool-pn', 'tool-code', 'tool-note'].forEach(function (nome) {
        var campo = f(nome);
        if (campo) { campo.value = ''; }
      });
      if (f('priority')) { f('priority').value = 'MEDIUM'; }
      if (f('tooling')) { f('tooling').value = 'none'; }
      sincronizzaAttrezzatura();
      sincronizzaBottone();
    }

    function sincronizzaBottone() {
      var aggiorna = !!valore('existing');
      save.textContent = aggiorna ? 'Aggiorna' : 'Aggiungi';
      title.placeholder = aggiorna ? 'Nuovo titolo (lascia vuoto per non cambiarlo)' : 'Nuova attività: scrivi il titolo e premi Invio';
    }

    function mostraErrore(testo) {
      err.classList.remove('qt-ok');
      err.textContent = testo;
      err.hidden = !testo;
    }

    function salva() {
      var titolo = title.value.trim();
      if (!titolo && !valore('existing')) { title.focus(); return; }
      if (inCorso) { return; }
      inCorso = true;
      save.disabled = true;
      mostraErrore('');
      fetch(bar.dataset.url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrf(),
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: new URLSearchParams({
          title: titolo,
          task_id: valore('existing'),
          assigned_to: owner.value,
          next_step_due: start.value,
          due_date: due.value,
          category: valore('category'),
          priority: valore('priority') || 'MEDIUM',
          tooling_mode: valore('tooling') || 'none',
          tooling_existing_attrezzatura: valore('tool-existing'),
          tooling_part_number: valore('tool-pn'),
          tooling_code: valore('tool-code'),
          tooling_description: valore('tool-note')
        })
      }).then(function (r) {
        return r.json().catch(function () { return { ok: false }; });
      }).then(function (data) {
        if (!data.ok) {
          mostraErrore(data.message || (data.reason && data.reason.indexOf(' ') > 0 ? data.reason : 'Attività non creata: riprova.'));
          return;
        }
        if (data.created === false) {
          bar.querySelectorAll('[data-qt="log"] a').forEach(function (link) {
            if (link.getAttribute('href') === data.task_url) { link.textContent = data.title; }
          });
          mostraEsito('Attività «' + data.title + '» aggiornata.');
          azzeraOpzioni();
          title.value = '';
          due.value = '';
          start.value = inizioProposto;
          title.focus();
          return;
        }
        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = data.task_url;
        a.textContent = data.title;
        li.appendChild(a);
        var coda = '';
        if (owner.value) { coda += ' · ' + owner.options[owner.selectedIndex].textContent; }
        if (data.due_date) { coda += ' · entro ' + dataIt(data.due_date); }
        li.appendChild(document.createTextNode(coda));
        log.appendChild(li);
        if (count) { count.textContent = String(log.children.length); }
        if (window.meetingTaskModalAddTask) { window.meetingTaskModalAddTask({ id: data.task_id, title: data.title }); }
        var esistente = f('existing');
        if (esistente) {
          var opt = document.createElement('option');
          opt.value = String(data.task_id);
          opt.textContent = data.title;
          esistente.appendChild(opt);
        }
        azzeraOpzioni();
        if (data.due_date) { start.value = giornoDopo(data.due_date); }
        inizioProposto = start.value;
        title.value = '';
        due.value = '';
        title.focus();
      }).catch(function () {
        mostraErrore('Connessione assente: attività non creata.');
      }).finally(function () {
        inCorso = false;
        save.disabled = false;
      });
    }

    save.addEventListener('click', salva);
    /* Invio salva: nell'esito la riga sta dentro un form e non deve inviarlo. */
    [title, start, due].forEach(function (campo) {
      campo.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); salva(); }
      });
    });

    var piu = f('more');
    var box = f('more-box');
    if (piu && box) {
      piu.addEventListener('click', function () {
        box.hidden = !box.hidden;
        piu.setAttribute('aria-expanded', String(!box.hidden));
      });
    }
    if (f('tooling')) { f('tooling').addEventListener('change', sincronizzaAttrezzatura); }
    if (f('existing')) {
      /* Aggiornando un'attività le date proposte non devono sovrascrivere le sue. */
      f('existing').addEventListener('change', function () {
        if (valore('existing')) { start.value = ''; due.value = ''; } else { start.value = inizioProposto; }
        sincronizzaBottone();
      });
    }
    /* Invio nei campi del blocco salva come nella riga, senza inviare il form dell'esito. */
    if (box) {
      box.querySelectorAll('input').forEach(function (campo) {
        campo.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter') { ev.preventDefault(); salva(); }
        });
      });
    }
  });
})();
