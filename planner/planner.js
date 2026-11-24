"use strict";

const data = window.DROP_DATA;
const canvas = document.querySelector("#map");
const ctx = canvas.getContext("2d");
const ui = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map(element => [element.id, element])
);
const map = new Image();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const gold = "#ffd453";
const red = "#ff4e65";
let size, camera, motion, selected, drag, drawnBus, baseRoute;
let reliableMode = false;
let notice = "";
let landedAt = 0;
let displayedRoute;
let pinTargets = [];
const misses = new Set();
const chance = () => Number(ui.chance.value) / 100;
const skipped = point => loot && misses.has(loot.id(point));
const selectEnabled = () => Boolean(loot && selected);
let mode = "plan";
let step = 0;
let revealed = 0;
let ready = false;
let frame = 0;

const mix = (a, b, t) => a + (b - a) * t;
const ease = t => t * t * (3 - 2 * t);
const distance = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const heading = (a, b) => (Math.atan2(b[0] - a[0], a[1] - b[1]) * 180 / Math.PI + 360) % 360;
const compass = angle => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(angle / 45) % 8];
const clock = seconds => {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

function overviewCamera() {
  // The game raster includes open ocean beyond the island on every side.
  return [data.width * .53, data.height * .55,
    Math.min(size.w / (data.width * .74), size.h * .78 / (data.height * .69))];
}

function routeCamera() {
  const points = selected.chests;
  const xs = points.map(p => p[0]);
  const ys = points.map(p => p[1]);
  const left = Math.min(...xs), right = Math.max(...xs);
  const top = Math.min(...ys), bottom = Math.max(...ys);
  const scale = Math.min(size.w * .72 / (right - left + 80), size.h * .55 / (bottom - top + 80), overviewCamera()[2] * 5);
  return [(left + right) / 2, (top + bottom) / 2, scale];
}

function chestCamera(index) {
  const [x, y] = selected.chests[index];
  return [x, y, Math.min(size.w, size.h) / (data.width * .14)];
}

function destinationCamera() {
  if (mode === "fly") return chestCamera(step);
  if (mode === "overview") return routeCamera();
  return overviewCamera();
}

function screen(point) {
  return [
    (point[0] - camera[0]) * camera[2] + size.w / 2,
    (point[1] - camera[1]) * camera[2] + size.h * .45
  ];
}

function mapPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return [
    (event.clientX - rect.left - size.w / 2) / camera[2] + camera[0],
    (event.clientY - rect.top - size.h * .45) / camera[2] + camera[1]
  ];
}

function line(points, color, width) {
  if (points.length < 2) return;
  ctx.beginPath();
  points.forEach((p, i) => {
    const [x, y] = screen(p);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke();
}

function circle(x, y, radius, color, stroke, width = 2) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = width;
    ctx.stroke();
  }
}

