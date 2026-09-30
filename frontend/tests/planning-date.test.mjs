import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const pageUrl = new URL("../app/page.tsx", import.meta.url);
const pageRequire = createRequire(pageUrl);
const compiled = ts.transpileModule(readFileSync(pageUrl, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const NOW = "2026-09-30T09:36:00.000Z";
const TOMORROW = "Tomorrow, after dinner, take a shower.";
const WINDOWS = [{ start: "2026-10-01T01:00:00.000Z", end: "2026-10-01T13:00:00.000Z" }];

// Execute the actual page handlers with a deterministic clock and an in-memory
// API, so these tests cover Extract -> Save -> Generate request wiring.
function pageHarness({ timezone = "Asia/Shanghai", date = "2026-10-01", anchored = false } = {}) {
  const slots = [];
  const saved = new Map();
  const requests = [];
  let cursor = 0;
  let tree;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { slots[index] = value; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useMemo: (fn) => fn(),
  };
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [NOW])); }
    static now() { return new Date(NOW).getTime(); }
  }
  const exports = {};
  runInNewContext(compiled, {
    exports, Date: Clock, process: { env: {} },
    require: (name) => name === "react" ? hooks : pageRequire(name.startsWith("./") ? `${name}.ts` : name),
    fetch: async (url, init = {}) => {
      const path = new URL(url).pathname;
      const body = init.body ? JSON.parse(init.body) : null;
      requests.push({ path, body });
      let result;
      if (path === "/api/tasks/extract") {
        const tasks = [
          { id: "dinner", title: "Dinner", dependency_ids: [] },
          { id: "shower", title: "Shower", dependency_ids: ["dinner"] },
        ].map((task) => ({ urgency: 3, importance: 3, estimated_minutes: 30,
          deadline: null, start_time: null, end_time: null, kind: "habit",
          status: "inbox", priority_score: 38, ...task }));
        if (anchored) Object.assign(tasks[0], { kind: "fixed_event",
          start_time: "2026-10-01T18:00:00+08:00", end_time: "2026-10-01T18:30:00+08:00" });
        result = { tasks, date_context: body.text.includes("Tomorrow") ? date : null, timezone };
      } else if (path === "/api/tasks" && init.method === "POST") {
        result = { ...body, status: "inbox", priority_score: 38 };
        saved.set(result.id, result);
      } else if (path === "/api/tasks") {
        result = [...saved.values()];
      } else if (path === "/api/plans/generate") {
        result = { id: "plan", version: 1, items: [], unscheduled: [], rationale: [], windows: body.windows || [] };
      } else throw new Error(`Unexpected request: ${path}`);
      return { ok: true, json: async () => result };
    },
  });
  function render() { cursor = 0; tree = exports.default(); }
  function nodes(value) {
    if (Array.isArray(value)) return value.flatMap(nodes);
    return value?.props ? [value, ...nodes(value.props.children)] : [];
  }
  function text(value) {
    if (Array.isArray(value)) return value.map(text).join("");
    if (value?.props) return text(value.props.children);
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  }
  render();
  return {
    requests,
    input(value) {
      nodes(tree).find((node) => node.type === "textarea").props.onChange({ target: { value } });
      render();
    },
    async click(label) {
      const button = nodes(tree).find((node) => node.type === "button" && text(node).replace(/\s+/g, " ").trim() === label);
      assert.ok(button, `Button not found: ${label}`);
      assert.ok(!button.props.disabled, `Button disabled: ${label}`);
      await button.props.onClick();
      render();
    },
    planRequest() { return requests.findLast((request) => request.path === "/api/plans/generate")?.body; },
  };
}

async function extractAndSave(page, text = TOMORROW) {
  page.input(text);
  await page.click("Extract tasks →");
  await page.click("Save tasks");
}

test("Tomorrow date survives Extract -> Save -> Generate for tasks without times", async () => {
  const page = pageHarness();
  await extractAndSave(page);
  await page.click("Generate adaptive plan ↗");
  const request = page.planRequest();
  assert.deepEqual(request.windows, WINDOWS);
  assert.equal(request.timezone, "Asia/Shanghai");
  assert.equal(request.now, NOW);
  assert.deepEqual(request.task_ids, ["dinner", "shower"]);
  const saved = page.requests.filter((r) => r.path === "/api/tasks" && r.body).map((r) => r.body);
  assert.equal(saved.length, 2);
  assert.deepEqual(saved[1].dependency_ids, [saved[0].id]);
  assert.ok(saved.every((task) => task.start_time === null && task.deadline === null));
});

test("a new extraction without date context does not reuse Tomorrow windows", async () => {
  const page = pageHarness();
  await extractAndSave(page);
  await page.click("Generate adaptive plan ↗");
  assert.deepEqual(page.planRequest().windows, WINDOWS);
  await extractAndSave(page, "After dinner, take a shower.");
  await page.click("Generate adaptive plan ↗");
  assert.equal(page.planRequest().windows, undefined);
});

test("editing input without extracting keeps the saved task batch's date", async () => {
  const page = pageHarness();
  await extractAndSave(page);
  page.input("Today, after dinner, take a shower.");
  await page.click("Generate adaptive plan ↗");
  assert.deepEqual(page.planRequest().windows, WINDOWS);
});

test("dated fixed events retain the API's existing default window selection", async () => {
  const page = pageHarness({ anchored: true });
  await extractAndSave(page);
  await page.click("Generate adaptive plan ↗");
  assert.equal(page.planRequest().windows, undefined);
  assert.equal(page.planRequest().now, NOW);
});

test("windows use the extraction timezone including its date-specific DST offset", async () => {
  const page = pageHarness({ timezone: "America/New_York", date: "2026-11-01" });
  await extractAndSave(page);
  await page.click("Generate adaptive plan ↗");
  assert.equal(page.planRequest().timezone, "America/New_York");
  assert.deepEqual(page.planRequest().windows, [{ start: "2026-11-01T14:00:00.000Z", end: "2026-11-02T02:00:00.000Z" }]);
});
