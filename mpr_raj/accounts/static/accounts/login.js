/*
 * Sign-in page only: fetch a fresh captcha challenge.
 *
 * The same URL serves a new challenge every time, so re-requesting it with a
 * throwaway query string is enough — no template URL needs to reach the JS.
 */
var image = document.querySelector(".captcha-row img");

image.addEventListener("click", function () {
  this.src = this.src.split("?")[0] + "?" + Date.now();
});

document.querySelector(".captcha-new").addEventListener("click", function (e) {
  e.preventDefault();
  image.click();
});
