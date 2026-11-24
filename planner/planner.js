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
let size, camera, motion, selected, drag;
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
  return [data.width / 2, data.height / 2, Math.min(size.w / data.width, size.h * .88 / data.height) * .98];
}

function routeCamera() {
  const points = selected.chests;
  const xs = points.map(p => p[0]);
  const ys = points.map(p => p[1]);
  const left = Math.min(...xs), right = Math.max(...xs);
  const top = Math.min(...ys), bottom = Math.max(...ys);
  const scale = Math.min(size.w * .72 / (right - left + 80), size.h * .55 / (bottom - top + 80), overviewCamera()[2] * 4);
  return [(left + right) / 2, (top + bottom) / 2, scale];
}

function chestCamera(index) {
  const [x, y] = selected.chests[index];
  return [x, y, Math.min(size.w, size.h) / (data.width * .19)];
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

function busLine([a, b], color) {
  ctx.setLineDash([8, 8]);
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
      updateUI();
    }
  }
  ctx.fillStyle = "#101c2a";
  ctx.fillRect(0, 0, size.w, size.h);
  if (!ready) return;
  const [left, top] = screen([0, 0]);
  ctx.drawImage(map, left, top, data.width * camera[2], data.height * camera[2]);
  if (selected) {
    if (mode !== "fly") busLine(selected.bus, "#f8faffb0");
    const count = mode === "fly" ? revealed : selected.legs.length;
    const paths = selected.legs.slice(0, Math.ceil(count))
      .map((leg, i) => segment(leg.path, Math.min(1, count - i)));
    paths.forEach(path => line(path, "#15130def", 8));
    paths.forEach(path => line(path, gold, 4));
    const last = mode === "fly" ? Math.ceil(revealed) : selected.chests.length - 1;
    const active = mode === "fly" ? Math.round(revealed) : 0;
    const ground = selected.chests[active];
    if (!reducedMotion.matches) {
      const [x, y] = screen(ground);
      const pulse = (now % 1500) / 1500;
      circle(x, y, 15 + pulse * 23, "transparent", `rgba(255, 211, 83, ${(1 - pulse) * .65})`);
    }
    for (let i = last; i >= 0; i--) {
      if (i !== active) drawPin(i);
    }
    drawPin(active);
    if (mode !== "fly" || active === 0) drawLandingLabel();
  }
  if (drag) busLine([drag.start, drag.end], "#fff");
  if (motion || (selected && !reducedMotion.matches)) requestDraw();
}

function drawPin(index) {
  const [x, y] = screen(selected.chests[index]);
  const radius = mode === "fly" ? 12 : index === 0 ? 12 : 9;
  circle(x, y, radius, index === 0 ? red : gold, "#141519", 2.5);
  ctx.font = `850 ${mode === "fly" ? 12 : 10}px system-ui`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#17140d";
  ctx.fillText(index + 1, x, y + .5);
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
    ui.detail.textContent = `${Math.round(angle) % 360}° ${compass(angle)}  ·  about ${leg.meters} m  ·  about ${Math.round(leg.seconds)} s`;
  } else if (planned) {
    ui.detail.textContent = flying
      ? `Chest 1 / ${selected.chests.length}  ·  land on the red pin`
      : `${selected.chests.length} chest spots  ·  about ${clock(selected.seconds)} on the ground`;
  } else {
    ui.detail.textContent = ready ? "Drag a line across the island to find your drop." : "Loading map…";
  }
  ui.progress.hidden = !flying;
  if (planned) ui.fill.style.width = `${(step + 1) / selected.chests.length * 100}%`;
  ui.next.innerHTML = flying ? "Next chest <span>→</span>" : planned ? "Start flyover <span>→</span>" : "Try a sample bus <span>↗</span>";
  ui.next.disabled = !ready || Boolean(motion) || (flying && step === selected.chests.length - 1);
  ui.back.hidden = !flying;
  ui.back.disabled = step === 0 || Boolean(motion);
  ui.overview.hidden = !flying;
  ui.reset.hidden = !planned;
  ui.keys.textContent = planned ? "Space / → next  ·  ← back  ·  Esc overview" : "Drag from the bus entrance toward its exit.";
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

function selectRoute(route) {
  selected = route;
  activate("overview", 0, 770);
}

function next() {
  if (!ready || motion) return;
  if (!selected) {
    selectRoute(data.routes.find(route => route.heading === 90 && route.offset === 0));
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
  if (mode === "fly") activate("overview", 0, 820);
}

function reset() {
  selected = null;
  activate("plan", 0, 650);
}

canvas.addEventListener("pointerdown", event => {
  if (!ready || mode !== "plan" || motion || drag || event.button !== 0) return;
  const point = mapPoint(event);
  canvas.setPointerCapture(event.pointerId);
  drag = { id: event.pointerId, start: point, end: point };
  requestDraw();
});
canvas.addEventListener("pointermove", event => {
  if (drag?.id !== event.pointerId) return;
  drag.end = mapPoint(event);
  requestDraw();
});
canvas.addEventListener("pointerup", event => {
  if (drag?.id !== event.pointerId) return;
  const { start } = drag;
  const end = mapPoint(event);
  drag = null;
  if (distance(start, end) * camera[2] >= 22) selectRoute(nearestRoute(start, end));
  requestDraw();
});
canvas.addEventListener("lostpointercapture", () => { drag = null; requestDraw(); });

ui.next.onclick = next;
ui.back.onclick = back;
ui.overview.onclick = overview;
ui.reset.onclick = reset;

window.addEventListener("keydown", event => {
  if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.code === "Space" && event.target instanceof HTMLButtonElement) return;
  const action = { Space: next, ArrowRight: next, ArrowLeft: back, Escape: overview }[event.code];
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
  ui.version.textContent = `${data.version} · ${data.count} mapped spawns`;
  map.onload = () => { ready = true; updateUI(); requestDraw(); };
  map.onerror = () => { ui.detail.textContent = "Map asset failed to load. See the project README."; };
  new ResizeObserver(resize).observe(canvas);
  resize();
  map.src = "map.webp";
} else {
  ui.detail.textContent = "Route data is missing. Run the planner exporter.";
}
