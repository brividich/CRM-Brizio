/* Finestre centrali della sezione (dialog nativo): [data-apri-dialogo="x"] apre #dialogo-x. */
(function () {
  document.querySelectorAll('[data-apri-dialogo]').forEach(function (b) {
    b.addEventListener('click', function () {
      var d = document.getElementById('dialogo-' + b.dataset.apriDialogo);
      if (d && d.showModal) d.showModal();
    });
  });
  document.querySelectorAll('[data-chiudi-dialogo]').forEach(function (b) {
    b.addEventListener('click', function () { b.closest('dialog').close(); });
  });
})();
