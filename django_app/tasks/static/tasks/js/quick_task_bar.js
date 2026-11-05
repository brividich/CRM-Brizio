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

    function mostraErrore(testo) {
      err.textContent = testo;
      err.hidden = !testo;
    }

    function salva() {
      var titolo = title.value.trim();
      if (!titolo) { title.focus(); return; }
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
          assigned_to: owner.value,
          next_step_due: start.value,
          due_date: due.value
        })
      }).then(function (r) {
        return r.json().catch(function () { return { ok: false }; });
      }).then(function (data) {
        if (!data.ok) {
          mostraErrore(data.message || (data.reason && data.reason.indexOf(' ') > 0 ? data.reason : 'Attività non creata: riprova.'));
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
        if (data.due_date) { start.value = giornoDopo(data.due_date); }
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
    if (piu) {
      piu.addEventListener('click', function () {
        if (!window.openCreateTaskModal) { return; }
        window.openCreateTaskModal('', null);
        var porta = { 'ctm-title': title.value, 'ctm-assignee': owner.value, 'ctm-start': start.value, 'ctm-due': due.value };
        Object.keys(porta).forEach(function (id) {
          var campo = document.getElementById(id);
          if (campo) { campo.value = porta[id]; }
        });
      });
    }
  });
})();
