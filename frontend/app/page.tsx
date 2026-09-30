"use client";

import { useMemo, useRef, useState } from "react";
import { persistTasks } from "./task-persistence";
import { contextWindows } from "./planning-window";

type Task = { id: string; title: string; description?: string; urgency: number; importance: number; estimated_minutes: number | null; remaining_minutes?: number | null; status: string; priority_score: number; deadline?: string | null; source_text?: string; kind?: "flexible_task" | "fixed_event" | "habit"; start_time?: string | null; end_time?: string | null; duration_source?: "explicit" | "estimated" | "default" | "unknown"; confidence?: number; dependency_ids?: string[]; assumptions?: string[] };
type PlanItem = { task_id: string; start: string; end: string; state: string; reason: string };
type Plan = { id: string; version: number; generated_at: string; items: PlanItem[]; unscheduled: { task_id: string; reason: string }[]; rationale: string[]; windows?: { start: string; end: string }[] };
type Replan = { plan: Plan; changes: string[]; explanation: string };

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
const demoText = "Exam tomorrow: review calculus chapters and submit English assignment. Buy shampoo and reply to the important email.";
function formatTime(value?: string) { return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"; }
function priorityLabel(score: number) { return score >= 75 ? "High" : score >= 50 ? "Medium" : "Low"; }
function timelineDate(plan: Plan) {
  const value = plan.windows?.[0]?.start;
  if (!value) return "Today's timeline";
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today's timeline";
  const dateLabel = date.toLocaleDateString("en-US", { month: "long", day: "numeric" });
  const weekday = date.toLocaleDateString("en-US", { weekday: "long" });
  return `${dateLabel} · ${weekday} timeline`;
}

export default function Home() {
  const [text, setText] = useState(""); const [tasks, setTasks] = useState<Task[]>([]); const [plan, setPlan] = useState<Plan | null>(null); const [originalPlan, setOriginalPlan] = useState<Plan | null>(null); const [explanation, setExplanation] = useState(""); const [assumptions, setAssumptions] = useState<string[]>([]); const [loading, setLoading] = useState(false); const [error, setError] = useState(""); const [activeTask, setActiveTask] = useState<string | null>(null);
  const persistedTasks = useRef(new Map<string, Task>());
  const busy = useRef(false);
  const [demoNow, setDemoNow] = useState<string | null>(null);
  const [extractionContext, setExtractionContext] = useState<{ date: string | null; timezone: string } | null>(null);
  const saved = tasks.length > 0 && tasks.every((task) => persistedTasks.current.has(task.id));
  const taskMap = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const planDiff = useMemo(() => {
    if (!originalPlan || !plan || plan.version === originalPlan.version) return [];
    const oldByTask = new Map(originalPlan.items.map((item) => [item.task_id, item]));
    return plan.items.flatMap((item) => {
      const old = oldByTask.get(item.task_id);
      if (!old || (old.start === item.start && old.end === item.end)) return [];
      const title = taskMap.get(item.task_id)?.title || "Task";
      return [old.start !== item.start
        ? `${title} moved from ${formatTime(old.start)} to ${formatTime(item.start)}`
        : `${title} now ends at ${formatTime(item.end)} (was ${formatTime(old.end)})`];
    });
  }, [originalPlan, plan, taskMap]);
  async function request(path: string, init?: RequestInit) {
    let response: Response;
    try {
      response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
    } catch {
      throw new Error("Cannot reach the LifePilot backend. Start the API on port 8000 and try again.");
    }
    if (!response.ok) {
      const detail = (await response.json().catch(() => null))?.detail;
      throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${response.status})`);
    }
    return response.json();
  }
  async function runAction(action: () => Promise<void>) {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    setError("");
    try { await action(); }
    catch (err) { setError(err instanceof Error ? err.message : "The request failed. Please try again."); }
    finally { busy.current = false; setLoading(false); setActiveTask(null); }
  }
  async function extractTasks() {
    if (!text.trim()) return;
    await runAction(async () => {
      const result = await request("/tasks/extract", { method: "POST", body: JSON.stringify({ text, now: demoNow }) });
      persistedTasks.current.clear();
      setTasks(result.tasks);
      setExtractionContext({ date: result.date_context ?? null, timezone: result.timezone });
      setAssumptions(result.assumptions || []);
      setPlan(null); setOriginalPlan(null); setExplanation("");
    });
  }
  async function persistCurrentTasks() {
    const result = await persistTasks(tasks, persistedTasks.current, (task) => request("/tasks", {
      method: "POST",
      body: JSON.stringify({ title: task.title, description: task.description || "", urgency: task.urgency,
        id: task.id,
        importance: task.importance, estimated_minutes: task.estimated_minutes, remaining_minutes: task.remaining_minutes,
        deadline: task.deadline, source_text: task.source_text || text, kind: task.kind || "flexible_task", start_time: task.start_time, end_time: task.end_time, duration_source: task.duration_source || "estimated", confidence: task.confidence ?? 0.65, dependency_ids: task.dependency_ids || [], assumptions: task.assumptions || [] }),
    }));
    setTasks(result);
    return result;
  }
  async function saveExtractedTasks() {
    if (!tasks.length) return;
    await runAction(async () => { await persistCurrentTasks(); });
  }
  async function generatePlan() {
    if (!tasks.length) return;
    await runAction(async () => {
      const current = await persistCurrentTasks();
      const now = new Date(demoNow || Date.now());
      const hasDatedTask = current.some((task) => task.start_time || task.deadline);
      const generated = await request("/plans/generate", { method: "POST", body: JSON.stringify({
        task_ids: current.map((task) => task.id), now: now.toISOString(),
        timezone: extractionContext?.timezone,
        windows: !hasDatedTask && extractionContext ? contextWindows(extractionContext.date, extractionContext.timezone) : undefined,
      }) });
      const ids = new Set(current.map((task) => task.id));
      const updated = (await request("/tasks") as Task[]).filter((task) => ids.has(task.id));
      updated.forEach((task) => persistedTasks.current.set(task.id, task));
      setTasks(updated); setOriginalPlan(generated); setPlan(generated); setExplanation("");
    });
  }
  async function applyEvent(taskId: string, type: "complete" | "skip" | "delay") {
    if (!plan) return;
    await runAction(async () => {
      setActiveTask(taskId);
      const result: Replan = await request(`/plans/${plan.id}/events`, { method: "POST", body: JSON.stringify({
        task_id: taskId, type, minutes: type === "delay" ? 60 : 0, at: demoNow,
      }) });
      setPlan(result.plan); setExplanation(result.explanation);
      const ids = new Set(tasks.map((task) => task.id));
      const updated = (await request("/tasks") as Task[]).filter((task) => ids.has(task.id));
      updated.forEach((task) => persistedTasks.current.set(task.id, task));
      setTasks(updated);
    });
  }
  function loadDemo() {
    if (busy.current) return;
    const morning = new Date(); morning.setHours(9, 0, 0, 0);
    setDemoNow(morning.toISOString());
    setExtractionContext(null);
    persistedTasks.current.clear();
    setText(demoText); setTasks([]); setPlan(null); setOriginalPlan(null); setExplanation(""); setAssumptions([]); setError("");
  }
  return <main className="shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">✦</span><span>LifePilot</span><span className="beta">HackNowa 2026</span></div><div className="status-dot"><span /> Offline-ready planner</div></header>
    <section className="hero"><div><p className="eyebrow">PERSONAL EXECUTION SYSTEM</p><h1>Make today <em>work for you.</em></h1><p className="subhead">Turn a messy brain dump into a realistic plan that adapts when life changes.</p></div><div className="hero-orbit"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit-core">✦</div></div></section>
    <section className="input-card card"><div className="card-heading"><div><span className="step">01</span><div><h2>Tell me what&apos;s on your mind</h2><p>Enter tasks to review rule-based estimates and priorities.</p></div></div><button className="ghost-button" onClick={loadDemo} disabled={loading}>Load demo scenario</button></div><textarea value={text} disabled={loading} onChange={(event) => { setText(event.target.value); setDemoNow(null); }} placeholder="e.g. I have a calculus exam tomorrow, need to submit my English assignment, buy shampoo, and reply to an important email..." /><div className="input-footer"><span className="hint">{demoNow ? `Demo clock: ${formatTime(demoNow)} · simulated day` : `${text.length} characters · Rule-based extraction`}</span><button className="primary-button" onClick={extractTasks} disabled={loading || !text.trim()}>{loading ? "Working…" : "Extract tasks  →"}</button></div></section>
    {error && <div className="error-banner">{error}</div>}{assumptions.length > 0 && <div className="assumption-banner"><strong>Agent assumptions</strong><span>{assumptions.join(" ")}</span></div>}
    {tasks.length > 0 && <section className="card task-card"><div className="card-heading"><div><span className="step">02</span><div><h2>Your task inbox</h2><p>Review what the agent understood before scheduling.</p></div></div><button className="secondary-button" onClick={saveExtractedTasks} disabled={loading || saved}>{saved ? "Tasks saved" : "Save tasks"}</button></div><div className="task-grid">{tasks.map((task) => <article className="task-row" key={task.id}><div className={`priority-bar ${priorityLabel(task.priority_score).toLowerCase()}`} /><div className="task-main"><div className="task-title-row"><h3>{task.title}</h3><span className={`priority-pill ${priorityLabel(task.priority_score).toLowerCase()}`}>{priorityLabel(task.priority_score)} · {Math.round(task.priority_score)}</span></div><div className="task-meta"><span>◷ {task.estimated_minutes == null ? "Duration unknown" : `${task.estimated_minutes} min`}</span><span>Urgency {task.urgency}/5</span><span>Importance {task.importance}/5</span><span>{(task.kind || "flexible_task").replace("_", " ")}</span>{task.start_time && <span>Starts {formatTime(task.start_time)}</span>}</div></div></article>)}</div><button className="plan-button" onClick={generatePlan} disabled={loading}>Generate adaptive plan <span>↗</span></button></section>}
    {plan && <section className="workspace-grid"><div className="card timeline-card"><div className="card-heading"><div><span className="step">03</span><div><h2>{plan.version > 1 ? "Revised timeline" : timelineDate(plan)}</h2><p>{plan.version > 1 ? `Version ${plan.version} · adapted to your update` : "A feasible plan built around your priorities."}</p></div></div><span className="version-badge">v{plan.version}</span></div><div className="timeline">{plan.items.length === 0 && <div className="empty-state">No tasks fit the available time window.</div>}{plan.items.map((item) => { const task = taskMap.get(item.task_id); if (!task) return null; return <article className={`timeline-item ${task.status === "completed" ? "done" : ""}`} key={`${item.task_id}-${item.start}`}><div className="time-col"><strong>{formatTime(item.start)}</strong><span>{formatTime(item.end)}</span></div><div className="timeline-line"><span className="timeline-dot" /></div><div className="timeline-content"><div className="timeline-title"><h3>{task.title}</h3><span className={`state-chip ${task.status}`}>{task.status.replace("_", " ")}</span></div><p>{item.reason}</p>{task.status !== "completed" && task.status !== "skipped" && <div className="action-row"><button onClick={() => applyEvent(task.id, "complete")} disabled={loading || activeTask === task.id}>Complete</button><button onClick={() => applyEvent(task.id, "delay")} disabled={loading || activeTask === task.id}>Needs 60m more</button><button onClick={() => applyEvent(task.id, "skip")} disabled={loading || activeTask === task.id}>Skip</button></div>}</div></article>})}</div>{plan.unscheduled.length > 0 && <div className="unscheduled"><strong>Needs attention</strong>{plan.unscheduled.map((entry) => <span key={entry.task_id}>• {taskMap.get(entry.task_id)?.title || entry.task_id}: {entry.reason}</span>)}</div>}</div><aside className="side-stack"><div className="card compare-card"><div className="card-heading compact"><div><span className="step">04</span><div><h2>Plan evolution</h2><p>See how the agent responds.</p></div></div></div><div className="compare-flow"><div><span className="compare-icon original">◌</span><div><strong>Original plan</strong><small>{originalPlan ? `${originalPlan.items.length} scheduled blocks` : "Waiting"}</small></div></div><span className="flow-arrow">→</span><div><span className="compare-icon actual">◉</span><div><strong>Actual progress</strong><small>{tasks.filter((task) => task.status === "completed").length} completed</small></div></div><span className="flow-arrow">→</span><div><span className="compare-icon revised">✦</span><div><strong>Revised plan</strong><small>{plan.version > 1 ? `Version ${plan.version}` : "Updates appear here"}</small></div></div></div>{explanation && <div className="explanation"><span>✦</span><p>{explanation}</p></div>}{planDiff.length > 0 && <div className="diff-list"><strong>What changed</strong>{planDiff.map((change) => <span key={change}>↳ {change}</span>)}</div>}</div><div className="card principles-card"><h2>Why this plan?</h2>{(plan.rationale || []).map((reason) => <div className="principle" key={reason}><span>✓</span><p>{reason}</p></div>)}</div></aside></section>}
  </main>;
}
