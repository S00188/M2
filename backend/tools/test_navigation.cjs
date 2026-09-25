const fs = require("fs");
const vm = require("vm");
const assert = require("assert/strict");
const source = fs.readFileSync(require("path").join(__dirname, "../app/static/app.js"), "utf8");
function element(id) {
  const classes = new Set();
  return { id, dataset: {}, style: {}, clientWidth: 390, scrollLeft: 0,
    classList: { contains: x => classes.has(x), add: x => classes.add(x),
      remove: x => classes.delete(x), toggle(x, on) { on ? classes.add(x) : classes.delete(x); } },
    addEventListener() {}, scrollTo(options) { this.lastScroll = options; this.scrollLeft = options.left; }
  };
}
const ids = ["game", "home", "gamepanels", ...["morning","night","day","vote","lynch","kamikaze","outcome"].map(x => "pg-" + x)];
const els = Object.fromEntries(ids.map(id => [id, element(id)]));
const buttons = ["chat","game","cabinet"].map(pane => Object.assign(element(pane), {dataset: {pane}}));
let scrolls = 0;
const ctx = vm.createContext({
  document: {body: element("body"), getElementById: id => els[id],
    querySelectorAll: q => q === ".screen" ? [els.game, els.home] : q === "#gameNav button" ? buttons : []},
  window: {scrollTo: () => scrolls++, matchMedia: () => ({matches: false}), addEventListener() {}},
  requestAnimationFrame: f => { f(); return 1; }, cancelAnimationFrame() {},
  currentGamePhase: null, gamePaneFocusedOnce: false, themeMode: "dark", _pushHistory() {},
});
vm.runInContext('const screens = () => [...document.querySelectorAll(".screen")]; const GAME_PHASES = ["morning","night","day","vote","lynch","kamikaze","outcome"];' +
  source.slice(source.indexOf("function go(id)"), source.indexOf("// The lobby's top-right")), ctx);
vm.runInContext('go("night")', ctx);
assert.equal(els.gamepanels.lastScroll.left, 390);
assert.equal(els.gamepanels.lastScroll.behavior, "instant");
assert(buttons[1].classList.contains("active"));
vm.runInContext('scrollToPane("cabinet")', ctx);
assert.equal(els.gamepanels.lastScroll.behavior, "smooth");
const before = scrolls;
vm.runInContext('go("night")', ctx);
assert.equal(els.gamepanels.scrollLeft, 780, "state push must preserve selected pane");
assert.equal(scrolls, before, "state push must preserve vertical scroll");
vm.runInContext('go("home"); go("night")', ctx);
assert.equal(els.gamepanels.scrollLeft, 390, "re-enter at center");
vm.runInContext('go("vote")', ctx);
assert.equal(els["pg-night"].style.display, "none");
assert(els["pg-vote"].classList.contains("phase-enter"));
console.log("Navigation checks passed: center entry, re-entry, smooth switch, stable updates, phase change.");