function busLine([a, b], color, dashed = true) {
  ctx.setLineDash(dashed ? [8, 8] : []);
  line([a, b], "#0b1119b0", 6);
  line([a, b], color, 2);
  ctx.setLineDash([]);
  const tail = screen(a);
  const [x, y] = screen(b);
  const angle = Math.atan2(y - tail[1], x - tail[0]);
  circle(...tail, 4, color);
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(7, 0);
  ctx.lineTo(-6, -6);
  ctx.lineTo(-3, 0);
  ctx.lineTo(-6, 6);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

function segment(points, progress) {
  if (progress >= 1) return points;
  const lengths = points.slice(1).map((point, i) => distance(points[i], point));
  let remaining = lengths.reduce((a, b) => a + b, 0) * progress;
  const partial = [points[0]];
  for (let i = 0; i < lengths.length; i++) {
    if (remaining < lengths[i]) {
      partial.push(points[i].map((v, axis) => mix(v, points[i + 1][axis], remaining / lengths[i])));
      break;
    }
    remaining -= lengths[i];
    partial.push(points[i + 1]);
  }
  return partial;
}

function draw(now) {
  frame = 0;
  if (!size || !data) return;
  if (motion) {
    const t = ease(Math.min(1, (now - motion.start) / motion.duration));
    camera = motion.from.map((value, axis) => mix(value, motion.to[axis], t));
    revealed = mix(motion.oldReveal, motion.newReveal, t);
    if (t >= 1) {
      motion = null;
      landedAt = now;
      updateUI();
    }
  }
  ctx.fillStyle = "#101c2a";
  ctx.fillRect(0, 0, size.w, size.h);
  if (!ready) return;
  const [left, top] = screen([0, 0]);
  ctx.drawImage(map, left, top, data.width * camera[2], data.height * camera[2]);
  if (selected) {
    if (mode !== "fly" && drawnBus) {
      const actual = mode === "edit" && drag ? drag.ends : drawnBus;
      busLine(actual, "#60e2ff", false);
      const snap = mode === "edit" && drag && distance(...actual) * camera[2] >= 22
        ? nearestRoute(...actual).bus : selected.bus;
      busLine(snap, "#fff");
      if (mode === "edit") {
        actual.forEach((point, index) => {
          const [x, y] = screen(point);
          circle(x, y, 13, "#60e2ff", "#141519", 2.5);
          ctx.font = "850 10px system-ui";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillStyle = "#141519";
          ctx.fillText(index ? "END" : "IN", x, y);
        });
      }
    }
    const count = mode === "fly" ? revealed : selected.legs.length;
    const paths = selected.legs.slice(0, Math.ceil(count))
      .map((leg, i) => segment(leg.path, Math.min(1, count - i)));
    paths.forEach(path => line(path, "#15130def", 8));
    paths.forEach(path => line(path, gold, 4));
    if (mode === "fly" && count % 1 > 0) {
      const tip = paths.at(-1).at(-1);
      circle(...screen(tip), 4, "#fff2b2", "#15130d", 1.5);
    }
    const last = mode === "fly" ? Math.floor(revealed + 1e-6) : selected.chests.length - 1;
    const active = mode === "fly" ? last : 0;
    const ground = selected.chests[active];
    if (!motion && !reducedMotion.matches) {
      const [x, y] = screen(ground);
      const pulse = mode === "fly" && active > 0 ? Math.min(1, (now - landedAt) / 480) : (now % 1500) / 1500;
      if (pulse < 1) circle(x, y, 15 + pulse * 23, "transparent", `rgba(255, 211, 83, ${(1 - pulse) * .65})`);
    }
    drawPins(last, active);
    if (mode !== "fly" || active === 0) drawLandingLabel();
  }
  if (drag && mode === "plan") busLine(drag.ends, "#60e2ff", false);
  if (motion || (selected && !reducedMotion.matches)) requestDraw();
}

function drawPins(last, active) {
  const labeled = [active];
  if (active !== 0) labeled.push(0);
  for (let i = last; i >= 1; i--) {
    if (i === active) continue;
    const point = selected.chests[i];
    const overlaps = labeled.some(index => distance(point, selected.chests[index]) * camera[2] < 21);
    if (overlaps) circle(...screen(point), 3.5, skipped(point) ? "#8894a1" : gold, "#141519", 1.5);
    else labeled.push(i);
  }
  pinTargets = labeled.reverse();
  pinTargets.forEach(index => drawPin(index, index === active));
}

function drawPin(index, active) {
  const [x, y] = screen(selected.chests[index]);
  const radius = active || index === 0 ? 12 : 8;
  const empty = skipped(selected.chests[index]);
  circle(x, y, radius, empty ? "#8894a1" : index === 0 ? red : gold, "#141519", 2.5);
  ctx.font = `850 ${active ? 12 : 10}px system-ui`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#17140d";
  ctx.fillText(empty ? "×" : index + 1, x, y + .5);
}

function drawLandingLabel() {
  const [x, y] = screen(selected.chests[0]);
  ctx.font = "800 14px system-ui";
  const label = selected.name;
  const width = ctx.measureText(label).width + 20;
  const left = Math.max(7, Math.min(size.w - width - 7, x - width / 2));
  ctx.fillStyle = "#111925";
  ctx.fillRect(left, y - 44, width, 24);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "white";
  ctx.fillText(label, left + width / 2, y - 32);
}

function requestDraw() {
  if (!frame) frame = requestAnimationFrame(draw);
}

function activate(nextMode, nextStep, duration) {
  // The camera projection uses a fixed anchor so mode changes cannot jump a frame.
  mode = nextMode;
  step = nextStep;
  const target = destinationCamera();
  if (reducedMotion.matches) {
    motion = null;
    camera = target;
    revealed = step;
  } else {
    motion = {
      start: performance.now(), duration, from: camera.slice(), to: target,
      oldReveal: revealed, newReveal: step
    };
  }
  updateUI();
  requestDraw();
}

function updateUI() {
  const planned = Boolean(selected);
  const flying = mode === "fly";
  const leg = flying && step > 0 ? selected.legs[step - 1] : null;
  ui.phase.textContent = flying ? (step === 0 ? "LAND HERE" : "CHEST FLYOVER") : planned ? "RECOMMENDED DROP" : "BATTLE BUS";
  ui.title.textContent = flying && step > 0 ? `Chest ${step + 1} / ${selected.chests.length}` : planned ? selected.name : "Draw your bus path";
  if (leg) {
    const angle = heading(selected.chests[step - 1], selected.chests[step]);
    const meters = leg.meters ? `about ${leg.meters} m` : "under 1 m";
    const seconds = leg.seconds >= .5 ? `about ${Math.round(leg.seconds)} s` : "under 1 s";
    ui.detail.textContent = `${Math.round(angle) % 360}° ${compass(angle)}  ·  ${meters}  ·  ${seconds}`;
  } else if (planned) {
    ui.detail.textContent = flying
      ? `Chest 1 / ${selected.chests.length}  ·  land on the red pin`
      : `${selected.chests.length} chest spots  ·  about ${clock(selected.seconds)} on the ground`;
  } else {
    ui.detail.textContent = ready ? "Drag a line across the island to find your drop." : "Loading map…";
  }
  if (mode === "edit") {
    ui.phase.textContent = "BATTLE BUS";
    ui.title.textContent = "Adjust your bus path";
    ui.detail.textContent = "Drag either blue handle to update the route.";
  }
  const options = selectEnabled();
  ui.routeTools.hidden = !options || mode === "edit";
  ui.yield.hidden = !options;
  ui.notice.hidden = !notice;
  ui.notice.textContent = notice;
  ui.reliability.textContent = reliableMode ? "Reliable loot on" : "Reliable loot";
  ui.reliability.setAttribute("aria-pressed", reliableMode);
  ui.reliability.disabled = Boolean(motion) || misses.size > 0;
  ui.chanceRow.hidden = !options || !reliableMode || mode === "edit";
  ui.chance.disabled = Boolean(motion) || misses.size > 0;
  ui.chanceValue.value = `${ui.chance.value}%`;
  if (options) {
    const stops = selected.chests.filter(point => !skipped(point));
    const guaranteed = stops.filter(point => loot.isGuaranteed(loot.id(point))).length;
    const expected = guaranteed + (stops.length - guaranteed) * chance();
    ui.yield.textContent = `${guaranteed} guaranteed · about ${expected.toFixed(1)} expected chests`;
    if (displayedRoute !== selected) {
      ui.jump.replaceChildren(new Option("Select chest", ""), ...selected.chests.map((point, i) =>
        new Option(`Chest ${i + 1}${skipped(point) ? " · empty" : ""}`, String(i))));
      displayedRoute = selected;
    }
    ui.jump.value = flying ? String(step) : "";
    ui.jump.disabled = Boolean(motion);
  }
  ui.progress.hidden = !flying;
  if (planned) ui.fill.style.width = `${(step + 1) / selected.chests.length * 100}%`;
  ui.next.innerHTML = mode === "edit" ? "Done <span>✓</span>" : flying ? "Next chest <span>→</span>"
    : planned ? "Start flyover <span>→</span>" : "Try a sample bus <span>↗</span>";
  ui.next.disabled = !ready || Boolean(motion) || (flying && step === selected.chests.length - 1);
  ui.back.hidden = !flying;
  ui.back.disabled = step === 0 || Boolean(motion);
  ui.overview.hidden = !flying;
  ui.reset.hidden = !planned;
  ui.edit.hidden = mode !== "overview";
  ui.edit.disabled = Boolean(motion);
  ui.skip.hidden = !flying || !options;
  ui.skip.disabled = !flying || Boolean(motion) || selected.chests.slice(step).some(skipped);
  ui.busLegend.hidden = mode === "fly" || !drawnBus;
  ui.keys.textContent = mode === "edit" ? "Move either end. Select Done to preview the route."
    : flying ? "Space / → next  ·  ← back  ·  X empty  ·  Esc overview"
    : planned ? "Select a pin to jump to that chest." : "Drag from the bus entrance toward its exit.";
}

function nearestRoute(a, b) {
  const angle = heading(a, b);
  const canonical = Math.round(angle / data.headingStep) * data.headingStep % 360;
  const radians = canonical * Math.PI / 180;
  const midpoint = a.map((v, i) => (v + b[i]) / 2);
  const offset = (midpoint[0] - data.width / 2) * Math.cos(radians) +
    (midpoint[1] - data.height / 2) * Math.sin(radians);
  return data.routes.filter(route => route.heading === canonical)
    .reduce((best, route) => Math.abs(route.offset - offset) < Math.abs(best.offset - offset) ? route : best);
}

function selectRoute(route, actual, nextMode = "overview") {
  baseRoute = route;
  drawnBus = actual;
  misses.clear();
  notice = "";
  selected = reliableMode ? loot.reliable(baseRoute, chance()) : baseRoute;
  if (nextMode === "edit") {
    updateUI();
    requestDraw();
  } else {
    activate(nextMode, 0, 770);
  }
}

function updateReliability() {
  if (!baseRoute || !loot || misses.size || motion) return;
  selected = reliableMode ? loot.reliable(baseRoute, chance()) : baseRoute;
  if (mode === "overview" || step === 0) activate(mode, 0, 650);
  else activate("fly", 0, 650);
}

function jumpTo(index) {
  if (!selected || motion || mode === "edit" || !Number.isInteger(index) || !selected.chests[index]) return;
  if (mode !== "fly" || step !== index) activate("fly", index, 900);
}

function skipChest() {
  if (ui.skip.hidden || ui.skip.disabled) return;
  misses.add(loot.id(selected.chests[step]));
  selected = loot.replan(selected, step, misses, reliableMode ? chance() : 1);
  notice = step + 1 < selected.chests.length ? "Empty chest marked. Remaining route updated."
    : "Empty chest marked. No more stops fit the estimated time.";
  updateUI();
  requestDraw();
}

function next() {
  if (!ready || motion) return;
  if (!selected) {
    const sample = data.routes.find(route => route.heading === 300 && route.offset === -240);
    const [a, b] = sample.bus;
    selectRoute(sample, [.27, .73].map(t => a.map((x, i) => mix(x, b[i], t))));
  } else if (mode === "edit") {
    activate("overview", 0, 730);
  } else if (mode !== "fly") {
    activate("fly", 0, 900);
  } else if (step < selected.chests.length - 1) {
    activate("fly", step + 1, 960);
  }
}

function back() {
  if (mode === "fly" && step > 0 && !motion) activate("fly", step - 1, 960);
}

function overview() {
  if (mode === "fly" || mode === "edit") activate("overview", 0, 820);
}

function reset() {
  selected = baseRoute = drawnBus = null;
  misses.clear();
  notice = "";
  activate("plan", 0, 650);
}

canvas.addEventListener("pointerdown", event => {
  if (!ready || motion || drag || event.button !== 0) return;
  const point = mapPoint(event);
  const near = (target, radius) => distance(point, target) * camera[2] < radius;
  if (mode === "overview" || mode === "fly") {
    const pin = pinTargets.slice().reverse().find(i => near(selected.chests[i], 13));
    if (pin !== undefined) jumpTo(pin);
    return;
  }
  const handle = mode === "edit" ? drawnBus.findIndex(end => near(end, 26)) : 1;
  if (handle < 0) return;
  canvas.setPointerCapture(event.pointerId);
  drag = { id: event.pointerId, handle, ends: mode === "edit" ? drawnBus.slice() : [point, point] };
  requestDraw();
});
canvas.addEventListener("pointermove", event => {
  if (drag?.id !== event.pointerId) return;
  drag.ends[drag.handle] = mapPoint(event);
  requestDraw();
});
canvas.addEventListener("pointerup", event => {
  if (drag?.id !== event.pointerId) return;
  drag.ends[drag.handle] = mapPoint(event);
  const ends = drag.ends;
  drag = null;
  if (distance(...ends) * camera[2] >= 22) selectRoute(nearestRoute(...ends), ends, mode === "edit" ? "edit" : "overview");
  requestDraw();
});
canvas.addEventListener("lostpointercapture", () => { drag = null; requestDraw(); });

ui.next.onclick = next;
ui.back.onclick = back;
ui.overview.onclick = overview;
ui.reset.onclick = reset;
ui.edit.onclick = () => activate("edit", 0, 730);
ui.skip.onclick = skipChest;
ui.jump.onchange = () => { if (ui.jump.value !== "") jumpTo(Number(ui.jump.value)); };
ui.reliability.onclick = () => { reliableMode = !reliableMode; updateReliability(); };
ui.chance.oninput = () => { ui.chanceValue.value = `${ui.chance.value}%`; };
ui.chance.onchange = updateReliability;

window.addEventListener("keydown", event => {
  if (event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.target.matches?.("input, select")) return;
  if (event.code === "Space" && event.target instanceof HTMLButtonElement) return;
  const action = { Space: next, ArrowRight: next, ArrowLeft: back, Escape: overview, KeyX: skipChest }[event.code];
  if (action) {
    event.preventDefault();
    action();
  }
});

function resize() {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  size = { w: canvas.clientWidth, h: canvas.clientHeight };
  canvas.width = Math.round(size.w * dpr);
  canvas.height = Math.round(size.h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (data) {
    camera = destinationCamera();
    motion = null;
    revealed = step;
    updateUI();
  }
  requestDraw();
}

if (data) {
  ui.version.textContent = `${data.version} · ${data.count} standard spots`;
  map.onload = () => { ready = true; updateUI(); requestDraw(); };
  map.onerror = () => { ui.detail.textContent = "Map asset failed to load. See the project README."; };
  new ResizeObserver(resize).observe(canvas);
  resize();
  map.src = "map.webp";
} else {
  ui.detail.textContent = "Route data is missing. Run the planner exporter.";
}
