// Small UI helpers: toast, bottom sheets (closed by the phone's back button), image viewer, crop box.
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let toastTimer = 0;
export function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// -- overlays (sheets, viewer) form a stack; Android's back button closes the top one ----------------
const stack = [];
export const overlayCount = () => stack.length;
export function pushOverlay(nodes, onClose) {
  stack.push({ nodes, onClose });
  history.pushState({ overlay: stack.length }, "");
}
/** Remove the top overlay without touching browser history (used by popstate). */
export function popOverlay() {
  const o = stack.pop();
  if (!o) return false;
  o.nodes.forEach((n) => n.remove());
  o.onClose && o.onClose();
  return true;
}
export function closeTop() { if (stack.length) history.back(); }

/** Open a bottom sheet. Returns {sheet, body, foot, close}. */
export function openSheet(title, html = "", { full = false, onClose = null } = {}) {
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  const sheet = document.createElement("div");
  sheet.className = "sheet" + (full ? " full" : "");
  sheet.innerHTML = `<div class="grab"></div><div class="sh"><h3></h3><button class="icon-btn" data-close>✕</button></div>` +
    `<div class="sb"></div><div class="sf"></div>`;
  $("h3", sheet).textContent = title;
  $(".sb", sheet).innerHTML = html;
  document.body.append(scrim, sheet);
  scrim.addEventListener("click", closeTop);
  $("[data-close]", sheet).addEventListener("click", closeTop);
  // swipe the grab handle down to close
  let y0 = null;
  const grab = $(".grab", sheet), head = $(".sh", sheet);
  for (const el of [grab, head]) {
    el.addEventListener("touchstart", (e) => { y0 = e.touches[0].clientY; }, { passive: true });
    el.addEventListener("touchmove", (e) => {
      if (y0 === null) return;
      const dy = Math.max(0, e.touches[0].clientY - y0);
      sheet.style.transition = "none"; sheet.style.transform = `translateY(${dy}px)`;
    }, { passive: true });
    el.addEventListener("touchend", (e) => {
      if (y0 === null) return;
      const dy = e.changedTouches[0].clientY - y0;
      y0 = null; sheet.style.transition = ""; sheet.style.transform = "";
      if (dy > 90) closeTop();
    });
  }
  pushOverlay([scrim, sheet], onClose);
  return { sheet, body: $(".sb", sheet), foot: $(".sf", sheet), close: closeTop };
}

/** Full-screen image with pinch-zoom and drag. */
export function openViewer(src) {
  const v = document.createElement("div");
  v.className = "viewer";
  v.innerHTML = `<button class="icon-btn close">✕</button><img alt="">`;
  const img = $("img", v);
  document.body.append(v);
  $(".close", v).addEventListener("click", closeTop);
  let s = 1, x = 0, y = 0;
  const apply = () => { img.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
  img.onload = () => {
    s = Math.min(innerWidth / img.naturalWidth, innerHeight / img.naturalHeight);
    x = (innerWidth - img.naturalWidth * s) / 2; y = (innerHeight - img.naturalHeight * s) / 2; apply();
  };
  img.src = src;
  const pts = new Map();
  let last = null;
  v.addEventListener("pointerdown", (e) => { pts.set(e.pointerId, [e.clientX, e.clientY]); v.setPointerCapture(e.pointerId); last = null; });
  v.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    const p = [...pts.values()];
    const cx = p.reduce((a, q) => a + q[0], 0) / p.length, cy = p.reduce((a, q) => a + q[1], 0) / p.length;
    const d = p.length > 1 ? Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]) : 0;
    if (last && last.n === p.length) {
      const k = d && last.d ? d / last.d : 1;
      x = cx - (last.cx - x) * k; y = cy - (last.cy - y) * k; s *= k; apply();
    }
    last = { cx, cy, d, n: p.length };
  });
  const up = (e) => { pts.delete(e.pointerId); last = null; };
  v.addEventListener("pointerup", up); v.addEventListener("pointercancel", up);
  v.addEventListener("wheel", (e) => {
    e.preventDefault();
    const k = Math.exp(-e.deltaY / 400);
    x = e.clientX - (e.clientX - x) * k; y = e.clientY - (e.clientY - y) * k; s *= k; apply();
  }, { passive: false });
  pushOverlay([v]);
}

/** Crop box on an <img>. Calls onChange(hasBox). Returns {get() -> natural-pixel rect or null, reset()} */
export function cropper(stage, img, box, onChange) {
  let r = null, mode = null, start = null, orig = null;
  const draw = () => {
    box.hidden = !r;
    if (r) Object.assign(box.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
    onChange(!!r && r.w > 12 && r.h > 12);
  };
  const pos = (e) => {
    const b = img.getBoundingClientRect();
    return [Math.max(0, Math.min(b.width, e.clientX - b.left)), Math.max(0, Math.min(b.height, e.clientY - b.top))];
  };
  stage.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    stage.setPointerCapture(e.pointerId);
    const [px, py] = pos(e);
    start = [px, py]; orig = r && { ...r };
    const h = e.target.dataset && e.target.dataset.h;
    if (h && r) mode = h;
    else if (r && px > r.x && px < r.x + r.w && py > r.y && py < r.y + r.h) mode = "move";
    else { mode = "new"; r = { x: px, y: py, w: 0, h: 0 }; }
    draw();
  });
  stage.addEventListener("pointermove", (e) => {
    if (!mode) return;
    const [px, py] = pos(e);
    const b = img.getBoundingClientRect();
    if (mode === "new") {
      r = { x: Math.min(px, start[0]), y: Math.min(py, start[1]), w: Math.abs(px - start[0]), h: Math.abs(py - start[1]) };
    } else if (mode === "move") {
      r.x = Math.max(0, Math.min(b.width - orig.w, orig.x + px - start[0]));
      r.y = Math.max(0, Math.min(b.height - orig.h, orig.y + py - start[1]));
    } else {
      let x1 = orig.x, y1 = orig.y, x2 = orig.x + orig.w, y2 = orig.y + orig.h;
      if (mode.includes("l")) x1 = px; if (mode.includes("r")) x2 = px;
      if (mode.includes("t")) y1 = py; if (mode.includes("b")) y2 = py;
      r = { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
    }
    draw();
  });
  const end = () => { if (mode === "new" && r && (r.w < 12 || r.h < 12)) r = null; mode = null; draw(); };
  stage.addEventListener("pointerup", end); stage.addEventListener("pointercancel", end);
  return {
    get() {
      if (!r || r.w < 12 || r.h < 12) return null;
      const k = img.naturalWidth / img.getBoundingClientRect().width;
      return { x: Math.round(r.x * k), y: Math.round(r.y * k), w: Math.round(r.w * k), h: Math.round(r.h * k) };
    },
    reset() { r = null; draw(); },
  };
}

/** Long-press helper: calls onLong after 450 ms; returns a function telling whether the last press was long. */
export function onLongPress(el, onLong) {
  let timer = 0, long = false;
  el.addEventListener("pointerdown", (e) => {
    long = false;
    timer = setTimeout(() => { long = true; onLong(e); }, 450);
  });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) el.addEventListener(ev, () => clearTimeout(timer));
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  return () => long;
}
