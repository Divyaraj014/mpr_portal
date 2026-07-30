/*
 * Runs before the page paints, on every screen.
 *
 * base.html loads this WITHOUT defer or async on purpose: it has to apply the
 * saved sidebar width and theme before the first paint, or every navigation
 * flashes the wrong width and a white page. Keep it tiny for the same reason.
 * Unset theme follows the OS.
 */
if (localStorage.getItem("sb") === "1") document.documentElement.classList.add("sb-collapsed");
document.documentElement.dataset.theme = localStorage.getItem("theme")
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
