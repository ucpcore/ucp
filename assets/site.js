(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
  }
  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { selectTab(tab); });
    tab.addEventListener("keydown", function (e) {
      var next = null;
      if (e.key === "ArrowRight") next = tabs[(i + 1) % tabs.length];
      if (e.key === "ArrowLeft") next = tabs[(i - 1 + tabs.length) % tabs.length];
      if (next) { next.focus(); selectTab(next); e.preventDefault(); }
    });
  });

  var copyIcon = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3.5v5A1.5 1.5 0 0 0 4 10h1.5"/></svg>';
  var checkIcon = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 8.5l3.5 3.5L13 4.5"/></svg>';
  Array.prototype.forEach.call(document.querySelectorAll(".copy"), function (btn) {
    btn.innerHTML = copyIcon;
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () {
        btn.classList.add("done");
        btn.innerHTML = checkIcon + "<span>copied</span>";
        setTimeout(function () {
          btn.classList.remove("done");
          btn.innerHTML = copyIcon;
        }, 1600);
      });
    });
  });

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var targets = Array.prototype.slice.call(document.querySelectorAll(".reveal, .term"));
  if (reduced || !("IntersectionObserver" in window)) {
    targets.forEach(function (el) { el.classList.add("in", "armed"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add(entry.target.classList.contains("term") ? "armed" : "in");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.25 });
    targets.forEach(function (el) { io.observe(el); });
  }
})();
