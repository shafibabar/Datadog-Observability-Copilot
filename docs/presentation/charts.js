/* Deck charts — shared by both decks so the figures can never drift apart.
 *
 * Static inline SVG generated from the repo's own records: metrics/prompts.jsonl
 * (written automatically by the Stop hook in .claude/settings.json) and the
 * per-step log in docs/context/TESTING.md. The numbers are historical facts, so
 * the markup is fixed rather than recomputed at view time.
 *
 * Form choices follow the data's job, not taste: magnitude and trend get a single
 * sequential hue with no legend (the title names the series), part-to-whole gets a
 * horizontal stacked bar rather than a two-slice pie. Bars use 4px rounded
 * data-ends anchored to the baseline, lines are 2px with >=8px markers, axes are
 * recessive, and EVERY mark carries a direct label plus a <title> — so no value
 * is encoded by color alone. Palette: validated dark-mode categorical slots 1-2
 * (see the header of deck.js for the validator numbers).
 */
(function () {
  "use strict";
  var FIGURES = {
  "prompts-per-day": `<figure class="viz"><svg viewBox="0 0 720 230" role="img" aria-label="Prompts per active build day">
<line class="ax" x1="8" y1="200" x2="712" y2="200"/>
<path d="M26.285714285714285,200.0 L26.285714285714285,47.400000000000006 Q26.285714285714285,43.400000000000006 30.285714285714285,43.400000000000006 L86.28571428571428,43.400000000000006 Q90.28571428571428,43.400000000000006 90.28571428571428,47.400000000000006 L90.28571428571428,200.0 Z" fill="var(--series-1)"><title>Jun 26: 18 prompts</title></path>
<text class="val" x="58.3" y="36.4" text-anchor="middle">18</text>
<text x="58.3" y="219" text-anchor="middle">Jun 26</text>
<path d="M126.85714285714286,200.0 L126.85714285714286,143.1 Q126.85714285714286,139.1 130.85714285714286,139.1 L186.85714285714286,139.1 Q190.85714285714286,139.1 190.85714285714286,143.1 L190.85714285714286,200.0 Z" fill="var(--series-1)"><title>Jun 27: 7 prompts</title></path>
<text class="val" x="158.9" y="132.1" text-anchor="middle">7</text>
<text x="158.9" y="219" text-anchor="middle">Jun 27</text>
<path d="M227.42857142857142,200.0 L227.42857142857142,151.8 Q227.42857142857142,147.8 231.42857142857142,147.8 L287.42857142857144,147.8 Q291.42857142857144,147.8 291.42857142857144,151.8 L291.42857142857144,200.0 Z" fill="var(--series-1)"><title>Jul 3: 6 prompts</title></path>
<text class="val" x="259.4" y="140.8" text-anchor="middle">6</text>
<text x="259.4" y="219" text-anchor="middle">Jul 3</text>
<path d="M328.0,200.0 L328.0,38.70000000000002 Q328.0,34.70000000000002 332.0,34.70000000000002 L388.0,34.70000000000002 Q392.0,34.70000000000002 392.0,38.70000000000002 L392.0,200.0 Z" fill="var(--series-1)"><title>Jul 8: 19 prompts</title></path>
<text class="val" x="360.0" y="27.7" text-anchor="middle">19</text>
<text x="360.0" y="219" text-anchor="middle">Jul 8</text>
<path d="M428.57142857142856,200.0 L428.57142857142856,169.2 Q428.57142857142856,165.2 432.57142857142856,165.2 L488.57142857142856,165.2 Q492.57142857142856,165.2 492.57142857142856,169.2 L492.57142857142856,200.0 Z" fill="var(--series-1)"><title>Jul 9: 4 prompts</title></path>
<text class="val" x="460.6" y="158.2" text-anchor="middle">4</text>
<text x="460.6" y="219" text-anchor="middle">Jul 9</text>
<path d="M529.1428571428571,200.0 L529.1428571428571,134.39999999999998 Q529.1428571428571,130.39999999999998 533.1428571428571,130.39999999999998 L589.1428571428571,130.39999999999998 Q593.1428571428571,130.39999999999998 593.1428571428571,134.39999999999998 L593.1428571428571,200.0 Z" fill="var(--series-1)"><title>Jul 27: 8 prompts</title></path>
<text class="val" x="561.1" y="123.4" text-anchor="middle">8</text>
<text x="561.1" y="219" text-anchor="middle">Jul 27</text>
<path d="M629.7142857142858,200.0 L629.7142857142858,186.6 Q629.7142857142858,182.6 633.7142857142858,182.6 L689.7142857142858,182.6 Q693.7142857142858,182.6 693.7142857142858,186.6 L693.7142857142858,200.0 Z" fill="var(--series-1)"><title>Jul 28: 2 prompts</title></path>
<text class="val" x="661.7" y="175.6" text-anchor="middle">2</text>
<text x="661.7" y="219" text-anchor="middle">Jul 28</text>
</svg><figcaption>Prompts per active build day, from <code>metrics/prompts.jsonl</code> (recorded automatically by a Stop hook). 64 prompts across 7 active days.</figcaption></figure>`,

  "suite-growth": `<figure class="viz"><svg viewBox="0 0 720 230" role="img" aria-label="Passing tests over time, 113 to 388">
<line class="ax" x1="34" y1="157.5" x2="706" y2="157.5"/>
<text x="26" y="161.5" text-anchor="end">100</text>
<line class="ax" x1="34" y1="115.0" x2="706" y2="115.0"/>
<text x="26" y="119.0" text-anchor="end">200</text>
<line class="ax" x1="34" y1="72.5" x2="706" y2="72.5"/>
<text x="26" y="76.5" text-anchor="end">300</text>
<line class="ax" x1="34" y1="30.0" x2="706" y2="30.0"/>
<text x="26" y="34.0" text-anchor="end">400</text>
<polyline fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" points="34.0,152.0 146.0,139.2 258.0,127.3 370.0,96.7 482.0,81.4 594.0,72.9 706.0,35.1"/>
<circle cx="34.0" cy="152.0" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jun 26: 113 passing</title></circle>
<text x="34.0" y="219" text-anchor="middle">Jun 26</text>
<circle cx="146.0" cy="139.2" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jun 27: 143 passing</title></circle>
<text x="146.0" y="219" text-anchor="middle">Jun 27</text>
<circle cx="258.0" cy="127.3" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jul 3: 171 passing</title></circle>
<text x="258.0" y="219" text-anchor="middle">Jul 3</text>
<circle cx="370.0" cy="96.7" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jul 8: 243 passing</title></circle>
<text x="370.0" y="219" text-anchor="middle">Jul 8</text>
<circle cx="482.0" cy="81.4" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jul 27: 279 passing</title></circle>
<text x="482.0" y="219" text-anchor="middle">Jul 27</text>
<circle cx="594.0" cy="72.9" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Jul 28: 299 passing</title></circle>
<text x="594.0" y="219" text-anchor="middle">Jul 28</text>
<circle cx="706.0" cy="35.1" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"><title>Aug 5: 388 passing</title></circle>
<text x="706.0" y="219" text-anchor="middle">Aug 5</text>
<text class="val" x="34.0" y="141.0" text-anchor="start">113</text>
<text class="val" x="706.0" y="24.1" text-anchor="end">388</text>
</svg><figcaption>Passing tests at each logged step (<code>docs/context/TESTING.md</code>). The invariant was binding: once green, always green.</figcaption></figure>`,

  "intent-split": `<figure class="viz"><svg viewBox="0 0 720 96" role="img" aria-label="24 planning prompts and 40 implementation prompts of 64 total">
<rect x="8" y="10" width="263.0" height="42" rx="4" fill="var(--series-1)"><title>Planning and Q&amp;A: 24 prompts</title></rect>
<rect x="273.0" y="10" width="439.0" height="42" rx="4" fill="var(--series-2)"><title>Implementation: 40 prompts</title></rect>
<text class="val" x="24" y="36.0">24 &nbsp;·&nbsp; 38%</text>
<text class="val" x="289.0" y="36.0">40 &nbsp;·&nbsp; 62%</text>
<text x="8" y="74">Planning &amp; Q&amp;A</text>
<text x="273.0" y="74">Implementation</text>
</svg><figcaption>Every prompt classified by the collector. Over a third of the work was deciding what to build, before any code.</figcaption></figure>`
  };
  document.querySelectorAll("[data-chart]").forEach(function (el) {
    var svg = FIGURES[el.getAttribute("data-chart")];
    if (svg) el.innerHTML = svg;
  });
})();
