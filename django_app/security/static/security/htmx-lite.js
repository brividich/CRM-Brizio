(function () {
  function csrfTokenFromCookie() {
    var match = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function csrfTokenForForm(form) {
    var input = form.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : csrfTokenFromCookie();
  }

  function submitControls(form) {
    return Array.prototype.slice.call(form.querySelectorAll("button[type='submit'], input[type='submit']"));
  }

  function applySwap(target, html, swap) {
    if (!target || swap === "none") {
      return;
    }
    if (swap === "outerHTML") {
      target.outerHTML = html;
      return;
    }
    if (swap === "beforeend") {
      target.insertAdjacentHTML("beforeend", html);
      return;
    }
    if (swap === "afterbegin") {
      target.insertAdjacentHTML("afterbegin", html);
      return;
    }
    target.innerHTML = html;
  }

  function submitHtmxForm(form) {
    var targetSelector = form.getAttribute("hx-target");
    var target = targetSelector ? document.querySelector(targetSelector) : null;
    var method = (form.getAttribute("hx-post") ? "POST" : form.method || "GET").toUpperCase();
    var url = form.getAttribute("hx-post") || form.action;
    var body = new FormData(form);
    var swap = form.getAttribute("hx-swap") || "innerHTML";
    var buttons = submitControls(form);

    if (form.dataset.hxLiteSubmitting === "true") {
      return;
    }
    form.dataset.hxLiteSubmitting = "true";
    buttons.forEach(function (button) {
      button.dataset.hxLiteDisabled = button.disabled ? "true" : "false";
      button.disabled = true;
      if (button.dataset.busyLabel) {
        button.dataset.hxLiteLabel = button.textContent;
        button.textContent = button.dataset.busyLabel;
      }
    });

    fetch(url, {
      method: method,
      body: body,
      headers: {
        "HX-Request": "true",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfTokenForForm(form)
      },
      credentials: "same-origin"
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.text();
      })
      .then(function (html) {
        applySwap(target, html, swap);
      })
      .catch(function () {
        if (target) {
          target.innerHTML = '<span class="sec-badge critical">Request failed</span>';
        }
      })
      .finally(function () {
        form.dataset.hxLiteSubmitting = "false";
        buttons.forEach(function (button) {
          button.disabled = button.dataset.hxLiteDisabled === "true";
          delete button.dataset.hxLiteDisabled;
          if (button.dataset.hxLiteLabel !== undefined) {
            button.textContent = button.dataset.hxLiteLabel;
            delete button.dataset.hxLiteLabel;
          }
        });
      });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches("form[hx-post]")) {
      return;
    }
    // Il layout del portale carica anche htmx vero: se ha gia' preso il form non si manda una seconda richiesta.
    if (event.defaultPrevented && window.htmx) {
      return;
    }
    event.preventDefault();
    submitHtmxForm(form);
  });

  // Etichetta d'attesa (data-busy-label) anche quando la richiesta la fa htmx vero.
  function busyButtons(event) {
    var elt = event.detail && event.detail.elt;
    return elt && elt.querySelectorAll ? Array.prototype.slice.call(elt.querySelectorAll("button[data-busy-label]")) : [];
  }
  document.addEventListener("htmx:beforeRequest", function (event) {
    busyButtons(event).forEach(function (button) {
      button.dataset.hxLiteLabel = button.textContent;
      button.textContent = button.dataset.busyLabel;
      button.disabled = true;
    });
  });
  document.addEventListener("htmx:afterRequest", function (event) {
    busyButtons(event).forEach(function (button) {
      if (button.dataset.hxLiteLabel !== undefined) {
        button.textContent = button.dataset.hxLiteLabel;
        delete button.dataset.hxLiteLabel;
      }
      button.disabled = false;
    });
  });
})();
