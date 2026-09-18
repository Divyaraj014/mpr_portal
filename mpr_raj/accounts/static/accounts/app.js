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

// Live word count under capped text boxes. Counts like the server (split on
// whitespace); the static "Up to N words." help text is what shows without JS.
document.querySelectorAll("textarea[data-max-words]").forEach(function (box) {
  var max = +box.dataset.maxWords, out = box.nextElementSibling;
  if (!out || !out.classList.contains("helptext")) return;
  out.setAttribute("aria-live", "polite");
  function sync() {
    var n = box.value.trim() ? box.value.trim().split(/\s+/).length : 0;
    out.textContent = n + " / " + max + " words · " +
      (n > max ? (n - max) + " over the limit" : (max - n) + " remaining");
    out.classList.toggle("over", n > max);
  }
  box.addEventListener("input", sync);
  sync();
});

// Figures page: suggest "since inception" as last month's total + this month's
// figure. Never filled in by itself — the PL presses Use this or types their own.
// Only plain numbers ("1,204", "12.5") add up; "NA" or "₹ 2 Cr" get no suggestion.
(function () {
  function num(s) {
    s = (s || "").replace(/[,\s]/g, "");
    return /^-?\d+(\.\d+)?$/.test(s) ? parseFloat(s) : null;
  }
  function fmt(n) { return n.toLocaleString("en-IN", { maximumFractionDigits: 2 }); }
  document.querySelectorAll("input[data-last-cumulative]").forEach(function (cum) {
    var row = cum.closest(".trow"), last = num(cum.dataset.lastCumulative),
        rep = row.querySelector("input[name$='-reporting_month']"), hint = row.querySelector(".calc");
    if (last === null || !rep || !hint) return;
    var text = hint.querySelector("span"), use = hint.querySelector("button");
    function sync() {
      var r = num(rep.value), c = num(cum.value);
      hint.hidden = r === null;
      if (r === null) return;
      var total = fmt(last + r), same = c !== null && fmt(c) === total;
      text.textContent = fmt(last) + " + " + fmt(r) + " = " + total + (same ? " ✓" : "");
      use.hidden = same;
    }
    use.addEventListener("click", function () { cum.value = fmt(last + num(rep.value)); sync(); });
    rep.addEventListener("input", sync);
    cum.addEventListener("input", sync);
    sync();
  });
})();
