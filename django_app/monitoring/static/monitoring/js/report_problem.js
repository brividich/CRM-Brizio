(function () {
  var modal = document.getElementById("monitoringProblemModal");
  var form = document.getElementById("monitoringProblemForm");
  var messageField = document.getElementById("monitoringProblemMessage");
  var statusEl = document.getElementById("monitoringProblemStatus");
  var toast = document.getElementById("monitoringProblemToast");
  var currentUrlField = document.getElementById("monitoringProblemCurrentUrl");
  var routeNameField = document.getElementById("monitoringProblemRouteName");
  var moduleNameField = document.getElementById("monitoringProblemModuleName");
  var browserInfoField = document.getElementById("monitoringProblemBrowserInfo");
  var clientTimestampField = document.getElementById("monitoringProblemClientTimestamp");
  var submitBtn = document.getElementById("monitoringProblemSubmit");

  if (!modal || !form || !messageField) return;

  var toastTimer = null;

  function setStatus(message, mode) {
    statusEl.textContent = message || "";
    statusEl.classList.remove("is-error", "is-success");
    if (mode) statusEl.classList.add(mode);
  }

  function openModal(trigger) {
    currentUrlField.value = (trigger && trigger.getAttribute("data-current-url")) || window.location.pathname + window.location.search;
    routeNameField.value = (trigger && trigger.getAttribute("data-route-name")) || routeNameField.value || "";
    moduleNameField.value = (trigger && trigger.getAttribute("data-module-name")) || moduleNameField.value || "";
    browserInfoField.value = window.navigator.userAgent || "";
    clientTimestampField.value = new Date().toISOString();
    messageField.value = "";
    setStatus("", "");
    modal.hidden = false;
    document.body.classList.add("monitoring-modal-open");
    window.setTimeout(function () {
      messageField.focus();
    }, 20);
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("monitoring-modal-open");
    setStatus("", "");
  }

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toast.hidden = true;
    }, 2800);
  }

  document.querySelectorAll("[data-monitoring-report-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openModal(btn);
    });
  });

  document.querySelectorAll("[data-monitoring-report-close]").forEach(function (btn) {
    btn.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", function (event) {
    if (event.target === modal) closeModal();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    setStatus("", "");

    var csrfInput = form.querySelector("input[name='csrfmiddlewaretoken']");
    var formData = new FormData(form);
    submitBtn.disabled = true;
    submitBtn.classList.add("btn-loading");

    fetch(form.getAttribute("data-report-url") || form.action, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfInput ? csrfInput.value : "",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: formData
    })
      .then(function (response) {
        return response.json().catch(function () { return { ok: false, error: "invalid_json" }; });
      })
      .then(function (payload) {
        if (!payload.ok) {
          setStatus("Impossibile inviare la segnalazione. Riprova tra qualche secondo.", "is-error");
          return;
        }
        closeModal();
        showToast(payload.message || "Segnalazione inviata");
      })
      .catch(function () {
        setStatus("Errore di rete durante l'invio della segnalazione.", "is-error");
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.classList.remove("btn-loading");
      });
  });
})();
