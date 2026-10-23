"use strict";
(function () {
  var D = window.DATA;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (m) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]; }); };
  var fmt = function (n, d) { return n.toFixed(d == null ? 2 : d).replace(".", ","); };
  var SHORT = ["Покрытие", "Зрелость", "Открытость", "Интегр.", "Данные"];
  var state = { w: D.crit.map(function (c) { return c.w; }), thr: { take: D.thr.take, idea: D.thr.idea }, sort: { k: "total", d: -1 }, cat: "", q: "", open: {}, all: false };

  function total(c) {
    var sw = state.w.reduce(function (a, b) { return a + b; }, 0);
    if (!sw) return 0;
    return Math.round(c.s.reduce(function (a, s, i) { return a + s * state.w[i]; }, 0) / sw * 100) / 100;
  }
  function verdict(t) {
    if (t >= state.thr.take) return ["Брать", "ok"];
    if (t >= state.thr.idea) return ["Рассмотреть / взять идею", "mid"];
    return ["Только как референс", "low"];
  }
  function enrich() {
    var rows = D.comps.map(function (c) { var r = Object.assign({}, c); r.t = total(c); return r; });
    rows.forEach(function (r) { r.rk = rows.filter(function (o) { return o.c === r.c && o.t > r.t; }).length + 1; r.v = verdict(r.t); });
    return rows;
  }
  var cats = []; D.comps.forEach(function (c) { if (cats.indexOf(c.c) < 0) cats.push(c.c); });

  /* ---------- compare ---------- */
  function renderCats(rows) {
    var avgs = cats.map(function (c) { var rs = rows.filter(function (r) { return r.c === c; }); return rs.reduce(function (a, r) { return a + r.t; }, 0) / rs.length; });
    var minAvg = Math.min.apply(null, avgs);
    $("#cats").innerHTML = cats.map(function (c, i) {
      var rs = rows.filter(function (r) { return r.c === c; }).sort(function (a, b) { return b.t - a.t || a.n.localeCompare(b.n); }).slice(0, 3);
      var top = rs.map(function (r, k) {
        return '<li><span class="pl">' + (k + 1) + '</span><a href="' + esc(r.u) + '" target="_blank" rel="noopener noreferrer">' + esc(r.n) + '</a><span class="pv">' + fmt(r.t) + '</span></li>';
      }).join("");
      var total = rows.filter(function (r) { return r.c === c; }).length;
      return '<div class="cat-card' + (avgs[i] === minAvg ? " weak" : "") + '"><h4>' + esc(c) + '</h4><div class="avg">' + fmt(avgs[i]) + ' <small>средний, ' + total + ' шт.</small></div><ol class="top3">' + top + '</ol></div>';
    }).join("");
  }
  function render() { var c = $("#cats"); if (c && !c.children.length) renderCats(enrich()); }
  render();

  /* ---------- sources filter ---------- */
  $("#srcQ").addEventListener("input", function (e) {
    var q = e.target.value.trim().toLowerCase();
    $$("#srcList li").forEach(function (li) { li.hidden = q && li.textContent.toLowerCase().indexOf(q) < 0 && li.innerHTML.toLowerCase().indexOf(q) < 0; });
  });

  /* ---------- подсветка раздела в меню ---------- */
  var links = $$(".top nav a"), blocks = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
  var navEl = $(".top nav"), lastOn = null;
  function spy() {
    var cur = null;
    blocks.forEach(function (b, i) { if (b && b.getBoundingClientRect().top <= 120) cur = i; });
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) cur = blocks.length - 1;
    if (cur === lastOn) return;
    lastOn = cur;
    links.forEach(function (l, i) { l.classList.toggle("on", i === cur); });
    if (cur != null && navEl.scrollWidth > navEl.clientWidth) {
      var l = links[cur];
      navEl.scrollLeft = l.offsetLeft - (navEl.clientWidth - l.offsetWidth) / 2;
    }
  }
  window.addEventListener("scroll", spy, { passive: true });
  window.addEventListener("resize", spy);
  spy();
})();
