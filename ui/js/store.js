// The screen's shared memory: settings, markets, accounts and which account is active.

import { get } from "./api.js";

export const store = {
  settings: {},
  markets: {},          // symbol -> market facts
  watchlists: {},
  accounts: [],
  activeAccountId: null,
  tradingHalted: false,
  scripts: [],
  runs: [],
  auth: {},
  prices: {},           // symbol -> last price
  feeds: {},            // symbol -> ok / stale / down / waiting
  version: "",
};

const subscribers = new Set();
export function onChange(fn) { subscribers.add(fn); return () => subscribers.delete(fn); }
export function changed(what) { for (const fn of subscribers) { try { fn(what); } catch (e) { console.error(e); } } }

export async function loadState() {
  const state = await get("/api/state");
  store.settings = state.settings;
  store.markets = Object.fromEntries(state.markets.map((m) => [m.symbol, m]));
  store.watchlists = state.watchlists;
  store.accounts = state.accounts;
  store.tradingHalted = state.trading_halted;
  store.scripts = state.scripts;
  store.runs = state.runs;
  store.auth = state.auth;
  store.version = state.version;
  store.workspaces = state.workspaces;
  const saved = localStorage.getItem("activeAccount");
  store.activeAccountId = state.accounts.find((a) => a.id === saved)?.id || state.accounts[0]?.id || null;
  changed("all");
}

export function activeAccount() {
  return store.accounts.find((a) => a.id === store.activeAccountId) || null;
}

export function setActiveAccount(id) {
  store.activeAccountId = id;
  try { localStorage.setItem("activeAccount", id); } catch (e) { /* private window */ }
  changed("account");
}

export async function refreshAccounts() {
  store.accounts = await get("/api/accounts");
  changed("accounts");
}

export async function refreshScripts() {
  store.scripts = await get("/api/scripts");
  store.runs = await get("/api/runs");
  changed("scripts");
}

export function market(symbol) { return store.markets[symbol]; }
