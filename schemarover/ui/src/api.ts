export type Linked = {
  lexical: string[];
  semantic: string[];
  fk_expanded: boolean;
  added_by_fk: string[];
  tables: string[];
};

export type QueryResult = {
  question: string;
  linked: Linked;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  error: string | null;
  prompt_chars: number;
  total_tables_in_db: number;
  elapsed_ms: number;
  ts?: string; // set when reopened from history
};

export type TableInfo = { name: string; columns: number; foreign_keys: number };

export type Connection = {
  connected: boolean;
  database: string;
  dialect: string;
  safe_url: string;
  table_count: number;
  tables: TableInfo[];
};

export type HistoryRow = {
  id: number;
  ts: string;
  database: string;
  question: string;
  sql: string | null;
  linked_tables: string;
  total_tables: number;
  elapsed_ms: number;
  row_count: number;
  error: string | null;
  has_result: number;
};

export type SavedConnection = { id: number; name: string; safe_url: string; last_used: number };

const TOKEN_KEY = "schemarover.session";

export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...init.headers,
    },
  });
  const body = await res.json().catch(() => null);
  // expired or revoked session: drop it and send the user to log in again
  if (res.status === 401 && !path.startsWith("/auth/")) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.assign("/login");
  }
  if (!res.ok) throw new Error(body?.detail ?? `Request failed (${res.status})`);
  return body as T;
}

const post = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });

export async function authenticate(mode: "login" | "signup", email: string, password: string, invite = "") {
  const r = await call<{ token: string; email: string }>(`/auth/${mode}`, post({ email, password, invite }));
  setToken(r.token);
}
export async function logout() {
  await call("/auth/logout", { method: "POST" }).catch(() => {});
  localStorage.removeItem(TOKEN_KEY);
}
export const me = () => call<{ email: string; connection: Connection | null }>("/auth/me");

export const connect = (db_url: string, name = "") => call<Connection>("/connect", post({ db_url, name }));
export const savedConnections = () => call<SavedConnection[]>("/connections");
export const openSaved = (id: number) => call<Connection>(`/connections/${id}/connect`, { method: "POST" });
export const forgetSaved = (id: number) => call(`/connections/${id}`, { method: "DELETE" });

export const ask = (question: string) => call<QueryResult>("/query", post({ question }));
export const history = () => call<HistoryRow[]>("/history?limit=50");
export const historyEntry = (id: number) => call<QueryResult>(`/history/${id}`);

/** Download a result as CSV. The BOM makes Excel read UTF-8 (names with accents) correctly. */
export function downloadCsv(filename: string, columns: string[], rows: unknown[][]) {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [columns, ...rows].map((r) => r.map(esc).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Turns backend error strings into something a non-technical person can act on. */
export function humanError(raw: string): { headline: string; hint: string } {
  if (raw.startsWith("Rejected for safety"))
    return {
      headline: "That question would have changed your data.",
      hint: "SchemaRover only reads. Try rephrasing it as a question about what's in the database.",
    };
  if (raw.startsWith("Execution failed"))
    return {
      headline: "The database couldn't run that.",
      hint: "Usually the question mentions something the database doesn't track. Try naming the information more directly.",
    };
  if (raw.includes("can't be answered"))
    return {
      headline: "This database doesn't hold that answer.",
      hint: "Try asking about something the data actually records.",
    };
  if (raw.startsWith("LLM error"))
    return { headline: "Couldn't reach the language model.", hint: "Wait a moment and ask again." };
  if (raw.includes("Connect to a database"))
    return {
      headline: "No database is connected.",
      hint: "Open the console and connect one, then try again.",
    };
  return { headline: "Something went wrong.", hint: "Try asking again, or rephrase the question." };
}
