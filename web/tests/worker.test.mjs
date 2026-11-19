import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { handle } from "../worker/worker.js";
import { PAGE } from "../worker/page.js";

test("deployment bundle resolves its page without external runtime modules", async () => {
  execFileSync(process.execPath, ["scripts/build.mjs"], {
    cwd: new URL("..", import.meta.url),
  });
  const built = await import("../dist/server/index.js");
  const response = await built.default.fetch(
    new Request("https://imagine.test/", {
      headers: { "oai-authenticated-user-id": "test-owner" },
    }),
    {},
  );
  assert.equal(response.status, 200);
  assert.equal(await response.text(), PAGE);
});
function database() {
  const sql = new DatabaseSync(":memory:");
  sql.exec(
    readFileSync(
      new URL("../drizzle/0000_chunky_roland_deschain.sql", import.meta.url),
      "utf8",
    ).replaceAll("--> statement-breakpoint", ""),
  );
  const adapter = {
    prepare(query) {
      let params = [];
      return {
        bind(...p) {
          params = p;
          return this;
        },
        async first() {
          return sql.prepare(query).get(...params) || null;
        },
        async all() {
          return { results: sql.prepare(query).all(...params) };
        },
        async run() {
          const r = sql.prepare(query).run(...params);
          return { meta: { changes: Number(r.changes) } };
        },
      };
    },
    async batch(stmts) {
      const out = [];
      sql.exec("BEGIN");
      try {
        for (const s of stmts) out.push(await s.run());
        sql.exec("COMMIT");
        return out;
      } catch (e) {
        sql.exec("ROLLBACK");
        throw e;
      }
    },
  };
  return adapter;
}
const secret = "test-relay-secret-which-is-long-enough-for-tests";
const req = (path, user, method = "GET", body) =>
  new Request("https://imagine.test" + path, {
    method,
    headers: {
      ...(user ? { "oai-authenticated-user-id": user } : {}),
      ...(body
        ? { "content-type": "application/json", origin: "https://imagine.test" }
        : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
const agent = (path, body = {}) =>
  new Request("https://imagine.test" + path, {
    method: "POST",
    headers: {
      "x-imagine-relay-key": secret,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
test("real inline browser JS parses and handles untrusted content as text", () => {
  new Function(PAGE.match(/<script>([\s\S]*)<\/script>/)[1]);
  assert.ok(!PAGE.includes("innerHTML"));
  assert.ok(PAGE.includes("이 장면을 다른 방향으로"));
});
test("anonymous browser and missing service secret cannot read stored stories or claim jobs", async () => {
  const env = { DB: database(), RELAY_KEY: secret };
  assert.equal((await handle(req("/api/rooms"), env)).status, 401);
  assert.equal(
    (await handle(req("/relay/poll", null, "POST", {}), env)).status,
    401,
  );
  assert.equal((await handle(req("/"), env)).status, 302);
});
test("durable fallback reading stays scoped per visitor while generation stays offline", async () => {
  const DB = database(),
    env = { DB, RELAY_KEY: secret };
  await DB.prepare("INSERT INTO story_cache VALUES(?,?,?,?,?)")
    .bind(
      JSON.stringify(["alice", "/rooms"]),
      "alice",
      "/rooms",
      JSON.stringify([{ id: "private" }]),
      Date.now(),
    )
    .run();
  assert.equal((await handle(req("/api/rooms", "alice"), env)).status, 200);
  assert.deepEqual(
    await (await handle(req("/api/rooms", "alice"), env)).json(),
    [{ id: "private" }],
  );
  assert.equal((await handle(req("/api/rooms", "bob"), env)).status, 503);
  assert.equal(
    (await handle(req("/api/rooms", "alice", "POST", { title: "x" }), env))
      .status,
    503,
  );
});
test("relay claims jobs once and caches only for the authenticated job visitor", async () => {
  const DB = database(),
    env = { DB, RELAY_KEY: secret };
  await DB.prepare(
    "INSERT INTO relay_requests(id,visitor,path,method,status,created,expires) VALUES(?,?,?,?,?,?,?)",
  )
    .bind(
      "job",
      "alice",
      "/rooms",
      "GET",
      "pending",
      Date.now(),
      Date.now() + 60000,
    )
    .run();
  const jobs = await (await handle(agent("/relay/poll"), env)).json();
  assert.equal(jobs.jobs.length, 1);
  assert.equal(
    (await (await handle(agent("/relay/poll"), env)).json()).jobs.length,
    0,
  );
  assert.equal(
    (
      await handle(
        agent("/relay/complete", {
          id: "job",
          status: 200,
          data: [{ id: "book" }],
        }),
        env,
      )
    ).status,
    200,
  );
  const cache = await DB.prepare("SELECT * FROM story_cache WHERE visitor=?")
    .bind("alice")
    .first();
  assert.ok(cache.payload.includes("book"));
  assert.equal(
    await DB.prepare("SELECT * FROM story_cache WHERE visitor=?")
      .bind("bob")
      .first(),
    null,
  );
});
test("cross-origin writes are rejected before backend work", async () => {
  const env = { DB: database(), RELAY_KEY: secret };
  const request = new Request("https://imagine.test/api/rooms", {
    method: "POST",
    headers: {
      "oai-authenticated-user-id": "alice",
      origin: "https://evil.example",
      "content-type": "application/json",
    },
    body: "{}",
  });
  assert.equal((await handle(request, env)).status, 403);
});
test("long generations return durable task ids and repeat submissions reuse the same task", async () => {
  const DB = database(),
    env = { DB, RELAY_KEY: secret };
  await handle(agent("/relay/poll"), env);
  const body = {
    content: "새로운 장면",
    request_id: "same-request",
    actor: "작가",
  };
  const a = await handle(
    req("/api/rooms/book-id/turns", "alice", "POST", body),
    env,
  );
  assert.equal(a.status, 202);
  const task = (await a.json()).task;
  assert.equal(
    (
      await (
        await handle(
          req("/api/rooms/book-id/turns", "alice", "POST", body),
          env,
        )
      ).json()
    ).task,
    task,
  );
  assert.equal(
    (await handle(req("/api/tasks/" + task, "bob"), env)).status,
    404,
  );
  assert.equal(
    (await (await handle(req("/api/tasks/" + task, "alice"), env)).json()).done,
    false,
  );
  const jobs = await (await handle(agent("/relay/poll"), env)).json();
  assert.equal(jobs.jobs.length, 1);
  await handle(
    agent("/relay/complete", {
      id: task,
      status: 200,
      data: { ai_message: { content: "새 장면" } },
      cache_updates: [],
    }),
    env,
  );
  const result = await (
    await handle(req("/api/tasks/" + task, "alice"), env)
  ).json();
  assert.equal(result.done, true);
  assert.equal(result.data.ai_message.content, "새 장면");
});

test("reader pagination query and memory routes reach authenticated work without exposing another visitor", async () => {
  const DB = database(),
    env = { DB, RELAY_KEY: secret };
  await handle(agent("/relay/poll"), env);
  const r = await handle(
    req("/api/rooms/book/chapters?before_position=90", "alice"),
    env,
  );
  assert.equal(r.status, 202);
  const search = await handle(
    req("/api/rooms/book/memory/search", "alice", "POST", {
      query: "은빛 나침반",
    }),
    env,
  );
  assert.equal(search.status, 202);
  const jobs = await (await handle(agent("/relay/poll"), env)).json();
  assert.ok(
    jobs.jobs.some((j) => j.path === "/rooms/book/chapters?before_position=90"),
  );
  assert.equal(
    (
      await handle(
        req("/api/rooms/book/memory/search", null, "POST", { query: "나침반" }),
        env,
      )
    ).status,
    401,
  );
});
