const { test } = require("node:test");
const assert = require("node:assert/strict");
const { DatabaseSync } = require("node:sqlite");
const { mkdtempSync, readFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const vm = require("node:vm");
const { transformSync } = require("@babel/core");
function load(name) {
  const context = { exports: {}, setTimeout, clearTimeout };
  vm.runInNewContext(
    transformSync(readFileSync(name, "utf8"), {
      plugins: ["@babel/plugin-transform-modules-commonjs"],
      babelrc: false,
      configFile: false,
    }).code,
    context,
  );
  return context.exports;
}
const { createOutboxStore } = load("./outboxStore.js");
const { createOutboxWorker } = load("./outboxWorker.js");
const alice = { api: "https://one.example", userId: "alice" },
  bob = { ...alice, userId: "bob" };
function database(path) {
  const db = new DatabaseSync(path);
  const adapter = {
    execAsync: async (sql) => db.exec(sql),
    runAsync: async (sql, ...params) => db.prepare(sql).run(...params),
    getFirstAsync: async (sql, ...params) => db.prepare(sql).get(...params),
    getAllAsync: async (sql, ...params) => db.prepare(sql).all(...params),
    withExclusiveTransactionAsync: async (fn) => {
      db.exec("BEGIN IMMEDIATE");
      try {
        await fn(adapter);
        db.exec("COMMIT");
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    },
    close: () => db.close(),
  };
  return adapter;
}
async function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), "storyverse-outbox-"));
  const path = join(dir, "queue.db");
  let db = database(path),
    clock = 1000,
    store = createOutboxStore(db, () => clock);
  await store.initialize();
  t.after(() => {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return {
    get db() {
      return db;
    },
    get store() {
      return store;
    },
    get now() {
      return clock;
    },
    advance: (n) => (clock += n),
    async restart() {
      db.close();
      db = database(path);
      store = createOutboxStore(db, () => clock);
      await store.initialize();
      return store;
    },
  };
}
const entry = (id, extra = {}) => ({
  requestId: id,
  roomId: "room",
  roomTitle: "Story",
  kind: "message",
  actor: "Alice",
  content: "Message " + id,
  ...extra,
});
function worker(t, f, send, scope = alice) {
  const w = createOutboxWorker({
    store: f.store,
    scope,
    send,
    now: () => f.now,
    schedule: () => 1,
    cancel: () => {},
  });
  t.after(() => w.stop());
  return w;
}

test("draft and request ID survive a real SQLite close and reopen", async (t) => {
  const f = await fixture(t);
  await f.store.saveDraft(alice, "room", "Message first");
  await f.store.enqueue(alice, entry("first"));
  await f.store.saveDraft(alice, "room", "Next draft");
  await f.restart();
  assert.equal(await f.store.getDraft(alice, "room"), "Next draft");
  const [row] = await f.store.list(alice);
  assert.equal(row.requestId, "first");
  assert.equal(row.content, "Message first");
  assert.equal(row.roomTitle, "Story");
});
test("account, server and room scopes never expose another draft or queue", async (t) => {
  const f = await fixture(t);
  await f.store.saveDraft(alice, "room", "Private");
  await f.store.enqueue(alice, entry("a"));
  assert.equal(await f.store.getDraft(bob, "room"), "");
  assert.equal((await f.store.list(bob)).length, 0);
  assert.equal(
    await f.store.getDraft({ ...alice, api: "https://two.example" }, "room"),
    "",
  );
  assert.equal(
    (await f.store.list({ ...alice, api: "https://two.example" })).length,
    0,
  );
  assert.equal(await f.store.getDraft(alice, "different"), "");
  assert.equal(await f.store.claim(bob, "a"), false);
  await assert.rejects(f.store.enqueue(bob, entry("a")));
  assert.equal((await f.store.list(alice)).length, 1);
});
test("failed transaction keeps the unsent draft and creates no queue row", async (t) => {
  const f = await fixture(t);
  await f.store.saveDraft(alice, "room", "Message a");
  await f.db.execAsync(
    "CREATE TRIGGER disk_error AFTER INSERT ON outbox BEGIN SELECT RAISE(ABORT,'disk full');END;",
  );
  await assert.rejects(f.store.enqueue(alice, entry("a")));
  assert.equal(await f.store.getDraft(alice, "room"), "Message a");
  assert.equal((await f.store.list(alice)).length, 0);
});
test("enqueue does not erase a newer draft and an existing ID cannot change payload", async (t) => {
  const f = await fixture(t);
  await f.store.saveDraft(alice, "room", "Newer draft");
  await f.store.enqueue(alice, entry("a"));
  assert.equal(await f.store.getDraft(alice, "room"), "Newer draft");
  await f.store.enqueue(alice, entry("a"));
  assert.equal((await f.store.list(alice)).length, 1);
  await assert.rejects(
    f.store.enqueue(alice, entry("a", { content: "Changed" })),
  );
});
test("restart requeues uncertain human sends and requires review for AI", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("human"));
  await f.store.claim(alice, "human");
  await f.store.enqueue(
    alice,
    entry("ai", { kind: "turn", roomId: "ai-room" }),
  );
  await f.store.claim(alice, "ai");
  await f.restart();
  const rows = await f.store.list(alice);
  assert.equal(rows[0].status, "queued");
  assert.equal(rows[1].status, "review");
  const sent = [];
  await worker(t, f, async (_, path) => sent.push(path)).wake();
  assert.equal(sent.length, 1);
  assert.ok(sent[0].endsWith("/messages"));
});
test("lost acknowledgement retries the same durable ID without a second server message", async (t) => {
  const f = await fixture(t);
  const server = new Map(),
    ids = [];
  let first = true;
  await f.store.enqueue(alice, entry("stable-id"));
  const send = async (user, path, method, body) => {
    ids.push(body.request_id);
    if (!server.has(body.request_id)) server.set(body.request_id, body.content);
    if (first) {
      first = false;
      throw new Error("Response lost");
    }
  };
  const before = worker(t, f, send);
  await before.wake();
  before.stop();
  assert.equal((await f.store.list(alice))[0].status, "queued");
  f.advance(10000);
  await f.restart();
  await worker(t, f, send).wake();
  assert.equal(server.size, 1);
  assert.equal(ids.join(","), "stable-id,stable-id");
  assert.equal((await f.store.list(alice)).length, 0);
});
test("two workers claim a queued message atomically", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("a"));
  let resolve,
    calls = 0;
  const send = () => {
    calls++;
    return new Promise((r) => (resolve = r));
  };
  const one = worker(t, f, send),
    two = worker(t, f, send);
  const running = one.wake();
  while (!resolve) await new Promise((r) => setImmediate(r));
  await two.wake();
  assert.equal(calls, 1);
  resolve();
  await running;
});
test("a blocked first message preserves order without blocking another room", async (t) => {
  const f = await fixture(t);
  for (const row of [
    entry("a"),
    entry("b"),
    entry("other", { roomId: "other" }),
  ])
    await f.store.enqueue(alice, row);
  const sent = [];
  const w = worker(t, f, async (_, path, method, body) => {
    if (body.request_id === "a")
      throw Object.assign(new Error("No access"), { status: 403 });
    sent.push(body.request_id);
  });
  await w.wake();
  await w.wake();
  assert.equal(sent.join(","), "other");
  assert.equal((await f.store.list(alice))[0].status, "blocked");
  await f.store.discard(alice, "a");
  await w.wake();
  assert.equal(sent.join(","), "other,b");
});
test("rate limits honor Retry-After and network retries back off", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("a"));
  let calls = 0;
  const w = worker(t, f, async () => {
    calls++;
    throw Object.assign(new Error("Rate limit"), {
      status: 429,
      retryAfter: 15,
    });
  });
  await w.wake();
  await w.wake();
  assert.equal(calls, 1);
  f.advance(14999);
  await w.wake();
  assert.equal(calls, 1);
  f.advance(1);
  await w.wake();
  assert.equal(calls, 2);
});
test("AI sends only with an explicit confirmation and never retries automatically", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("ai", { kind: "turn" }));
  let calls = 0;
  const w = worker(t, f, async () => {
    calls++;
    throw new Error("Offline");
  });
  await w.wake();
  assert.equal(calls, 0);
  await w.wake("ai");
  assert.equal(calls, 1);
  assert.equal((await f.store.list(alice))[0].status, "review");
  await w.wake();
  assert.equal(calls, 1);
  await f.store.retry(alice, "ai");
  await w.wake("ai");
  assert.equal(calls, 2);
});
test("paused or stopped workers start no new requests and sending rows cannot be deleted", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("a"));
  let calls = 0;
  const w = worker(t, f, async () => calls++);
  w.setActive(false);
  await w.wake();
  assert.equal(calls, 0);
  await f.store.claim(alice, "a");
  await assert.rejects(f.store.discard(alice, "a"));
  w.stop();
  await w.wake();
  assert.equal(calls, 0);
});
test("one outstanding AI request per room and bounded pending storage preserve inputs", async (t) => {
  const f = await fixture(t);
  await f.store.enqueue(alice, entry("ai", { kind: "turn" }));
  await assert.rejects(f.store.enqueue(alice, entry("ai2", { kind: "turn" })));
  for (let i = 0; i < 99; i++) await f.store.enqueue(alice, entry("m" + i));
  await f.store.saveDraft(alice, "room", "Keep this draft");
  await assert.rejects(f.store.enqueue(alice, entry("overflow")));
  assert.equal(await f.store.getDraft(alice, "room"), "Keep this draft");
});
