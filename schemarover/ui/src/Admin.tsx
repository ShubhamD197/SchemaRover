import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Link } from "react-router-dom";
import { Plug, Search, ExternalLink, AlertTriangle } from "lucide-react";
import {
  ask,
  connect,
  getToken,
  health,
  history,
  setToken,
  type Connection,
  type HistoryRow,
  type QueryResult,
} from "./api";
import ThemeToggle from "./ThemeToggle";

/** Which retrieval stage first surfaced a table. Drives the schema map colours. */
type Stage = "lexical" | "semantic" | "fk" | "none";

const STAGE_STYLE: Record<Stage, string> = {
  lexical: "bg-ink text-onink border-ink",
  semantic: "bg-signal text-onsignal border-signal",
  fk: "bg-beacon text-onbeacon border-beacon",
  none: "bg-card text-hush border-rule",
};

const STAGE_LABEL: Record<Exclude<Stage, "none">, string> = {
  lexical: "Lexical match",
  semantic: "Semantic match",
  fk: "Added by FK traversal",
};

export default function Admin() {
  const [token, setTokenState] = useState(getToken());
  const [dbUrl, setDbUrl] = useState("");
  const [conn, setConn] = useState<Connection | null>(null);
  const [connError, setConnError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const [probe, setProbe] = useState("");
  const [probing, setProbing] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  const [rows, setRows] = useState<HistoryRow[]>([]);

  const loadHistory = () => history().then(setRows).catch(() => setRows([]));

  useEffect(() => {
    health().catch(() => {});
    loadHistory();
  }, []);

  async function doConnect(e: React.FormEvent) {
    e.preventDefault();
    setConnecting(true);
    setConnError(null);
    try {
      setConn(await connect(dbUrl));
      setResult(null);
    } catch (err) {
      setConnError(err instanceof Error ? err.message : "Connection failed.");
      setConn(null);
    } finally {
      setConnecting(false);
    }
  }

  async function doProbe(e: React.FormEvent) {
    e.preventDefault();
    if (!probe.trim()) return;
    setProbing(true);
    setProbeError(null);
    try {
      setResult(await ask(probe.trim()));
      loadHistory();
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "Query failed.");
    } finally {
      setProbing(false);
    }
  }

  /** table name -> stage, for the schema map */
  const stages = useMemo(() => {
    const m = new Map<string, Stage>();
    conn?.tables.forEach((t) => m.set(t.name, "none"));
    if (!result) return m;
    const { lexical, semantic, added_by_fk } = result.linked;
    added_by_fk.forEach((t) => m.set(t, "fk"));
    semantic.forEach((t) => m.set(t, "semantic"));
    lexical.forEach((t) => m.set(t, "lexical"));
    return m;
  }, [conn, result]);

  /** Mean share of the schema handed to the LLM, over logged queries. */
  const meanReduction = useMemo(() => {
    const usable = rows.filter((r) => r.total_tables > 0);
    if (!usable.length) return null;
    const mean =
      usable.reduce((acc, r) => {
        const linked = JSON.parse(r.linked_tables || "[]").length;
        return acc + linked / r.total_tables;
      }, 0) / usable.length;
    return Math.round((1 - mean) * 100);
  }, [rows]);

  const meanLatency = rows.length
    ? Math.round(rows.reduce((a, r) => a + r.elapsed_ms, 0) / rows.length)
    : null;

  return (
    <div className="min-h-dvh">
      <header className="border-b border-rule bg-card">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-[15px] font-semibold tracking-tight">
              Schema<span className="text-signal">Rover</span>
            </span>
            <span className="font-mono text-[11px] uppercase tracking-wider text-hush">
              Console
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-2 font-mono text-xs text-slate">
              <span
                className={`size-1.5 rounded-full ${conn ? "bg-signal" : "bg-rule"}`}
                aria-hidden
              />
              {conn ? `${conn.database} · ${conn.dialect}` : "no database"}
            </span>
            <Link
              to="/"
              className="flex items-center gap-1.5 text-xs text-slate transition hover:text-signal"
            >
              User app <ExternalLink size={12} />
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {/* --- admin token --- */}
        <Panel title="Access" note="Sent as X-Admin-Token on privileged calls.">
          <div className="flex items-center gap-3">
            <input
              type="password"
              value={token}
              onChange={(e) => {
                setTokenState(e.target.value);
                setToken(e.target.value);
              }}
              placeholder="Admin token"
              aria-label="Admin token"
              className="flex-1 font-mono text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal"
            />
            {!token && (
              <span className="flex items-center gap-1.5 text-xs text-beacon shrink-0">
                <AlertTriangle size={13} /> required to connect
              </span>
            )}
          </div>
        </Panel>

        {/* --- connection --- */}
        <Panel
          title="Database connection"
          note="Kept off the user app on purpose — end users never see a connection string."
        >
          <form onSubmit={doConnect} className="flex flex-col sm:flex-row gap-3">
            <input
              value={dbUrl}
              onChange={(e) => setDbUrl(e.target.value)}
              placeholder="mysql+pymysql://user:password@localhost:3306/sakila"
              aria-label="Database URL"
              className="flex-1 font-mono text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal"
            />
            <button
              type="submit"
              disabled={connecting || !dbUrl.trim()}
              className="flex items-center justify-center gap-2 bg-ink text-onink text-sm rounded px-5 py-2 transition hover:bg-signal hover:text-onsignal disabled:opacity-30 disabled:hover:bg-ink disabled:hover:text-onink"
            >
              <Plug size={14} />
              {connecting ? "Connecting…" : "Connect"}
            </button>
          </form>
          {connError && (
            <p className="mt-3 font-mono text-xs text-alarm break-words">{connError}</p>
          )}
          {conn && (
            <p className="mt-3 font-mono text-xs text-slate">
              {conn.safe_url} · {conn.table_count} tables introspected
            </p>
          )}
        </Panel>

        {/* --- metrics --- */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Metric
            label="Tables retrieved"
            value={result ? `${result.linked.tables.length}` : "—"}
            sub={result ? `of ${result.total_tables_in_db} in schema` : "run a query"}
          />
          <Metric
            label="Schema withheld"
            value={
              result
                ? `${Math.round(
                    (1 - result.linked.tables.length / Math.max(result.total_tables_in_db, 1)) * 100
                  )}%`
                : "—"
            }
            sub="this query"
            accent
          />
          <Metric
            label="Mean withheld"
            value={meanReduction === null ? "—" : `${meanReduction}%`}
            sub={`over ${rows.length} logged queries`}
          />
          <Metric
            label="Mean latency"
            value={meanLatency === null ? "—" : `${(meanLatency / 1000).toFixed(2)}s`}
            sub="end to end"
          />
        </div>

        {/* --- probe + schema map --- */}
        <Panel
          title="Retrieval map"
          note="Every table in the schema. A query lights up only what the retriever passed to the model."
        >
          <form onSubmit={doProbe} className="flex flex-col sm:flex-row gap-3 mb-5">
            <input
              value={probe}
              onChange={(e) => setProbe(e.target.value)}
              placeholder="Ask a question to trace the retrieval"
              aria-label="Probe question"
              className="flex-1 text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal"
            />
            <button
              type="submit"
              disabled={probing || !probe.trim()}
              className="flex items-center justify-center gap-2 bg-ink text-onink text-sm rounded px-5 py-2 transition hover:bg-signal hover:text-onsignal disabled:opacity-30 disabled:hover:bg-ink disabled:hover:text-onink"
            >
              <Search size={14} />
              {probing ? "Tracing…" : "Trace"}
            </button>
          </form>

          <div className="relative h-[2px] overflow-hidden bg-rule mb-5">
            <div className={probing ? "sweep absolute inset-0" : ""} />
          </div>

          {probeError && (
            <p className="mb-4 font-mono text-xs text-alarm break-words">{probeError}</p>
          )}

          {!conn ? (
            <p className="text-sm text-hush">Connect a database to see its schema.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {conn.tables.map((t, i) => {
                  const stage = stages.get(t.name) ?? "none";
                  return (
                    <motion.span
                      key={t.name}
                      layout
                      animate={{ scale: 1 }}
                      initial={false}
                      transition={{ delay: stage === "none" ? 0 : Math.min(i * 0.012, 0.3) }}
                      title={`${t.columns} columns · ${t.foreign_keys} foreign keys`}
                      className={`font-mono text-[11px] border rounded px-2 py-1 transition-colors duration-300 ${STAGE_STYLE[stage]}`}
                    >
                      {t.name}
                    </motion.span>
                  );
                })}
              </div>

              <div className="flex flex-wrap gap-4 mt-5 pt-4 border-t border-rule">
                {(Object.keys(STAGE_LABEL) as Array<keyof typeof STAGE_LABEL>).map((s) => (
                  <span key={s} className="flex items-center gap-2 text-xs text-slate">
                    <span className={`size-2.5 rounded-[2px] border ${STAGE_STYLE[s]}`} aria-hidden />
                    {STAGE_LABEL[s]}
                  </span>
                ))}
                {result?.linked.fk_expanded === false && (
                  <span className="text-xs text-hush">FK traversal skipped for this question</span>
                )}
              </div>
            </>
          )}

          <AnimatePresence>
            {result?.sql && (
              <motion.pre
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-5 font-mono text-[12px] leading-relaxed bg-paper rounded p-4 overflow-x-auto whitespace-pre-wrap"
              >
                {result.sql}
              </motion.pre>
            )}
          </AnimatePresence>
        </Panel>

        {/* --- history --- */}
        <Panel title="Query log" note={`${rows.length} most recent`}>
          {rows.length === 0 ? (
            <p className="text-sm text-hush">Nothing logged yet.</p>
          ) : (
            <div className="overflow-x-auto -mx-5">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr>
                    {["When", "Question", "Tables", "Rows", "Time", "Error"].map((h) => (
                      <th
                        key={h}
                        className="text-left font-mono text-[11px] uppercase tracking-wider text-hush font-medium px-5 py-2 border-b border-rule whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const linked = JSON.parse(r.linked_tables || "[]").length;
                    return (
                      <tr key={r.id} className="border-b border-rule last:border-0">
                        <td className="px-5 py-2.5 font-mono text-xs text-hush whitespace-nowrap">
                          {r.ts.slice(5, 16)}
                        </td>
                        <td className="px-5 py-2.5 max-w-sm truncate">{r.question}</td>
                        <td className="px-5 py-2.5 font-mono text-xs whitespace-nowrap">
                          <span className="text-beacon">{linked}</span>
                          <span className="text-hush"> / {r.total_tables}</span>
                        </td>
                        <td className="px-5 py-2.5 font-mono text-xs">{r.row_count}</td>
                        <td className="px-5 py-2.5 font-mono text-xs text-slate whitespace-nowrap">
                          {(r.elapsed_ms / 1000).toFixed(2)}s
                        </td>
                        <td className="px-5 py-2.5 font-mono text-xs text-alarm max-w-xs truncate">
                          {r.error ?? ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </main>
    </div>
  );
}

function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-card rounded border border-rule p-5">
      <div className="mb-4">
        <h2 className="font-display text-sm font-semibold tracking-tight">{title}</h2>
        {note && <p className="text-xs text-hush mt-1">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Metric({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-card rounded border border-rule p-4">
      <p className="font-mono text-[10px] uppercase tracking-wider text-hush">{label}</p>
      <p
        className={`font-display text-3xl font-semibold tracking-tight mt-2 ${
          accent ? "text-beacon" : ""
        }`}
      >
        {value}
      </p>
      <p className="text-xs text-hush mt-1">{sub}</p>
    </div>
  );
}
