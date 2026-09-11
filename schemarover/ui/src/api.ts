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
};

const TOKEN_KEY = "schemarover.admin_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": getToken(),
      ...init.headers,
    },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail ?? `Request failed (${res.status})`);
  return body as T;
}

export const health = () => call<{ ok: boolean; connected: boolean }>("/health");
export const connect = (db_url: string) =>
  call<Connection>("/connect", { method: "POST", body: JSON.stringify({ db_url }) });
export const ask = (question: string) =>
  call<QueryResult>("/query", { method: "POST", body: JSON.stringify({ question }) });
export const history = () => call<HistoryRow[]>("/history?limit=50");

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
      hint: "Ask your administrator to connect one, then try again.",
    };
  return { headline: "Something went wrong.", hint: "Try asking again, or rephrase the question." };
}
