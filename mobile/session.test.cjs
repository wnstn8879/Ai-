const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { transformSync } = require("@babel/core");
const code = transformSync(fs.readFileSync("./api.js", "utf8"), {
  plugins: ["@babel/plugin-transform-modules-commonjs"],
  babelrc: false,
  configFile: false,
}).code;
function harness(handler, initial) {
  const storage = new Map(
    initial ? [["storyverse.session.v1", JSON.stringify(initial)]] : [],
  );
  const context = {
    exports: {},
    __DEV__: true,
    process: { env: {} },
    AbortController,
    setTimeout,
    clearTimeout,
    fetch: async (url, options) => {
      const result = await handler(
        url.replace("http://10.0.2.2:8000", ""),
        options,
      );
      return {
        ok: result.status < 400,
        status: result.status,
        json: async () => result.body,
      };
    },
    require: () => ({
      getItemAsync: async (k) => storage.get(k) || null,
      setItemAsync: async (k, v) => storage.set(k, v),
      deleteItemAsync: async (k) => storage.delete(k),
    }),
  };
  vm.runInNewContext(code, context);
  return { api: context.exports, storage };
}
const old = {
  access_token: "old-access",
  refresh_token: "old-refresh",
  user: { id: "alice" },
};
const renewed = {
  access_token: "new-access",
  refresh_token: "new-refresh",
  user: { id: "alice" },
};
test("concurrent expired requests rotate refresh once and persist before retry", async () => {
  let refreshes = 0;
  const { api, storage } = harness(async (path, options) => {
    if (path === "/auth/refresh") {
      refreshes++;
      assert.equal(JSON.parse(options.body).refresh_token, "old-refresh");
      await new Promise((r) => setTimeout(r, 10));
      return { status: 200, body: renewed };
    }
    return options.headers.Authorization === "Bearer new-access"
      ? { status: 200, body: ["private"] }
      : { status: 401, body: {} };
  }, old);
  await api.restoreSession();
  const result = await Promise.all([
    api.request("/rooms"),
    api.request("/rooms"),
  ]);
  assert.equal(refreshes, 1);
  assert.equal(result[0][0], "private");
  assert.equal(
    JSON.parse(storage.get("storyverse.session.v1")).refresh_token,
    "new-refresh",
  );
});
test("revoked refresh clears secure storage and notifies app", async () => {
  let expired = 0;
  const { api, storage } = harness(
    async () => ({ status: 401, body: {} }),
    old,
  );
  api.onExpired(() => expired++);
  await api.restoreSession();
  await assert.rejects(api.request("/rooms"));
  assert.equal(storage.size, 0);
  assert.equal(expired, 1);
  await assert.rejects(api.accessToken());
});
test("logout revokes session before clearing and second account uses own token", async () => {
  const calls = [];
  const bob = {
    access_token: "bob",
    refresh_token: "bob-refresh",
    user: { id: "bob" },
  };
  const { api, storage } = harness(async (path, options) => {
    calls.push([path, options.headers.Authorization]);
    return { status: 200, body: path === "/auth/login" ? bob : { ok: true } };
  }, old);
  await api.restoreSession();
  await api.logout();
  assert.equal(storage.size, 0);
  await assert.rejects(api.accessToken());
  await api.authenticate(false, {
    email: "bob@example.com",
    password: "long-password",
  });
  await api.request("/rooms");
  assert.equal(calls[0][1], "Bearer old-access");
  assert.equal(calls.at(-1)[1], "Bearer bob");
});
test("network failure preserves recoverable session", async () => {
  const { api, storage } = harness(async () => {
    throw new TypeError("offline");
  }, old);
  await api.restoreSession();
  await assert.rejects(api.request("/rooms"));
  assert.equal(storage.size, 1);
});
