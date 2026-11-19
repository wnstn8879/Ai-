import { test } from "node:test";
import assert from "node:assert/strict";
import { createWriterClient } from "../worker/writer-client.js";
const idle = { status: "idle", message_count: 0, draft: "", run_id: "" };
const writing = {
  status: "writing",
  message_count: 0,
  draft: "본문",
  run_id: "run-1",
};
function setup(api) {
  const events = [],
    commits = [],
    errors = [],
    timers = new Map();
  let next = 0;
  return {
    events,
    commits,
    errors,
    timers,
    client: createWriterClient({
      api,
      onStatus: (x) => events.push(x),
      onCommit: (x) => commits.push(x),
      onError: (e) => errors.push(e),
      id: () => String(++next),
      now: () => 20000,
      schedule: (fn) => {
        timers.set(++next, fn);
        return next;
      },
      cancel: (n) => timers.delete(n),
    }),
  };
}

test("one start follows server progression and new chapters without submitting further generations", async () => {
  const calls = [];
  let state = idle;
  const h = setup(async (path, method, body) => {
    calls.push({ path, method, body });
    if (path.endsWith("/start")) state = writing;
    return state;
  });
  await h.client.open("book", 0);
  await h.client.start();
  assert.equal(calls.filter((c) => c.path.endsWith("/start")).length, 1);
  assert.equal(h.timers.size, 1);
  state = { ...writing, message_count: 2, completed: 1 };
  let [key, fn] = h.timers.entries().next().value;
  h.timers.delete(key);
  await fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(h.commits.length, 1);
  assert.equal(calls.filter((c) => c.path.endsWith("/start")).length, 1);
  state = { ...state, status: "choice", question: "믿을까요?" };
  [key, fn] = h.timers.entries().next().value;
  h.timers.delete(key);
  await fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(h.client.state.status, "choice");
  assert.equal(h.timers.size, 0);
});

test("late start after pausing is stopped by its run id instead of renewing hidden generation", async () => {
  let finish;
  const calls = [];
  const h = setup(async (path, method, body) => {
    calls.push({ path, method, body });
    if (path.endsWith("/start"))
      return new Promise((resolve) => (finish = () => resolve(writing)));
    if (path.endsWith("/pause")) return { ...idle, status: "paused" };
    return idle;
  });
  await h.client.open("book", 0);
  const starting = h.client.start();
  await new Promise((r) => setImmediate(r));
  await h.client.pause();
  finish();
  await starting;
  assert.equal(calls.at(-1).path, "/rooms/book/writer/pause");
  assert.equal(calls.at(-1).body.run_id, "run-1");
  assert.equal(h.timers.size, 0);
});

test("one-time direction changes active writing without restarting it or automatically retrying failures", async () => {
  const calls = [];
  let state = idle;
  const h = setup(async (path, method, body) => {
    calls.push({ path, method, body });
    if (path.endsWith("/start")) state = writing;
    if (path.endsWith("/direction"))
      return { ...writing, pending_direction: body.content };
    return state;
  });
  await h.client.open("book", 0);
  await h.client.start();
  await h.client.direction("두 사람이 화해하게 해줘");
  assert.equal(calls.filter((c) => c.path.endsWith("/direction")).length, 1);
  assert.equal(calls.filter((c) => c.path.endsWith("/start")).length, 1);
  await h.client.leave();
  assert.equal(h.timers.size, 0);
  assert.equal(calls.at(-1).path, "/rooms/book/writer/pause");
});

test("crossroad controls wait for committed text and a failed reader refresh is retried", async () => {
  let state = idle,
    reads = 0;
  const statuses = [],
    timers = new Map();
  let key = 0;
  const client = createWriterClient({
    api: async () => state,
    id: () => String(++key),
    onStatus: (s) => statuses.push(s.status),
    onError: () => {},
    onCommit: async () => {
      reads++;
      if (reads === 1) throw Error("temporary reader failure");
    },
    schedule: (fn) => {
      timers.set(++key, fn);
      return key;
    },
    cancel: (k) => timers.delete(k),
  });
  await client.open("book", 0);
  state = {
    ...writing,
    status: "choice",
    message_count: 2,
    question: "갈림길",
  };
  // Reopening sees the saved chapter count from the old reader. The choice must
  // wait until the completed chapter has actually been fetched.
  await client.open("book", 0);
  assert.ok(!statuses.includes("choice"));
  assert.equal(timers.size, 1);
  const [k, fn] = timers.entries().next().value;
  timers.delete(k);
  await fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(reads, 2);
  assert.equal(statuses.at(-1), "choice");
  assert.equal(timers.size, 0);
});
