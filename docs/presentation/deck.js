/* Presentation deck — shared navigation. Zero dependencies, no build step.
 *
 * Keys:  ->  space  PgDn  = next        <-  PgUp = previous
 *        Home / End       = first / last
 *        N                = toggle speaker notes
 *        F                = fullscreen
 *        digit + Enter    = jump to slide
 *
 * The slide index lives in location.hash, so a reload keeps your place mid-talk
 * and you can link straight to a slide.
 *
 * Chart colors used by both decks are the data-viz categorical slots 1-2 stepped
 * for the dark surface (#3987e5 blue, #d95926 orange on #1a1a19). That pair was
 * run through the palette validator's six checks in dark mode and passes all of
 * them: normal-vision dE 31.8 (floor 15), CVD dE 26.8 under protanopia (target 8),
 * contrast 4.79:1 and 4.48:1 vs the surface (min 3.0). Every mark is also
 * direct-labeled with its value, so nothing is encoded by color alone.
 */
(function () {
  "use strict";

  var slides = [].slice.call(document.querySelectorAll(".slide"));
  var bar = document.getElementById("bar");
  var hud = document.getElementById("hud");
  var notes = document.getElementById("notes");
  var i = 0;
  var typed = "";

  function clamp(n) { return Math.max(0, Math.min(slides.length - 1, n)); }

  function show(n, push) {
    i = clamp(n);
    slides.forEach(function (s, k) { s.classList.toggle("on", k === i); });
    if (bar) bar.style.width = ((i + 1) / slides.length * 100) + "%";
    if (hud) hud.innerHTML = "<b>" + (i + 1) + "</b> / " + slides.length + " &nbsp;·&nbsp; N notes";
    if (notes) {
      var n0 = slides[i].getAttribute("data-notes") || "No notes for this slide.";
      notes.innerHTML = "<h3>Speaker notes — slide " + (i + 1) + "</h3>" + n0;
      notes.scrollTop = 0;
    }
    slides[i].scrollTop = 0;
    if (push !== false) history.replaceState(null, "", "#" + (i + 1));
  }

  function fromHash() {
    var n = parseInt((location.hash || "").replace("#", ""), 10);
    return isNaN(n) ? 0 : n - 1;
  }

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key;
    if (k >= "0" && k <= "9") { typed += k; return; }
    if (k === "Enter" && typed) { show(parseInt(typed, 10) - 1); typed = ""; e.preventDefault(); return; }
    typed = "";
    if (k === "ArrowRight" || k === " " || k === "PageDown" || k === "ArrowDown") { show(i + 1); e.preventDefault(); }
    else if (k === "ArrowLeft" || k === "PageUp" || k === "ArrowUp") { show(i - 1); e.preventDefault(); }
    else if (k === "Home") { show(0); e.preventDefault(); }
    else if (k === "End") { show(slides.length - 1); e.preventDefault(); }
    else if (k === "n" || k === "N") { document.body.classList.toggle("notes"); }
    else if (k === "f" || k === "F") {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen();
    }
  });

  // Click-through on the slide body, but never swallow a link or a text selection.
  document.addEventListener("click", function (e) {
    if (e.target.closest("a") || e.target.closest("#notes")) return;
    if (window.getSelection && String(window.getSelection())) return;
    show(i + 1);
  });

  window.addEventListener("hashchange", function () { show(fromHash(), false); });
  show(fromHash());
})();
