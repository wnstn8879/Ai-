const { test } = require("node:test");
const assert = require("node:assert/strict");
const { DatabaseSync } = require("node:sqlite");
const { mkdtempSync, readFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const vm = require("node:vm");
const { transformSync } = require("@babel/core");
function load(file, modules = {}) {
  const context = {
    exports: {},
    require: (name) => {
      if (!modules[name]) throw Error(name);
      return modules[name];
    },
  };
  vm.runInNewContext(
    transformSync(readFileSync(file, "utf8"), {
      plugins: ["@babel/plugin-transform-modules-commonjs"],
      babelrc: false,
      configFile: false,
    }).code,
    context,
  );
  return context.exports;
}
const commute = load("./commuteStory.js");
const story = load("./offlineStory.js", { "./commuteStory": commute });
const { createOfflineStore } = load("./offlineStore.js", {
  "./offlineStory": story,
  "./commuteStory": commute,
});
const plain = (value) => JSON.parse(JSON.stringify(value));
async function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), "storyverse-preview-"));
  const path = join(dir, "preview.db");
  let db,
    store,
    serial = 0,
    fail = false;
  function connect() {
    db = new DatabaseSync(path);
    const adapter = {
      execAsync: async (sql) => db.exec(sql),
      getFirstAsync: async (sql, ...params) => db.prepare(sql).get(...params),
      getAllAsync: async (sql, ...params) => db.prepare(sql).all(...params),
      runAsync: async (sql, ...params) => {
        if (fail && sql.startsWith("DELETE FROM preview_drafts"))
          throw Error("disk failure");
        return db.prepare(sql).run(...params);
      },
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
    };
    store = createOfflineStore(
      adapter,
      () => `id-${++serial}`,
      () => new Date(1700000000000 + serial * 1000).toISOString(),
    );
    return store.initialize();
  }
  await connect();
  t.after(() => {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return {
    get store() {
      return store;
    },
    fail: (value) => (fail = value),
    restart: async () => {
      db.close();
      await connect();
    },
  };
}
test("offline history, state, checkpoints and drafts survive actual SQLite reopening", async (t) => {
  const f = await fixture(t);
  const room = await f.store.create(1);
  const played = await f.store.send(room.id, "봉투를 열어본다");
  const save = await f.store.save(room.id, "퇴근길에 계속");
  await f.store.saveDraft(null, room.id, "아직 보내지 않은 행동");
  await f.restart();
  assert.deepEqual(plain(await f.store.get(room.id)), plain(played));
  assert.equal((await f.store.saves(room.id))[0].id, save.id);
  assert.equal(await f.store.getDraft(null, room.id), "아직 보내지 않은 행동");
  assert.equal((await f.store.list()).length, 1);
});
test("every message can fork with pinned state and original history remains independent", async (t) => {
  const f = await fixture(t);
  let parent = await f.store.create(1);
  parent = await f.store.send(parent.id, "봉투를 열어본다");
  parent = await f.store.send(parent.id, "역무원에게 간다");
  for (let i = 0; i <= parent.messages.length; i++) {
    const child = await f.store.fork(parent.id, i);
    assert.equal(child.parentId, parent.id);
    assert.equal(child.forkIndex, i);
    assert.deepEqual(plain(child.messages), plain(parent.messages.slice(0, i)));
    assert.deepEqual(
      plain(child.state),
      plain(
        i ? parent.messages[i - 1].stateAfter : { scene: 0, ending: false },
      ),
    );
    await f.store.send(child.id, "다른 선택");
    assert.deepEqual(plain(await f.store.get(parent.id)), plain(parent));
  }
});
test("checkpoint resumes pinned history even after original advances", async (t) => {
  const f = await fixture(t);
  const r = await f.store.create(1);
  const checkpoint = await f.store.save(r.id);
  await f.store.send(r.id, "주변을 살핀다");
  const child = await f.store.resume(checkpoint.id);
  assert.equal(child.messages.length, 1);
  assert.equal(child.state.scene, 0);
  assert.equal((await f.store.get(r.id)).messages.length, 3);
});
test("sending and removing the matching draft are atomic and failure preserves both", async (t) => {
  const f = await fixture(t);
  const r = await f.store.create(1);
  await f.store.saveDraft(null, r.id, " 봉투를 연다 ");
  f.fail(true);
  await assert.rejects(f.store.send(r.id, "봉투를 연다"), /disk failure/);
  assert.equal((await f.store.get(r.id)).messages.length, 1);
  assert.equal(await f.store.getDraft(null, r.id), " 봉투를 연다 ");
  f.fail(false);
  await f.store.send(r.id, "봉투를 연다");
  await f.restart();
  assert.equal(await f.store.getDraft(null, r.id), "");
  assert.equal((await f.store.get(r.id)).messages.length, 3);
});
test("a chosen action never deletes a different typed draft", async (t) => {
  const f = await fixture(t);
  const r = await f.store.create(1);
  await f.store.saveDraft(null, r.id, "내가 따로 적은 행동");
  await f.store.send(r.id, "봉투를 열어본다");
  assert.equal(await f.store.getDraft(null, r.id), "내가 따로 적은 행동");
});
test("concurrent requests append in order without losing a turn", async (t) => {
  const f = await fixture(t);
  const r = await f.store.create(1);
  await Promise.all([
    f.store.send(r.id, "첫 행동"),
    f.store.send(r.id, "두번째 행동"),
  ]);
  const saved = await f.store.get(r.id);
  assert.deepEqual(
    plain(saved.messages.filter((m) => m.actor === "나").map((m) => m.content)),
    ["첫 행동", "두번째 행동"],
  );
  assert.equal(saved.state.scene, 2);
});
test("invalid positions or empty actions cannot create partial branches or turns", async (t) => {
  const f = await fixture(t);
  const r = await f.store.create(1);
  for (const index of [-1, 2, 0.5])
    await assert.rejects(f.store.fork(r.id, index));
  await assert.rejects(f.store.send(r.id, "   "));
  assert.equal((await f.store.list()).length, 1);
  assert.equal((await f.store.get(r.id)).messages.length, 1);
});
test("short authored endings allow continuing and different choices at the same point", async (t) => {
  const f = await fixture(t);
  let r = await f.store.create(1);
  for (let i = 0; i < 3; i++) r = await f.store.send(r.id, "계속");
  const child = await f.store.fork(r.id, r.messages.length);
  const a = await f.store.send(r.id, "편지를 받아 읽는다");
  const b = await f.store.send(child.id, "오늘은 일상으로 돌아간다");
  assert.equal(a.state.ending, true);
  assert.equal(b.state.ending, true);
  assert.notEqual(a.messages.at(-1).content, b.messages.at(-1).content);
  const next = await f.store.send(a.id, story.choicesFor(a)[0]);
  assert.equal(next.state.ending, false);
  assert.equal(next.messages.length, a.messages.length + 2);
});

test("new mystery has distinct endings within at most four explicit choices", () => {
  const base = story.opening("new", "Mystery", "now", 2);
  const outcomes = new Set();
  let endings = 0;
  function explore(room, depth) {
    if (room.state.ending) {
      assert.ok(depth <= 4);
      assert.equal(story.choicesFor(room).length, 0);
      outcomes.add(room.state.outcome);
      endings++;
      return;
    }
    const choices = story.choicesFor(room);
    assert.equal(choices.length, 2);
    for (const choice of choices)
      explore(story.advance(room, choice, `step-${depth}`, "later"), depth + 1);
  }
  explore(base, 0);
  assert.equal(outcomes.size, 4);
  assert.equal(endings, 12);
  assert.equal(base.messages.length, 1);
});
test("unknown free input is preserved without inventing a choice or advancing state", () => {
  const base = story.opening("new", "Mystery", "now", 2);
  const result = story.advance(base, "나만의 전혀 다른 행동", "a", "later");
  assert.deepEqual(plain(result.state), plain(base.state));
  assert.equal(result.messages[1].content, "나만의 전혀 다른 행동");
  assert.match(result.messages[2].content, /확정하지 않았습니다/);
});
test("new story checkpoint and zero-point fork restore clues exactly across restart", async (t) => {
  const f = await fixture(t);
  let r = await f.store.create();
  assert.equal(r.storyVersion, 2);
  r = await f.store.send(r.id, story.choicesFor(r)[0]);
  r = await f.store.send(r.id, story.choicesFor(r)[1]);
  assert.ok(r.state.clues.includes("주인 확인"));
  const point = await f.store.save(r.id);
  await f.store.send(r.id, story.choicesFor(r)[1]);
  await f.restart();
  const restored = await f.store.resume(point.id);
  assert.deepEqual(plain(restored.state), plain(r.state));
  assert.equal(restored.messages.length, r.messages.length);
  const empty = await f.store.fork(r.id, 0);
  assert.deepEqual(plain(empty.state), plain(commute.initialState()));
  assert.equal((await f.store.get(r.id)).state.ending, true);
});
test("legacy story remains playable while new stories default to version two", async (t) => {
  const f = await fixture(t);
  const old = await f.store.create(1);
  await f.restart();
  const continued = await f.store.send(old.id, "계속");
  assert.equal(continued.storyVersion, undefined);
  assert.equal(continued.state.scene, 1);
  assert.equal((await f.store.create()).storyVersion, 2);
  const recap = story.brief(continued);
  assert.equal(recap.savedAt, continued.updatedAt);
  assert.ok(recap.recap.length > 0);
});
