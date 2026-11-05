// Route map on the run detail page: the simplified track over OpenStreetMap
// tiles. No map library: Web Mercator maths, one <img> per tile and an SVG
// overlay for the line. Tiles come from tile.openstreetmap.org, so the tile
// server sees which area is shown; the coordinates themselves stay in the page.

import { h } from "./dom.js";
import { svgEl } from "./svg.js";

export const TILE = 256;
export const MIN_ZOOM = 3;
export const MAX_ZOOM = 18;
const HEIGHT = 420;
const PAD = 32; // room around the fitted route, in pixels
const SCALE_PX = 110; // the scale bar is at most this long
const EARTH_RADIUS_M = 6378137; // Web Mercator sphere
const tileUrl = (z, x, y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;

/** World pixel position [x, y] of (lat, lon) at zoom z (Web Mercator). */
export function worldPx(lat, lon, z) {
  const size = TILE * 2 ** z;
  const s = Math.sin((lat * Math.PI) / 180);
  return [((lon + 180) / 360) * size, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size];
}

/** The largest zoom at which the bounding box fits in w × h less the padding. */
export function fitZoom(lats, lons, w, h, pad = PAD) {
  const [south, north] = [Math.min(...lats), Math.max(...lats)];
  const [west, east] = [Math.min(...lons), Math.max(...lons)];
  for (let z = MAX_ZOOM; z > MIN_ZOOM; z--) {
    const [x0, y0] = worldPx(north, west, z);
    const [x1, y1] = worldPx(south, east, z);
    if (x1 - x0 <= w - 2 * pad && y1 - y0 <= h - 2 * pad) return z;
  }
  return MIN_ZOOM;
}

/** Tiles covering a w × h view whose top-left world pixel is (left, top).
 * `col` is the unwrapped column; `x` wraps round the antimeridian. */
export function tilesFor(left, top, w, h, z) {
  const n = 2 ** z;
  const out = [];
  for (let row = Math.floor(top / TILE); row * TILE < top + h; row++) {
    if (row < 0 || row >= n) continue;
    for (let col = Math.floor(left / TILE); col * TILE < left + w; col++) {
      out.push({ z, col, x: ((col % n) + n) % n, y: row, left: col * TILE - left, top: row * TILE - top });
    }
  }
  return out;
}

/** Metres on the ground per screen pixel at latitude `lat` and zoom z. */
export function metresPerPx(lat, z) {
  return (2 * Math.PI * EARTH_RADIUS_M * Math.cos((lat * Math.PI) / 180)) / (TILE * 2 ** z);
}

/** The longest 1-2-5 length in metres that fits in `maxM`. */
export function scaleLength(maxM) {
  const mag = 10 ** Math.floor(Math.log10(maxM));
  for (const m of [5, 2, 1]) if (m * mag <= maxM) return m * mag;
  return mag;
}

const fmtLength = (m) => (m >= 1000 ? `${m / 1000} km` : `${m} m`);

/** The map element for a `route` from the API (needs `lat`, `lon`,
 * `start_index`, `finish_index`). It draws itself once it has a width. */
export function routeMap(r) {
  const tiles = h("div", { class: "route-tiles" });
  const overlay = svgEl("svg", { class: "route-overlay", "aria-hidden": "true" });
  const bar = h("span", { class: "route-scalebar" });
  const barText = h("span", { class: "num" });
  const button = (label, title, onClick) => {
    const b = h("button", { type: "button", title, "aria-label": title }, label);
    b.addEventListener("click", onClick);
    return b;
  };
  const box = h("div", { class: "route-map", role: "img", "aria-label": "路线地图" },
    tiles,
    overlay,
    h("div", { class: "route-controls" },
      button("+", "放大", () => zoomAt(1)),
      button("−", "缩小", () => zoomAt(-1)),
      button("全程", "回到整条路线", () => { fit(); draw(); }),
    ),
    h("div", { class: "route-scale" }, bar, barText),
    h("div", { class: "route-attrib" },
      "© ",
      h("a", { href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener" },
        "OpenStreetMap"),
      " contributors"),
  );

  let W = 0;
  let view = null; // { z, cx, cy }: zoom and the centre in world pixels
  const imgs = new Map(); // "z/col/row" -> <img>
  const midLat = (Math.min(...r.lat) + Math.max(...r.lat)) / 2;

  function fit() {
    const z = fitZoom(r.lat, r.lon, W, HEIGHT);
    const [x0, y0] = worldPx(Math.max(...r.lat), Math.min(...r.lon), z);
    const [x1, y1] = worldPx(Math.min(...r.lat), Math.max(...r.lon), z);
    view = { z, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  }

  /** Zoom by `dz` keeping the world point under (ox, oy) in place; the view centre by default. */
  function zoomAt(dz, ox = W / 2, oy = HEIGHT / 2) {
    const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.z + dz));
    const k = 2 ** (z - view.z);
    const px = view.cx - W / 2 + ox;
    const py = view.cy - HEIGHT / 2 + oy;
    view = { z, cx: px * k - ox + W / 2, cy: py * k - oy + HEIGHT / 2 };
    draw();
  }

  function draw() {
    const { z, cx, cy } = view;
    const left = cx - W / 2;
    const top = cy - HEIGHT / 2;

    const wanted = new Set();
    for (const t of tilesFor(left, top, W, HEIGHT, z)) {
      const key = `${t.z}/${t.col}/${t.y}`;
      wanted.add(key);
      let img = imgs.get(key);
      if (!img) {
        img = h("img", { src: tileUrl(t.z, t.x, t.y), alt: "", width: TILE, height: TILE, draggable: "false" });
        img.addEventListener("error", () => img.classList.add("missing"));
        imgs.set(key, img);
        tiles.append(img);
      }
      img.style.transform = `translate(${t.left}px, ${t.top}px)`;
    }
    for (const [key, img] of imgs) {
      if (!wanted.has(key)) {
        img.remove();
        imgs.delete(key);
      }
    }

    const pts = r.lat.map((lat, i) => {
      const [x, y] = worldPx(lat, r.lon[i], z);
      return [x - left, y - top];
    });
    overlay.setAttribute("width", W);
    overlay.setAttribute("height", HEIGHT);
    overlay.setAttribute("viewBox", `0 0 ${W} ${HEIGHT}`);
    const [sx, sy] = pts[r.start_index];
    const [fx, fy] = pts[r.finish_index];
    const points = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    overlay.replaceChildren(
      svgEl("polyline", { points, class: "route-casing" }),
      svgEl("polyline", { points, class: "route-line" }),
      svgEl("circle", { cx: fx, cy: fy, r: 5, class: "route-finish" }),
      svgEl("circle", { cx: sx, cy: sy, r: 7, class: "route-start" }),
    );

    const mpp = metresPerPx(midLat, z);
    const m = scaleLength(mpp * SCALE_PX);
    bar.style.width = `${Math.round(m / mpp)}px`;
    barText.textContent = fmtLength(m);
  }

  // Drag to pan; double-click to zoom in where clicked.
  let drag = null;
  box.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("button, a")) return;
    drag = { x: e.clientX, y: e.clientY };
    box.setPointerCapture(e.pointerId);
    box.classList.add("dragging");
  });
  box.addEventListener("pointermove", (e) => {
    if (!drag || !view) return;
    view.cx -= e.clientX - drag.x;
    view.cy -= e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    draw();
  });
  const endDrag = () => {
    drag = null;
    box.classList.remove("dragging");
  };
  box.addEventListener("pointerup", endDrag);
  box.addEventListener("pointercancel", endDrag);
  box.addEventListener("dblclick", (e) => {
    if (!view || e.target.closest("button, a")) return;
    const rect = box.getBoundingClientRect();
    zoomAt(1, e.clientX - rect.left, e.clientY - rect.top);
  });

  // Fit on first layout; on a resize keep the zoom and centre.
  new ResizeObserver(() => {
    const w = box.clientWidth;
    if (!w || w === W) return;
    W = w;
    if (!view) fit();
    draw();
  }).observe(box);

  return box;
}
