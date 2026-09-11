import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ArrowRight, Code2, Copy, Check, X } from "lucide-react";
import { ask, humanError, type QueryResult } from "./api";
import ThemeToggle from "./ThemeToggle";

const EXAMPLES = [
  "Which films are rented most often?",
  "Top 5 customers by total spend",
  "How many payments were made last month?",
];

function cell(v: unknown) {
  if (v === null || v === undefined) return "—";
  return String(v);
}

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || busy) return;
    setQuestion(trimmed);
    setBusy(true);
    setFailure(null);
    setResult(null);
    try {
      setResult(await ask(trimmed));
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const shownError = failure ?? result?.error ?? null;
  const hasRows = !!result && !result.error;

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="px-6 sm:px-10 py-6 flex items-center justify-between">
        <span className="font-display text-[15px] font-semibold tracking-tight">
          Schema<span className="text-signal">Rover</span>
        </span>
        <ThemeToggle />
      </header>

      <main className="flex-1 w-full max-w-3xl mx-auto px-6 sm:px-10 pb-24">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="pt-10 sm:pt-16"
        >
          <h1 className="font-display text-4xl sm:text-5xl font-semibold tracking-[-0.03em] leading-[1.05]">
            Ask your database
            <br />
            <span className="text-slate">a plain question.</span>
          </h1>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
            className="mt-8"
          >
            <div className="flex items-center gap-3">
              <input
                ref={inputRef}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Which films are rented most often?"
                aria-label="Your question"
                className="flex-1 bg-transparent text-lg sm:text-xl py-3 outline-none placeholder:text-hush"
              />
              <button
                type="submit"
                disabled={busy || !question.trim()}
                aria-label="Ask"
                className="shrink-0 size-11 grid place-items-center rounded-full bg-ink text-onink transition hover:bg-signal hover:text-onsignal disabled:opacity-25 disabled:hover:bg-ink disabled:hover:text-onink"
              >
                <ArrowRight size={18} />
              </button>
            </div>

            {/* the sweep — scanner bar while the retriever runs */}
            <div className="relative h-[2px] overflow-hidden bg-rule">
              <div className={busy ? "sweep absolute inset-0" : ""} />
            </div>
          </form>

          {!result && !busy && !shownError && (
            <div className="mt-6 flex flex-wrap gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => submit(ex)}
                  className="text-sm text-slate border border-rule rounded-full px-3.5 py-1.5 transition hover:border-signal hover:text-signal bg-card"
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
        </motion.div>

        <AnimatePresence mode="wait">
          {busy && <Skeleton key="skeleton" />}
          {shownError && !busy && <ErrorCard key="error" raw={shownError} />}
          {hasRows && !busy && <Results key="results" result={result!} />}
        </AnimatePresence>
      </main>
    </div>
  );
}

function Skeleton() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="mt-10 space-y-2.5"
      aria-live="polite"
      aria-label="Searching"
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="h-9 rounded bg-card animate-pulse"
          style={{ opacity: 1 - i * 0.16 }}
        />
      ))}
    </motion.div>
  );
}

function ErrorCard({ raw }: { raw: string }) {
  const { headline, hint } = humanError(raw);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="mt-10 bg-card border-l-2 border-alarm rounded-r p-5"
      role="alert"
    >
      <p className="font-display font-semibold">{headline}</p>
      <p className="text-slate text-sm mt-1.5">{hint}</p>
      <details className="mt-3">
        <summary className="text-xs text-hush cursor-pointer select-none hover:text-slate">
          Technical details
        </summary>
        <p className="font-mono text-xs text-slate mt-2 break-words">{raw}</p>
      </details>
    </motion.div>
  );
}

function Results({ result }: { result: QueryResult }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);
  const { columns, rows, sql, elapsed_ms } = result;

  async function copy() {
    await navigator.clipboard.writeText(sql ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="mt-10"
    >
      <div className="flex items-center justify-between gap-4 mb-3">
        <p className="font-mono text-xs text-slate">
          {rows.length} {rows.length === 1 ? "row" : "rows"}
          <span className="text-hush"> · {(elapsed_ms / 1000).toFixed(1)}s</span>
        </p>
        {sql && (
          <button
            onClick={() => dialogRef.current?.showModal()}
            className="flex items-center gap-1.5 text-xs text-slate border border-rule rounded-full px-3 py-1.5 bg-card transition hover:border-signal hover:text-signal"
          >
            <Code2 size={13} /> View SQL
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="bg-card rounded p-8 text-center">
          <p className="font-display font-semibold">No matching records.</p>
          <p className="text-slate text-sm mt-1.5">
            The question was understood, but the database holds nothing that fits it.
          </p>
        </div>
      ) : (
        <div className="bg-card rounded overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c}
                    className="text-left font-mono text-[11px] uppercase tracking-wider text-hush font-medium px-4 py-3 border-b border-rule whitespace-nowrap"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <motion.tr
                  key={i}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i * 0.02, 0.4), duration: 0.25 }}
                  className="border-b border-rule last:border-0"
                >
                  {row.map((v, j) => (
                    <td key={j} className="px-4 py-2.5 font-mono text-[13px] whitespace-nowrap">
                      {cell(v)}
                    </td>
                  ))}
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <dialog
        ref={dialogRef}
        onClick={(e) => e.target === dialogRef.current && dialogRef.current.close()}
        className="m-auto w-[min(46rem,92vw)] rounded bg-card p-0 text-ink"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-rule">
          <h2 className="font-display font-semibold text-sm">The SQL that ran</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={copy}
              className="flex items-center gap-1.5 text-xs text-slate px-2.5 py-1.5 rounded transition hover:text-signal hover:bg-paper"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={() => dialogRef.current?.close()}
              aria-label="Close"
              className="p-1.5 rounded text-slate transition hover:text-ink hover:bg-paper"
            >
              <X size={15} />
            </button>
          </div>
        </div>
        <pre className="font-mono text-[13px] leading-relaxed p-5 overflow-x-auto whitespace-pre-wrap">
          {sql}
        </pre>
      </dialog>
    </motion.section>
  );
}
