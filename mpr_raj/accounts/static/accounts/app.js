/*
 * Behaviour for the signed-in shell. Loaded with `defer` by app.html, so the
 * DOM is parsed by the time this runs and every element below exists.
 *
 * boot.js has already applied the saved sidebar and theme state; this file only
 * handles the toggles that change them.
 */

// Sidebar collapse — persisted; boot.js reads it back before paint.
(function () {
  var btn = document.querySelector(".sb-toggle");
  function sync() {
    var c = document.documentElement.classList.contains("sb-collapsed");
    btn.setAttribute("aria-expanded", c ? "false" : "true");
    btn.title = c ? "Expand sidebar" : "Collapse sidebar";
    btn.setAttribute("aria-label", btn.title);
  }
  btn.addEventListener("click", function () {
    var c = document.documentElement.classList.toggle("sb-collapsed");
    localStorage.setItem("sb", c ? "1" : "0");
    sync();
  });
  sync();
})();

// Theme — persisted; boot.js reads it back before paint.
(function () {
  var btn = document.querySelector(".theme-toggle"), root = document.documentElement;
  function sync() {
    var dark = root.dataset.theme === "dark";
    btn.setAttribute("aria-pressed", dark ? "true" : "false");
    btn.title = dark ? "Switch to light theme" : "Switch to dark theme";
  }
  btn.addEventListener("click", function () {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", root.dataset.theme);
    sync();
  });
  sync();
})();

// ponytail: native <details> menu; JS only closes it on outside-click / Escape.
document.addEventListener("click", function (e) {
  document.querySelectorAll("details.acct-menu[open]").forEach(function (d) {
    if (!d.contains(e.target)) d.removeAttribute("open");
  });
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape")
    document.querySelectorAll("details.acct-menu[open]").forEach(function (d) { d.removeAttribute("open"); });
});

// Destructive forms ask first. One delegated listener, not an onsubmit per form:
// a template opts in by putting the question in data-confirm.
document.addEventListener("submit", function (e) {
  var question = e.target.dataset.confirm;
  if (question && !confirm(question)) e.preventDefault();
});

// The period picker submits itself when you choose a month. Its <noscript>
// button covers the case where this never runs.
document.querySelectorAll("[data-submit-on-change]").forEach(function (el) {
  el.addEventListener("change", function () { this.form.submit(); });
});
