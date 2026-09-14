import assert from "node:assert/strict";
import test from "node:test";
import { persistTasks } from "../app/task-persistence.ts";

test("saving then generating reuses saved task IDs", async () => {
  const drafts = [{ id: "draft-a" }, { id: "draft-b" }];
  const cache = new Map();
  let requests = 0;
  const create = async (task) => ({ ...task, id: `saved-${++requests}` });
  const saved = await persistTasks(drafts, cache, create);
  assert.deepEqual(await persistTasks(saved, cache, create), saved);
  assert.deepEqual(await persistTasks(drafts, cache, create), saved);
  assert.equal(requests, 2);
});

test("a failed save stops the batch and retry preserves earlier successes", async () => {
  const drafts = [{ id: "a" }, { id: "b" }, { id: "c" }];
  const cache = new Map();
  const requests = [];
  let fail = true;
  const create = async (task) => {
    requests.push(task.id);
    if (task.id === "b" && fail) throw new Error("API unavailable");
    return { id: `saved-${task.id}` };
  };
  await assert.rejects(persistTasks(drafts, cache, create), /API unavailable/);
  assert.deepEqual(requests, ["a", "b"]);
  fail = false;
  const saved = await persistTasks(drafts, cache, create);
  assert.deepEqual(requests, ["a", "b", "b", "c"]);
  assert.deepEqual(saved.map((task) => task.id), ["saved-a", "saved-b", "saved-c"]);
});
