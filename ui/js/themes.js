// Theme presets (bible section 6A). These five are PROPOSALS for the owner to approve.
// None use black-and-orange, or navy with cyan, magenta or electric green.
// Safety colors (PAPER, LIVE, warnings, blocks, disconnects) are NOT part of any theme.

export const THEMES = {
  lilac_nocturne: {
    name: "Lilac Nocturne", note: "Plum-graphite with a soft lavender glow.",
    bg: "#16141d", bg2: "#1b1924", panel: "#1e1b28", panel2: "#262233", text: "#e9e6f2", muted: "#9b96ad", border: "#322e40",
    accent: "#b3a1ff", up: "#7fd1c0", down: "#ef8fa0", grid: "#24212f",
  },
  rose_quartz: {
    name: "Rose Quartz", note: "Warm charcoal with a dusty rose accent.",
    bg: "#181416", bg2: "#1e191b", panel: "#231d20", panel2: "#2c2428", text: "#f0e6e9", muted: "#a8979d", border: "#3a2f33",
    accent: "#f0a6b8", up: "#9fd6c3", down: "#f08f85", grid: "#2a2226",
  },
  champagne_graphite: {
    name: "Champagne Graphite", note: "Neutral graphite with a pale champagne-gold accent.",
    bg: "#141414", bg2: "#191918", panel: "#1e1d1b", panel2: "#272522", text: "#ece8df", muted: "#a29d92", border: "#34312c",
    accent: "#e3cf9a", up: "#a9d6b0", down: "#e59a8f", grid: "#24221f",
  },
  sea_glass: {
    name: "Sea Glass", note: "Deep slate-teal with a frosted seafoam accent.",
    bg: "#121819", bg2: "#161d1e", panel: "#1a2223", panel2: "#212c2d", text: "#e3eeec", muted: "#91a6a3", border: "#2b3839",
    accent: "#9ad8cb", up: "#a6dcb5", down: "#eaa092", grid: "#1f2829",
  },
  ice_opal: {
    name: "Ice Opal", note: "Cool pewter with an iridescent periwinkle accent.",
    bg: "#14161b", bg2: "#181b21", panel: "#1c1f26", panel2: "#242833", text: "#e6e9f2", muted: "#959cb0", border: "#2e3340",
    accent: "#a9bcff", up: "#8fd4c4", down: "#f0a0b4", grid: "#22262f",
  },
};

export function currentTheme(settings) {
  return THEMES[settings.theme] || THEMES.lilac_nocturne;
}

export function chartColors(settings) {
  const t = currentTheme(settings);
  return {
    background: t.panel,
    text: t.muted,
    grid: t.grid,
    border: t.border,
    accent: settings.accent_color || t.accent,
    up: settings.candle_up_color || t.up,
    down: settings.candle_down_color || t.down,
  };
}

export function applyTheme(settings) {
  const t = currentTheme(settings);
  const root = document.documentElement.style;
  root.setProperty("--bg", t.bg);
  root.setProperty("--bg-2", t.bg2);
  root.setProperty("--panel", t.panel);
  root.setProperty("--panel-2", t.panel2);
  root.setProperty("--text", t.text);
  root.setProperty("--muted", t.muted);
  root.setProperty("--border", t.border);
  root.setProperty("--accent", settings.accent_color || t.accent);
  root.setProperty("--up", settings.candle_up_color || t.up);
  root.setProperty("--down", settings.candle_down_color || t.down);
  root.setProperty("--glow", (settings.glow_strength ?? 50) / 100);
  root.setProperty("--effects", settings.effects_enabled ? (settings.effect_intensity ?? 50) / 50 : 0);
  document.body.classList.toggle("reduce-motion", !!settings.reduce_motion);
}
