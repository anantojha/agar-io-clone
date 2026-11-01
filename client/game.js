"use strict";
(() => {
  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  const $ = (id) => document.getElementById(id);

  // Same origin by default; ?server=wss://host/ws points the page at another game server.
  const params = new URLSearchParams(location.search);
  const WS_URL = params.get("server") ||
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

  let foodRadius = 6; // the server sends the real radii in its welcome message
  let pelletRadius = 20.8;
  const FOOD_COLORS = ["#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9", "#4dabf7", "#9775fa", "#f783ac"];
  const SEND_INTERVAL_MS = 66;
  const KEEPALIVE_MS = 5000;

  let ws = null;
  let myId = null;
  let mapSize = 4000;
  let playing = false;
  let viewHalf = 800; // half-width of the area the server sends us
  let myMass = 0;
  let serverCenter = { x: 2000, y: 2000 };
  const cells = new Map(); // id -> { x, y, r, tx, ty, tr, owner }
  const names = new Map(); // owner id -> name
  let foods = [];
  let viruses = [];
  let pellets = [];
  const cam = { x: 2000, y: 2000, scale: 0.5 };
  const mouse = { x: innerWidth / 2, y: innerHeight / 2 };
  let camReady = false;
  let refused = false; // the server turned this connection away
  let snapInterval = 66; // ms between state frames, from the welcome message then measured
  let lastStateAt = 0;

  // --- UI ------------------------------------------------------------

  const nameInput = $("name");
  try { nameInput.value = localStorage.getItem("blobs-name") || ""; } catch (e) { /* storage may be blocked */ }

  function showMenu(title, status) {
    $("title").textContent = title;
    $("status").textContent = status;
    $("menu").classList.remove("hidden");
    document.querySelectorAll(".hud").forEach((el) => el.classList.add("hidden"));
  }

  function hideMenu() {
    $("menu").classList.add("hidden");
    document.querySelectorAll(".hud").forEach((el) => el.classList.remove("hidden"));
  }

  function play() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const name = nameInput.value.trim();
    try { localStorage.setItem("blobs-name", name); } catch (e) { /* ignore */ }
    ws.send(JSON.stringify({ t: "join", name }));
    $("play").disabled = true;
    $("status").textContent = "Joining…";
  }

  $("play").addEventListener("click", play);
  nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") play(); });

  function renderLeaderboard(rows) {
    const list = $("lb");
    list.textContent = "";
    for (const [name, mass] of rows) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = name;
      const value = document.createElement("span");
      value.textContent = mass;
      li.append(label, value);
      if (name === (names.get(myId) || "")) li.className = "me";
      list.appendChild(li);
    }
  }

  // --- network -------------------------------------------------------

  function connect() {
    ws = new WebSocket(WS_URL);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      $("status").textContent = "Ready";
      $("play").disabled = false;
    };
    ws.onmessage = (event) => {
      // Control messages are JSON text; the world state is a binary frame.
      if (typeof event.data === "string") handle(JSON.parse(event.data));
      else handleState(Protocol.decodeState(event.data));
    };
    ws.onclose = () => {
      playing = false;
      if (refused) return; // keep the "server full" message on screen
      showMenu("Disconnected", "Lost the connection to the server.");
      $("play").textContent = "Reconnect";
      $("play").disabled = false;
      $("play").onclick = () => location.reload();
    };
  }

  function handle(msg) {
    switch (msg.t) {
      case "welcome":
        myId = msg.id;
        mapSize = msg.map;
        foodRadius = msg.fr;
        pelletRadius = msg.pr;
        snapInterval = msg.snap;
        break;
      case "full":
        refused = true;
        showMenu("Server full", msg.reason === "ip"
          ? "Too many connections from your address."
          : "No room right now. Try again in a minute.");
        $("play").textContent = "Try again";
        $("play").disabled = false;
        $("play").onclick = () => location.reload();
        break;
      case "dead":
        playing = false;
        $("play").disabled = false;
        showMenu("You were eaten", `By ${msg.by || "someone"}. Peak mass: ${msg.peak}`);
        break;
    }
  }

  function handleState(msg) {
    const now = performance.now();
    if (lastStateAt) {
      // Follow how often frames really arrive, so smoothing spans exactly one gap.
      const gap = Math.min(Math.max(now - lastStateAt, 20), 250);
      snapInterval += (gap - snapInterval) * 0.1;
    }
    lastStateAt = now;
    applyState(msg, now);
  }

  function applyState(msg, now) {
    if (!playing) {
      playing = true;
      hideMenu();
      $("play").disabled = false;
    }
    if (msg.n) for (const id in msg.n) names.set(Number(id), msg.n[id]);
    viewHalf = msg.v;
    myMass = msg.me[2];
    serverCenter = { x: msg.me[0], y: msg.me[1] };
    $("mass").textContent = myMass;

    const seen = new Set();
    for (const [id, owner, x, y, r] of msg.c) {
      seen.add(id);
      const cell = cells.get(id);
      if (cell) {
        // Glide from wherever it is drawn now to the new position over one frame gap.
        cell.fx = cell.x; cell.fy = cell.y; cell.fr = cell.r;
        cell.tx = x; cell.ty = y; cell.tr = r;
        cell.t0 = now;
      } else {
        cells.set(id, { x, y, r, fx: x, fy: y, fr: r, tx: x, ty: y, tr: r, t0: now, owner });
      }
    }
    for (const id of cells.keys()) if (!seen.has(id)) cells.delete(id);
    foods = msg.f;
    viruses = msg.vi;
    pellets = msg.e;
    if (msg.lb) renderLeaderboard(msg.lb);

    if (!camReady) {
      cam.x = serverCenter.x;
      cam.y = serverCenter.y;
      camReady = true;
    }
  }

  // Tell the server where the cursor points about 15 times a second, only when that spot has moved
  // (or every few seconds anyway, so the server knows we're still here).
  let lastSent = { x: NaN, y: NaN, at: 0 };
  setInterval(() => {
    if (!playing || !ws || ws.readyState !== WebSocket.OPEN) return;
    const x = Math.round(cam.x + (mouse.x - innerWidth / 2) / cam.scale);
    const y = Math.round(cam.y + (mouse.y - innerHeight / 2) / cam.scale);
    const now = performance.now();
    if (x === lastSent.x && y === lastSent.y && now - lastSent.at < KEEPALIVE_MS) return;
    lastSent = { x, y, at: now };
    ws.send(JSON.stringify({ t: "move", x, y }));
  }, SEND_INTERVAL_MS);

  function act(kind) {
    if (playing && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: kind }));
  }

  addEventListener("keydown", (e) => {
    if (!playing || e.target === nameInput) return;
    if (e.code === "Space") {
      e.preventDefault();
      if (!e.repeat) act("split");
    } else if (e.code === "KeyW") {
      act("eject"); // holding the key keeps feeding
    }
  });
  $("btn-split").addEventListener("pointerdown", (e) => { e.preventDefault(); act("split"); });
  $("btn-eject").addEventListener("pointerdown", (e) => { e.preventDefault(); act("eject"); });

  addEventListener("mousemove", (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
  addEventListener("touchmove", (e) => {
    const t = e.touches[0];
    mouse.x = t.clientX; mouse.y = t.clientY;
  }, { passive: true });
  addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    mouse.x = t.clientX; mouse.y = t.clientY;
  }, { passive: true });

  // --- drawing -------------------------------------------------------

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(innerWidth * dpr);
    canvas.height = Math.round(innerHeight * dpr);
  }
  addEventListener("resize", resize);
  resize();

  function ownerColor(owner) {
    return `hsl(${(owner * 137.5) % 360}, 70%, 55%)`;
  }

  function drawGrid(left, top, right, bottom) {
    const step = 100;
    ctx.beginPath();
    for (let x = Math.max(0, Math.ceil(left / step) * step); x <= Math.min(mapSize, right); x += step) {
      ctx.moveTo(x, Math.max(0, top)); ctx.lineTo(x, Math.min(mapSize, bottom));
    }
    for (let y = Math.max(0, Math.ceil(top / step) * step); y <= Math.min(mapSize, bottom); y += step) {
      ctx.moveTo(Math.max(0, left), y); ctx.lineTo(Math.min(mapSize, right), y);
    }
    ctx.stroke();
  }

  function drawVirus(x, y, r) {
    const spikes = 24;
    ctx.beginPath();
    for (let i = 0; i < spikes * 2; i++) {
      const angle = (Math.PI * i) / spikes;
      const radius = i % 2 === 0 ? r * 1.08 : r * 0.92;
      const px = x + Math.cos(angle) * radius, py = y + Math.sin(angle) * radius;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = "#4cc25a";
    ctx.fill();
    ctx.lineWidth = Math.max(2, r * 0.06);
    ctx.strokeStyle = "#2f8f3b";
    ctx.stroke();
  }

  let lastFrame = performance.now();
  function frame(now) {
    const dt = Math.min((now - lastFrame) / 1000, 0.1);
    lastFrame = now;
    const W = innerWidth, H = innerHeight;
    const dpr = window.devicePixelRatio || 1;

    // Move each cell along a straight line from its previous drawn spot to the newest server spot,
    // taking one frame gap, so 15 updates a second still look like continuous motion.
    let mx = 0, my = 0, mw = 0;
    for (const c of cells.values()) {
      const u = Math.min(1, (now - c.t0) / snapInterval);
      c.x = c.fx + (c.tx - c.fx) * u;
      c.y = c.fy + (c.ty - c.fy) * u;
      c.r = c.fr + (c.tr - c.fr) * u;
      if (c.owner === myId) {
        const w = c.r * c.r;
        mx += c.x * w; my += c.y * w; mw += w;
      }
    }
    const target = mw > 0 ? { x: mx / mw, y: my / mw } : serverCenter;
    const camK = 1 - Math.exp(-dt * 10);
    cam.x += (target.x - cam.x) * camK;
    cam.y += (target.y - cam.y) * camK;
    // Fit the area the server sends along the longer screen side so the edges are never empty.
    const wantScale = Math.max(W, H) / (2 * viewHalf);
    cam.scale += (wantScale - cam.scale) * camK;

    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = dark ? "#0f171c" : "#cfdde4";
    ctx.fillRect(0, 0, W, H);

    ctx.setTransform(dpr * cam.scale, 0, 0, dpr * cam.scale,
      dpr * (W / 2 - cam.x * cam.scale), dpr * (H / 2 - cam.y * cam.scale));
    const left = cam.x - W / 2 / cam.scale, right = cam.x + W / 2 / cam.scale;
    const top = cam.y - H / 2 / cam.scale, bottom = cam.y + H / 2 / cam.scale;

    ctx.fillStyle = dark ? "#1b2830" : "#f4fafc";
    ctx.fillRect(0, 0, mapSize, mapSize);
    ctx.strokeStyle = dark ? "#26363f" : "#dde8ee";
    ctx.lineWidth = 1 / cam.scale;
    drawGrid(left, top, right, bottom);
    ctx.strokeStyle = dark ? "#4a6270" : "#9db0bb";
    ctx.lineWidth = 4 / cam.scale;
    ctx.strokeRect(0, 0, mapSize, mapSize);

    for (const [x, y, kind] of foods) {
      ctx.fillStyle = FOOD_COLORS[kind];
      ctx.beginPath();
      ctx.arc(x, y, foodRadius, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const [x, y, owner] of pellets) {
      ctx.fillStyle = ownerColor(owner);
      ctx.strokeStyle = "rgba(0, 0, 0, 0.25)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, pelletRadius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }

    for (const [x, y, r] of viruses) drawVirus(x, y, r);

    const sorted = [...cells.values()].sort((a, b) => a.r - b.r);
    for (const c of sorted) {
      const mine = c.owner === myId;
      ctx.fillStyle = ownerColor(c.owner);
      // Your own pieces get a white rim so they never blend in with a bot of a similar color.
      ctx.strokeStyle = mine ? "#ffffff" : "rgba(0, 0, 0, 0.25)";
      ctx.lineWidth = Math.max(mine ? 3 : 2, c.r * (mine ? 0.09 : 0.06));
      ctx.beginPath();
      ctx.arc(c.x, c.y, c.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const name = names.get(c.owner);
      if (name && c.r * cam.scale > 14) {
        const size = Math.max(12 / cam.scale, c.r * 0.4);
        ctx.font = `700 ${size}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.lineWidth = size * 0.12;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
        ctx.strokeText(name, c.x, c.y);
        ctx.fillStyle = "#fff";
        ctx.fillText(name, c.x, c.y);
      }
    }

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  connect();
})();
