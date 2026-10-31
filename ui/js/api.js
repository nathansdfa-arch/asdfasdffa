// Talking to the engine: simple requests, plus the live WebSocket.
// Screens never contain trading logic; they only ask the engine (bible section 4).

export async function get(path) {
  const reply = await fetch(path, { cache: "no-store" });
  const body = await reply.json().catch(() => ({}));
  if (!reply.ok) throw new Error(body.error || `Request failed (${reply.status})`);
  return body;
}

export async function send(method, path, body) {
  const reply = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await reply.json().catch(() => ({}));
  if (!reply.ok) throw new Error(result.error || `Request failed (${reply.status})`);
  return result;
}

export const post = (path, body = {}) => send("POST", path, body);
export const put = (path, body = {}) => send("PUT", path, body);
export const del = (path) => send("DELETE", path);

// ---- Live updates -----------------------------------------------------------

const listeners = new Map();   // message type -> set of functions
let socket = null;
let watched = [];
let connected = false;

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}

function emit(type, data) {
  for (const fn of listeners.get(type) || []) {
    try { fn(data); } catch (problem) { console.error(problem); }
  }
}

export function watch(symbol, timeframe) {
  watched.push({ symbol, timeframe });
  if (socket && socket.readyState === 1) socket.send(JSON.stringify({ watch: [{ symbol, timeframe }] }));
}

export function isConnected() { return connected; }

export function connectLive() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onopen = () => {
    connected = true;
    emit("connection", true);
    if (watched.length) socket.send(JSON.stringify({ watch: watched }));
  };
  socket.onmessage = (event) => {
    for (const message of JSON.parse(event.data)) emit(message.type, message.data);
  };
  socket.onclose = () => {
    if (connected) emit("connection", false);
    connected = false;
    setTimeout(connectLive, 1500);   // keep trying; the red banner shows meanwhile
  };
}
