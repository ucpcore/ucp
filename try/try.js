(function () {
  "use strict";

  var GITHUB_URL = /^https?:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/issues\/(\d+)/i;
  var GITHUB_REF = /^([\w.-]+)\/([\w.-]+)#(\d+)$/;

  var manifest = null;
  var lastPackage = null;

  var form = document.getElementById("try-form");
  var input = document.getElementById("try-input");
  var statusEl = document.getElementById("try-status");
  var results = document.getElementById("try-results");
  var picks = document.getElementById("try-picks");
  var submitBtn = document.getElementById("try-submit");

  function demoApiUrl() {
    if (manifest && manifest.demo_api) {
      return manifest.demo_api;
    }
    if (location.hostname === "127.0.0.1" || location.hostname === "localhost") {
      return "http://127.0.0.1:8080/v1/demo/generate";
    }
    return "https://demo.ucpcore.org/v1/demo/generate";
  }

  function normalizeRef(raw) {
    var text = (raw || "").trim();
    if (!text) return null;
    var urlMatch = text.match(GITHUB_URL);
    if (urlMatch) {
      return urlMatch[1] + "/" + urlMatch[2] + "#" + urlMatch[3];
    }
    if (GITHUB_REF.test(text)) return text;
    return null;
  }

  function curatedExample(ref) {
    if (!manifest || !manifest.examples) return null;
    return manifest.examples.find(function (ex) { return ex.ref === ref; }) || null;
  }

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "try-hint" + (kind ? " try-hint-" + kind : "");
  }

  function setLoading(on) {
    submitBtn.disabled = on;
    submitBtn.textContent = on ? "Generating…" : "Generate";
  }

  function formatTokens(n) {
    if (!n && n !== 0) return "—";
    return "~" + Number(n).toLocaleString("en-US");
  }

  function salienceLabel(claim) {
    if (claim.salience == null) return "";
    var method = claim.salience_method ? " · " + claim.salience_method : "";
    return claim.salience.toFixed(2) + method;
  }

  function renderStats(stats, pkg) {
    var el = document.getElementById("try-stats");
    var title = (pkg.entity && pkg.entity.title) || stats.ref || "Package";
    var raw = stats.raw_tokens;
    var ucp = stats.ucp_tokens;
    var pct = stats.reduction_pct;
    if (raw && ucp && pct == null) {
      pct = Math.max(0, Math.round(100 - (ucp * 100 / Math.max(raw, 1))));
    }
    el.innerHTML =
      '<div class="try-stat-card">' +
        '<h3>' + escapeHtml(title) + '</h3>' +
        '<p class="try-ref mono">' + escapeHtml(stats.ref || "") + '</p>' +
        '<div class="try-bars">' +
          '<div class="try-bar-row"><span>raw thread</span><span class="n">' + formatTokens(raw) + '</span></div>' +
          '<div class="bar-track"><div class="bar raw" style="width:100%"></div></div>' +
          '<div class="try-bar-row"><span>ucp package</span><span class="n win">' + formatTokens(ucp) + '</span></div>' +
          '<div class="bar-track"><div class="bar ucp" style="width:' + Math.max(8, Math.min(100, ucp && raw ? (ucp * 100 / raw) : 30)) + '%"></div></div>' +
        '</div>' +
        (pct > 0 ? '<p class="try-win"><strong>' + pct + '% smaller</strong> with provenance intact</p>' : '') +
      '</div>';
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderPackage(pkg, stats) {
    lastPackage = pkg;
    renderStats(stats || { ref: (pkg.entity && pkg.entity.ref && pkg.entity.ref.id) || "" }, pkg);

    document.getElementById("try-summary").textContent = (pkg.summary && pkg.summary.text) || "(no summary)";

    var mk = document.getElementById("try-must-know");
    mk.innerHTML = "";
    (pkg.must_know || []).slice(0, 12).forEach(function (claim) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="try-claim-text">' + escapeHtml(claim.text) + '</span>' +
        (claim.salience != null ? '<span class="try-salience mono">' + escapeHtml(salienceLabel(claim)) + '</span>' : '');
      mk.appendChild(li);
    });
    if (!(pkg.must_know || []).length) {
      mk.innerHTML = '<li class="muted">No must-know claims</li>';
    }

    var dec = document.getElementById("try-decisions");
    dec.innerHTML = "";
    (pkg.decisions || []).slice(0, 8).forEach(function (d) {
      var li = document.createElement("li");
      var status = d.status ? ' <span class="tag">' + escapeHtml(d.status) + '</span>' : "";
      li.innerHTML = "<strong>" + escapeHtml(d.title || d.summary || "Decision") + "</strong>" + status;
      dec.appendChild(li);
    });
    if (!(pkg.decisions || []).length) {
      dec.innerHTML = '<li class="muted">No structured decisions</li>';
    }

    var conf = document.getElementById("try-conflicts");
    conf.innerHTML = "";
    (pkg.conflicts || []).slice(0, 6).forEach(function (c) {
      var li = document.createElement("li");
      li.textContent = c.summary || c.description || "Unresolved conflict";
      conf.appendChild(li);
    });
    if (!(pkg.conflicts || []).length) {
      conf.innerHTML = '<li class="muted">No conflicts detected</li>';
    }

    var link = document.getElementById("try-json-link");
    var blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
    link.href = URL.createObjectURL(blob);
    link.download = (stats && stats.ref ? stats.ref.replace("/", "-").replace("#", "-") : "package") + ".ucp.json";

    results.classList.remove("hidden");
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function loadCurated(example) {
    setLoading(true);
    setStatus("Loading " + example.ref + "…");
    return fetch("/try/data/" + example.file)
      .then(function (r) {
        if (!r.ok) throw new Error("cached package not found");
        return r.json();
      })
      .then(function (pkg) {
        renderPackage(pkg, {
          ref: example.ref,
          raw_tokens: example.raw_tokens,
          ucp_tokens: example.ucp_tokens,
          reduction_pct: example.raw_tokens
            ? Math.max(0, Math.round(100 - (example.ucp_tokens * 100 / example.raw_tokens)))
            : 0,
        });
        setStatus("Instant preview from curated benchmark · live API available for other public issues.", "ok");
      });
  }

  function loadLive(ref) {
    setLoading(true);
    setStatus("Fetching from GitHub and building package…");
    return fetch(demoApiUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: ref }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) {
            var detail = body.detail || body.title || "demo API error";
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
          }
          return body;
        });
      })
      .then(function (body) {
        renderPackage(body.package, body.stats);
        setStatus("Live package generated · " + (body.stats.comments_fetched || "?") + " comments fetched.", "ok");
      });
  }

  function run(ref) {
    var curated = curatedExample(ref);
    var chain = curated
      ? loadCurated(curated)
      : loadLive(ref);

    return chain.catch(function (err) {
      if (!curated) {
        setStatus(
          (err.message || "Generation failed") +
            " — try a curated example below, or run: ucp-gen github " + ref,
          "err"
        );
      } else {
        setStatus(err.message || "Failed to load example", "err");
      }
    }).finally(function () {
      setLoading(false);
    });
  }

  function renderPicks() {
    if (!manifest || !manifest.examples) return;
    picks.innerHTML = '<span class="try-picks-label">Try a famous thread:</span>';
    manifest.examples.forEach(function (ex) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "try-pick";
      btn.innerHTML = "<strong>" + escapeHtml(ex.label) + "</strong> <span>" + escapeHtml(ex.hint) + "</span>";
      btn.addEventListener("click", function () {
        input.value = ex.ref;
        run(ex.ref);
      });
      picks.appendChild(btn);
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var ref = normalizeRef(input.value);
    if (!ref) {
      setStatus("Enter a public GitHub issue URL or owner/repo#number.", "err");
      return;
    }
    input.value = ref;
    run(ref);
  });

  fetch("/try/data/index.json")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      manifest = data;
      renderPicks();
      var params = new URLSearchParams(location.search);
      var q = params.get("ref") || params.get("issue");
      if (q) {
        var ref = normalizeRef(q);
        if (ref) {
          input.value = ref;
          run(ref);
        }
      }
    })
    .catch(function () {
      setStatus("Could not load examples manifest.", "err");
    });
})();
