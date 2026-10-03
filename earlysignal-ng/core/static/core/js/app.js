/* EarlySignal NG interface behaviour. No dependencies. */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const RISK_ICON = {
    High: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    Medium: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    Low: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  };
  const svg = (body, size) =>
    `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

  /* ---------- drawer (mobile navigation) ---------- */
  const sidebar = $("#sidebar");
  if (sidebar) {
    const scrim = $(".scrim");
    const opener = $("[data-drawer-open]");
    const setOpen = (open) => {
      sidebar.classList.toggle("is-open", open);
      scrim.hidden = !open;
      opener.setAttribute("aria-expanded", String(open));
      if (open) $(".sidebar-close", sidebar).focus();
      else opener.focus();
    };
    opener.addEventListener("click", () => setOpen(true));
    $$("[data-drawer-close]").forEach((b) => b.addEventListener("click", () => setOpen(false)));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && sidebar.classList.contains("is-open")) setOpen(false);
    });
  }

  /* ---------- toasts ---------- */
  $$(".toast").forEach((toast, i) => {
    const close = () => {
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), reduced ? 0 : 220);
    };
    $(".toast-x", toast).addEventListener("click", close);
    if (!toast.classList.contains("toast-error")) setTimeout(close, 5200 + i * 400);
  });

  /* ---------- stagger index for the page entrance ---------- */
  $$(".enter").forEach((group) =>
    Array.from(group.children).forEach((child, i) => child.style.setProperty("--i", Math.min(i, 8)))
  );

  /* ---------- blur-fade reveal ---------- */
  const revealables = $$("[data-reveal]");
  if (revealables.length) {
    if (reduced || !("IntersectionObserver" in window)) {
      revealables.forEach((el) => el.classList.add("is-in"));
    } else {
      const io = new IntersectionObserver(
        (entries) => entries.forEach((en) => {
          if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); }
        }),
        { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
      );
      revealables.forEach((el) => io.observe(el));
    }
  }

  /* ---------- spotlight: the glow follows the pointer ---------- */
  $$(".tile").forEach((tile) =>
    tile.addEventListener("pointermove", (e) => {
      const r = tile.getBoundingClientRect();
      tile.style.setProperty("--mx", e.clientX - r.left + "px");
      tile.style.setProperty("--my", e.clientY - r.top + "px");
    })
  );

  /* ---------- number ticker ---------- */
  const tween = (el, to, opts) => {
    const o = Object.assign({ from: 0, duration: 1100, decimals: 0 }, opts);
    const fmt = (v) => v.toLocaleString("en-NG", { minimumFractionDigits: o.decimals, maximumFractionDigits: o.decimals });
    if (reduced) { el.textContent = fmt(to); return; }
    const start = performance.now();
    cancelAnimationFrame(el._raf);
    const frame = (now) => {
      const t = Math.min((now - start) / o.duration, 1);
      const eased = 1 - Math.pow(1 - t, 4);
      el.textContent = fmt(o.from + (to - o.from) * eased);
      if (t < 1) el._raf = requestAnimationFrame(frame);
    };
    el._raf = requestAnimationFrame(frame);
  };
  const tickers = $$("[data-ticker]");
  if (tickers.length) {
    const run = (el) => tween(el, parseFloat(el.dataset.ticker), { decimals: parseInt(el.dataset.decimals || "0", 10) });
    if (!("IntersectionObserver" in window)) tickers.forEach(run);
    else {
      const io = new IntersectionObserver((entries) => entries.forEach((en) => {
        if (en.isIntersecting) { run(en.target); io.unobserve(en.target); }
      }), { threshold: 0.4 });
      tickers.forEach((el) => io.observe(el));
    }
  }

  /* ---------- gauge draw-in ---------- */
  $$(".gauge-fill[data-offset]").forEach((arc) => {
    requestAnimationFrame(() => requestAnimationFrame(() => { arc.style.strokeDashoffset = arc.dataset.offset; }));
  });

  /* ---------- live predictor (landing demo and what-if panel) ---------- */
  $$("[data-predictor]").forEach((root) => {
    const inputs = { ca: $('[data-input="ca"]', root), att: $('[data-input="att"]', root), gpa: $('[data-input="gpa"]', root) };
    const out = (name) => $(`[data-out="${name}"]`, root);
    const readout = $(".readout", root);
    let scale = parseFloat(root.dataset.scale || "4");
    let timer, controller, shown = 0;

    const paint = () => {
      Object.values(inputs).forEach((inp) => {
        const pct = ((inp.value - inp.min) / (inp.max - inp.min)) * 100;
        inp.style.setProperty("--fill", pct + "%");
      });
      out("ca").textContent = inputs.ca.value + "%";
      out("att").textContent = inputs.att.value + "%";
      out("gpa").textContent = parseFloat(inputs.gpa.value).toFixed(2) + " / " + scale.toFixed(2);
      const note = out("att-note");
      if (note) note.hidden = parseFloat(inputs.att.value) >= parseFloat(root.dataset.requirement || "75");
    };

    const render = (data) => {
      tween(out("percent"), data.percent, { from: shown, duration: 450 });
      shown = data.percent;
      readout.dataset.risk = data.risk.toLowerCase();
      const badge = out("badge");
      badge.className = "badge badge-" + data.risk.toLowerCase();
      badge.innerHTML = svg(RISK_ICON[data.risk], 14) + "<span>" + data.risk + " risk</span>";
      out("outcome").textContent = data.outcome + ".";
      const peak = Math.max.apply(null, data.factors.map((f) => Math.abs(f.points))) || 1;
      data.factors.forEach((f) => {
        const li = $(`[data-factor="${f.feature}"]`, root);
        if (!li) return;
        li.className = "factor " + f.direction;
        li.style.setProperty("--w", Math.max(Math.round((Math.abs(f.points) / peak) * 100), 3));
        const verb = f.direction === "raises" ? "raises risk by " : f.direction === "lowers" ? "lowers risk by " : "no real effect, ";
        $("em", li).textContent = verb + Math.abs(f.points).toFixed(1) + " pts";
      });
      const err = out("error");
      if (err) err.hidden = true;
      const caution = out("caution");
      if (caution) {
        caution.hidden = !(data.cautions && data.cautions.length);
        caution.textContent = (data.cautions || []).join(" ");
      }
    };

    const request = () => {
      if (controller) controller.abort();
      controller = new AbortController();
      const prev = (parseFloat(inputs.gpa.value) / scale) * 100;
      const url = `${root.dataset.url}?ca=${inputs.ca.value}&att=${inputs.att.value}&prev=${prev.toFixed(2)}`;
      root.classList.add("is-loading");
      fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } })
        .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          root.classList.remove("is-loading");
          if (!ok) throw new Error(d.error || "The model could not be reached.");
          render(d);
        })
        .catch((e) => {
          if (e.name === "AbortError") return;
          root.classList.remove("is-loading");
          const err = out("error");
          if (err) { err.textContent = e.message + " Check your connection and move a slider to try again."; err.hidden = false; }
        });
    };
    const schedule = () => { paint(); clearTimeout(timer); timer = setTimeout(request, 140); };

    Object.values(inputs).forEach((inp) => inp.addEventListener("input", schedule));
    $$('input[name="demo-scale"]', root).forEach((radio) =>
      radio.addEventListener("change", () => {
        const share = parseFloat(inputs.gpa.value) / scale;
        scale = parseFloat(radio.value);
        inputs.gpa.max = scale;
        inputs.gpa.value = (share * scale).toFixed(2);
        schedule();
      })
    );
    const reset = $("[data-reset]", root);
    if (reset) reset.addEventListener("click", () => {
      Object.values(inputs).forEach((inp) => { inp.value = inp.defaultValue; });
      schedule();
    });
    paint();
    request();
  });

  /* ---------- password show / hide ---------- */
  $$('input[type="password"]').forEach((input) => {
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "pw-toggle"; btn.textContent = "Show";
    btn.setAttribute("aria-label", "Show password");
    btn.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-label", (show ? "Hide" : "Show") + " password");
    });
    wrap.appendChild(btn);
  });

  /* ---------- busy state on submit ---------- */
  $$("form[data-busy]").forEach((form) =>
    form.addEventListener("submit", (e) => {
      const btn = e.submitter || $('button[type="submit"]', form);
      if (!btn) return;
      setTimeout(() => { btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true"); if (form.dataset.busy) btn.lastChild.textContent = form.dataset.busy; }, 0);
    })
  );

  /* ---------- confirm before destructive actions ---------- */
  $$("[data-confirm]").forEach((trigger) => {
    const dialog = document.getElementById(trigger.dataset.confirm);
    if (!dialog || !dialog.showModal) return;
    trigger.addEventListener("click", () => dialog.showModal());
    $$("[data-cancel]", dialog).forEach((b) => b.addEventListener("click", () => dialog.close()));
  });

  /* ---------- student form: institution drives type, state and levels ---------- */
  const lookupEl = document.getElementById("institution-lookup");
  if (lookupEl) {
    const lookup = JSON.parse(lookupEl.textContent);
    const levels = JSON.parse(document.getElementById("levels-by-type").textContent);
    const inst = $("#id_institution"), type = $("#id_institution_type"), state = $("#id_state"), level = $("#id_level");
    const syncLevels = () => {
      const allowed = levels[type.value] || [];
      const current = level.value;
      $$("option", level).forEach((o) => { if (o.value) { o.hidden = !allowed.includes(o.value); o.disabled = o.hidden; } });
      if (current && !allowed.includes(current)) level.value = "";
    };
    inst.addEventListener("change", () => {
      const hit = lookup[inst.value];
      if (hit) { type.value = hit.type; state.value = hit.state; syncLevels(); }
    });
    type.addEventListener("change", syncLevels);
    syncLevels();
  }

  /* ---------- demo credentials on the sign-in page ---------- */
  $$("[data-fill]").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("#id_username").value = btn.dataset.fill;
      $("#id_password").value = btn.dataset.pass;
      $("#id_password").focus();
    })
  );
})();
