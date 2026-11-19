const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { transformSync } = require("@babel/core");
const code = transformSync(fs.readFileSync("./liveRoom.js", "utf8"), {
  plugins: ["@babel/plugin-transform-modules-commonjs"],
  babelrc: false,
  configFile: false,
}).code;
function setup(getToken = async () => "token") {
  const context = { exports: {}, setTimeout, clearTimeout };
  vm.runInNewContext(code, context);
  const sockets = [],
    timers = new Map(),
    snapshots = [],
    statuses = [];
  let next = 0,
    denied = 0;
  class Socket {
    constructor() {
      this.readyState = 0;
      this.sent = [];
      sockets.push(this);
    }
    send(data) {
      this.sent.push(data);
    }
    close() {
      this.readyState = 3;
      this.onclose?.({ code: 1000 });
    }
    open() {
      this.readyState = 1;
      this.onopen();
    }
    snapshot(room) {
      this.onmessage({ data: JSON.stringify({ type: "snapshot", room }) });
    }
    disconnect(code = 1006) {
      this.readyState = 3;
      this.onclose({ code });
    }
  }
  const control = context.exports.connectLiveRoom({
    url: "wss://example.invalid/live",
    getToken,
    onSnapshot: (r) => snapshots.push(r),
    onStatus: (s) => statuses.push(s),
    onDenied: () => denied++,
    WebSocketImpl: Socket,
    schedule: (fn, delay) => {
      const id = ++next;
      timers.set(id, { fn, delay });
      return id;
    },
    cancel: (id) => timers.delete(id),
  });
  return {
    control,
    sockets,
    timers,
    snapshots,
    statuses,
    get denied() {
      return denied;
    },
    retry() {
      const [id, item] = timers.entries().next().value;
      timers.delete(id);
      item.fn();
    },
  };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
test("foreground events while connecting create one socket and authenticate once", async () => {
  let resolve;
  const h = setup(() => new Promise((r) => (resolve = r)));
  h.control.resume();
  h.control.resume();
  assert.equal(h.sockets.length, 0);
  resolve("secret");
  await tick();
  assert.equal(h.sockets.length, 1);
  h.control.resume();
  assert.equal(h.sockets.length, 1);
  h.sockets[0].open();
  assert.equal(JSON.parse(h.sockets[0].sent[0]).access_token, "secret");
  h.control.stop();
});
test("reconnect backs off until authenticated snapshot and ignores replaced callbacks", async () => {
  const h = setup();
  await tick();
  const old = h.sockets[0];
  old.open();
  old.disconnect();
  assert.equal([...h.timers.values()][0].delay, 1000);
  h.retry();
  await tick();
  const second = h.sockets[1];
  second.open();
  second.disconnect();
  assert.equal([...h.timers.values()][0].delay, 2000);
  old.snapshot({ id: "stale" });
  assert.equal(h.snapshots.length, 0);
  h.retry();
  await tick();
  const third = h.sockets[2];
  third.open();
  third.snapshot({ id: "current" });
  assert.equal(h.snapshots[0].id, "current");
  third.disconnect();
  assert.equal([...h.timers.values()][0].delay, 1000);
  h.control.stop();
});
test("stopping cancels retry and prevents delayed token from opening a socket", async () => {
  let resolve;
  const h = setup(() => new Promise((r) => (resolve = r)));
  h.control.stop();
  resolve("late");
  await tick();
  assert.equal(h.sockets.length, 0);
  const other = setup();
  await tick();
  other.sockets[0].open();
  other.sockets[0].disconnect();
  other.control.stop();
  assert.equal(other.timers.size, 0);
});
test("membership denial stops reconnect while healthy resume requests a sync", async () => {
  const h = setup();
  await tick();
  h.sockets[0].open();
  h.control.resume();
  assert.equal(h.sockets[0].sent.at(-1), "sync");
  h.sockets[0].disconnect(4403);
  h.control.resume();
  await tick();
  assert.equal(h.denied, 1);
  assert.equal(h.sockets.length, 1);
  assert.equal(h.timers.size, 0);
});
