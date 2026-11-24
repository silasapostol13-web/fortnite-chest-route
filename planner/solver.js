"use strict";

// The exported matrix supplies the same walk costs as the Python route model.
const loot = (() => {
  const network = window.DROP_NETWORK;
  if (!network) return null;
  const { stops, cols, cell, meter, run, swim, stop } = network;
  const bytes = value => Uint8Array.from(atob(value), char => char.charCodeAt(0));
  const times = new DataView(bytes(network.times).buffer);
  const water = bytes(network.water);
  const rows = water.length / cols;
  const count = stops.length;
  const byPoint = new Map(stops.map(([x, y], i) => [`${x},${y}`, i]));
  const travelTime = (a, b) => times.getUint16((a * count + b) * 2, true) / 100;
  const point = i => stops[i].slice(0, 2);
  const id = ([x, y]) => byPoint.get(`${x},${y}`);
  const isGuaranteed = i => stops[i][3];

  function budget(bus, i) {
    const [[x, y], [ex, ey]] = bus;
    const [dx, dy] = [ex - x, ey - y];
    const length = Math.hypot(dx, dy);
    const [px, py] = [stops[i][0] - x, stops[i][1] - y];
    const along = (px * dx + py * dy) * meter / length;
    const side = Math.abs(px * dy - py * dx) * meter / length;
    const ratio = network.glide / network.busSpeed;
    const lead = ratio * side / Math.sqrt(1 - ratio * ratio);
    const jump = Math.min(Math.max(along - lead, 0), length * meter);
    const glide = Math.hypot(along - jump, side);
    if (glide > network.reach) return 0;
    return network.storm - jump / network.busSpeed - network.fall - glide / network.glide;
  }

  function greedy(start, available, excluded, chance, costFloor) {
    const seen = new Set(excluded);
    const route = [];
    let reward = 0;
    let seconds = 0;
    let current = start;
    seen.add(start);
    while (available - seconds >= stop) {
      let best = -1;
      let bestScore = 0;
      let cost = 0;
      for (let i = 0; i < count; i++) {
        if (seen.has(i)) continue;
        const elapsed = travelTime(current, i) + stop;
        if (seconds + elapsed > available) continue;
        const score = (isGuaranteed(i) ? 1 : chance) / (elapsed + costFloor);
        if (score > bestScore) {
          best = i;
          bestScore = score;
          cost = elapsed;
        }
      }
      if (best < 0) break;
      route.push(best);
      seen.add(best);
      reward += isGuaranteed(best) ? 1 : chance;
      seconds += cost;
      current = best;
    }
    return { route, seconds, reward };
  }

  function better(candidate, incumbent) {
    if (!incumbent) return true;
    if (Math.abs(candidate.reward - incumbent.reward) > 1e-8) return candidate.reward > incumbent.reward;
    if (candidate.route.length !== incumbent.route.length) return candidate.route.length > incumbent.route.length;
    return candidate.seconds < incumbent.seconds;
  }

  function polish(candidate, timeLimit, chance, excluded = new Set()) {
    const opensStart = !excluded.has(candidate.route[0]);
    const weight = i => excluded.has(i) ? 0 : isGuaranteed(i) ? 1 : chance;
    const pool = stops.map((_, i) => i).filter(i =>
      weight(i) > 0 && candidate.route.some(j => travelTime(j, i) <= 9));
    const total = route => route.reduce((seconds, i, j) =>
      seconds + (j || opensStart ? stop : 0) + (j ? travelTime(route[j - 1], i) : 0), 0);

    function refill(route) {
      let seconds = total(route);
      const used = new Set(route);
      while (seconds + stop <= timeLimit) {
        let insertion;
        for (const i of pool) {
          if (used.has(i)) continue;
          for (let j = 1; j <= route.length; j++) {
            const a = route[j - 1], b = route[j];
            const cost = stop + travelTime(a, i) + (b === undefined ? 0 : travelTime(i, b) - travelTime(a, b));
            if (seconds + cost > timeLimit) continue;
            const score = weight(i) / Math.max(1, cost);
            if (!insertion || score > insertion.score) insertion = { i, j, cost, score };
          }
        }
        if (!insertion) break;
        route.splice(insertion.j, 0, insertion.i);
        used.add(insertion.i);
        seconds += insertion.cost;
      }
      return { route, seconds, reward: route.reduce((sum, i) => sum + weight(i), 0) };
    }

    let best = candidate;
    const filled = refill(candidate.route.slice());
    if (filled.seconds <= timeLimit && better(filled, best)) best = filled;
    for (const width of [1, 2, 3]) {
      const reference = best.route;
      for (let start = 1; start < reference.length; start++) {
        const removed = reference.slice(start, start + width);
        if (removed.every(isGuaranteed)) continue;
        const trial = refill([...reference.slice(0, start), ...reference.slice(start + width)]);
        if (trial.seconds <= timeLimit && better(trial, best)) best = trial;
      }
    }
    return best;
  }

  function offBus(bus, i) {
    const [[x, y], [ex, ey]] = bus;
    const dx = ex - x, dy = ey - y;
    const [px, py] = [stops[i][0] - x, stops[i][1] - y];
    return Math.abs(px * dy - py * dx) * meter / Math.hypot(dx, dy);
  }

  function planFrom(base, chance, drawnBus, style = "quiet") {
    // Include the original recommendation as a candidate, so the weighted
    // heuristic cannot lower expected yield for the selected bus.
    const original = base.chests.map(id);
    let best = {
      route: original,
      seconds: base.seconds,
      reward: original.reduce((total, i) => total + (isGuaranteed(i) ? 1 : chance), 0),
    };
    const candidates = [best];
    for (let i = 0; i < count; i++) {
      const available = budget(base.bus, i) - stop;
      if (available < 0) continue;
      const candidate = greedy(i, available, [], chance, 1);
      candidate.route.unshift(i);
      candidate.reward += isGuaranteed(i) ? 1 : chance;
      candidate.seconds += stop;
      if (drawnBus) candidates.push(candidate);
      if (better(candidate, best)) best = candidate;
    }
    for (const floor of [0, 4, 9]) {
      const start = best.route[0];
      const candidate = greedy(start, budget(base.bus, start) - stop, [], chance, floor);
      candidate.route.unshift(start);
      candidate.reward += isGuaranteed(start) ? 1 : chance;
      candidate.seconds += stop;
      if (better(candidate, best)) best = candidate;
    }
    best = polish(best, budget(base.bus, best.route[0]), chance);
    if (drawnBus) {
      // Keep good loot routes, favoring distance within the modeled glide range.
      const reachable = [...candidates, best].filter(candidate =>
        offBus(drawnBus, candidate.route[0]) <= network.reach);
      const floor = Math.max(...reachable.map(candidate => candidate.reward)) * .85;
      const choices = reachable.filter(candidate => candidate.reward + 1e-8 >= floor);
      const direction = style === "hot" ? -1 : 1;
      const preferred = choices.reduce((current, candidate) => {
        if (!current) return candidate;
        const delta = direction * (offBus(drawnBus, candidate.route[0]) - offBus(drawnBus, current.route[0]));
        return delta > .01 || (Math.abs(delta) <= .01 && better(candidate, current)) ? candidate : current;
      }, null);
      if (preferred) best = polish(preferred, budget(base.bus, preferred.route[0]), chance);
    }
    if (best.route.length === original.length && best.route.every((i, index) => i === original[index])) return base;
    return {
      ...base,
      name: stops[best.route[0]][2],
      chests: best.route.map(point),
      seconds: best.seconds,
      legs: best.route.slice(1).map((i, index) => leg(best.route[index], i)),
    };
  }

  function replan(route, current, misses, chance) {
    const prefix = route.chests.slice(0, current + 1).map(id);
    const priorLegs = route.legs.slice(0, current);
    const consumed = priorLegs.reduce((total, item) => total + item.seconds, 0)
      + prefix.filter(i => !misses.has(i)).length * stop;
    const tailBudget = budget(route.bus, prefix[0]) - consumed;
    const oldTail = route.chests.slice(current + 1).map(id);
    const oldSeconds = route.legs.slice(current).reduce((total, leg) => total + leg.seconds + stop, 0);
    let best = oldSeconds <= tailBudget ? {
      route: oldTail,
      seconds: oldSeconds,
      reward: oldTail.reduce((total, i) => total + (isGuaranteed(i) ? 1 : chance), 0),
    } : null;
    for (const floor of [0, 1, 4, 9]) {
      const candidate = greedy(prefix.at(-1), tailBudget, [...prefix, ...misses], chance, floor);
      if (better(candidate, best)) best = candidate;
    }
    const optimized = polish(
      { ...best, route: [prefix.at(-1), ...best.route] },
      tailBudget, chance, new Set([...prefix, ...misses])
    );
    const indices = [...prefix, ...optimized.route.slice(1)];
    return {
      ...route,
      chests: indices.map(point),
      seconds: consumed + optimized.seconds,
      legs: [...priorLegs, ...optimized.route.slice(1).map((i, index) => leg(indices[current + index], i))],
    };
  }

  function gridPath(start, end) {
    const key = ([x, y]) => Math.floor(y / cell) * cols + Math.floor(x / cell);
    const source = key(start), target = key(end);
    if (source === target) return [start, end];
    const tx = target % cols, ty = Math.floor(target / cols);
    const heuristic = at => Math.hypot(tx - at % cols, ty - Math.floor(at / cols)) * cell * meter / run;
    const previous = new Int32Array(water.length).fill(-1);
    const scores = new Float64Array(water.length).fill(Infinity);
    scores[source] = 0;
    const heap = [];
    function push(entry) {
      let index = heap.length;
      while (index > 0) {
        const parent = (index - 1) >> 1;
        if (heap[parent][0] <= entry[0]) break;
        heap[index] = heap[parent];
        index = parent;
      }
      heap[index] = entry;
    }
    function pop() {
      const first = heap[0], last = heap.pop();
      if (!heap.length) return first;
      let index = 0;
      while (index * 2 + 1 < heap.length) {
        let child = index * 2 + 1;
        if (child + 1 < heap.length && heap[child + 1][0] < heap[child][0]) child++;
        if (heap[child][0] >= last[0]) break;
        heap[index] = heap[child];
        index = child;
      }
      heap[index] = last;
      return first;
    }
    push([heuristic(source), source, 0]);
    const pace = at => 1 / (water[at] ? swim : run);
    while (heap.length) {
      const [, at, traveled] = pop();
      if (at === target) break;
      if (traveled > scores[at]) continue;
      const x = at % cols, y = Math.floor(at / cols);
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if ((!dx && !dy) || x + dx < 0 || x + dx >= cols || y + dy < 0 || y + dy >= rows) continue;
          const next = at + dx + dy * cols;
          const cost = traveled + Math.hypot(dx, dy) * cell * meter * (pace(at) + pace(next)) / 2;
          if (cost >= scores[next]) continue;
          scores[next] = cost;
          previous[next] = at;
          push([cost + heuristic(next), next, cost]);
        }
      }
    }
    const route = [];
    for (let at = previous[target]; at !== source && at !== -1; at = previous[at]) {
      route.push([(at % cols + .5) * cell, (Math.floor(at / cols) + .5) * cell]);
    }
    return [start, ...route.reverse(), end];
  }

  function leg(a, b) {
    const path = gridPath(point(a), point(b));
    let meters = 0;
    for (let i = 1; i < path.length; i++) {
      meters += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]) * meter;
    }
    return { path, meters: Math.round(meters), seconds: travelTime(a, b) };
  }

  return { planFrom, offBus, replan, id, isGuaranteed };
})();
