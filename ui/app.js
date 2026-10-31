// The Phase 1 screen. It only talks to the engine through the local API
// and contains no trading logic (bible section 4).

const HEALTH_CHECK_EVERY_MS = 2000;

// Times arrive from the engine in UTC and are shown in the owner's chosen time zone.
let displayTimeZone = "UTC";
let engineStartedAt = null;

function showTime(utcText) {
  return new Date(utcText).toLocaleString(undefined, { timeZone: displayTimeZone, timeZoneName: "short" });
}

// --- Engine connection --------------------------------------------------

async function checkEngine() {
  const pill = document.getElementById("engine-status");
  const banner = document.getElementById("engine-banner");
  try {
    const reply = await fetch("/api/health", { cache: "no-store" });
    if (!reply.ok) throw new Error("engine replied " + reply.status);
    const health = await reply.json();
    pill.textContent = "Engine connected";
    pill.className = "status-pill ok";
    banner.hidden = true;
    document.getElementById("fact-version").textContent = health.version;
    engineStartedAt = health.started_at;
    document.getElementById("fact-started").textContent = showTime(engineStartedAt);
    document.getElementById("fact-schema").textContent = health.schema_version;
    document.getElementById("fact-folder").textContent = health.data_folder;
  } catch (problem) {
    pill.textContent = "Engine not connected";
    pill.className = "status-pill down";
    banner.hidden = false;
  }
}

// --- Settings ----------------------------------------------------------

// A short list of common time zones. Any valid name can be saved through the API.
const TIME_ZONES = [
  "UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Asia/Singapore", "Australia/Sydney",
];

async function saveSetting(key, value) {
  const message = document.getElementById("settings-message");
  const reply = await fetch("/api/settings/" + key, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  const result = await reply.json();
  if (reply.ok) {
    message.textContent = "Saved.";
    message.className = "message";
    applySetting(key, value);
  } else {
    message.textContent = result.error;
    message.className = "message error";
  }
}

// Make a setting take effect on screen immediately.
function applySetting(key, value) {
  if (key === "glow_strength") {
    document.documentElement.style.setProperty("--glow-strength", value / 100);
  }
  if (key === "display_timezone") {
    displayTimeZone = value;
    if (engineStartedAt) document.getElementById("fact-started").textContent = showTime(engineStartedAt);
  }
  if (key === "reduce_motion") {
    document.body.classList.toggle("reduce-motion", value);
  }
}

function buildSettingsForm(settings) {
  const form = document.getElementById("settings-form");
  form.innerHTML = "";

  // Display time zone: a drop-down list.
  const tz = settings.display_timezone;
  const tzOptions = TIME_ZONES.includes(tz.value) ? TIME_ZONES : [tz.value, ...TIME_ZONES];
  form.append(row(tz.label, `<select id="display_timezone">${
    tzOptions.map(z => `<option ${z === tz.value ? "selected" : ""}>${z}</option>`).join("")
  }</select>`));

  // Glow strength: a slider from 0 to 100.
  const glow = settings.glow_strength;
  form.append(row(glow.label,
    `<input type="range" id="glow_strength" min="0" max="100" value="${glow.value}">`));

  // Reduce motion: a tick box.
  const motion = settings.reduce_motion;
  form.append(row(motion.label,
    `<input type="checkbox" id="reduce_motion" ${motion.value ? "checked" : ""}>`));

  document.getElementById("display_timezone").onchange = e => saveSetting("display_timezone", e.target.value);
  document.getElementById("glow_strength").onchange = e => saveSetting("glow_strength", Number(e.target.value));
  document.getElementById("reduce_motion").onchange = e => saveSetting("reduce_motion", e.target.checked);

  for (const key of Object.keys(settings)) applySetting(key, settings[key].value);
}

function row(labelText, controlHtml) {
  const label = document.createElement("label");
  label.innerHTML = `<span>${labelText}</span>${controlHtml}`;
  return label;
}

async function loadSettings() {
  try {
    const reply = await fetch("/api/settings", { cache: "no-store" });
    buildSettingsForm(await reply.json());
  } catch (problem) {
    setTimeout(loadSettings, HEALTH_CHECK_EVERY_MS);  // engine not ready yet; try again
  }
}

checkEngine();
loadSettings();
setInterval(checkEngine, HEALTH_CHECK_EVERY_MS);
