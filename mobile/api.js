import * as SecureStore from "expo-secure-store";
export const API = (
  process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000"
).replace(/\/+$/, "");
const KEY = "storyverse.session.v1";
let session = null;
let refreshPromise = null;
let expired = () => {};
let generation = 0;
let storageQueue = Promise.resolve();
const sessionChanged = () =>
  Object.assign(
    new Error("계정이 변경되었습니다. 현재 계정에서 다시 시도해주세요."),
    { code: "SESSION_CHANGED" },
  );
function assertGeneration(expected) {
  if (expected !== generation || !session) throw sessionChanged();
}
function storage(action) {
  const next = storageQueue.then(action);
  storageQueue = next.catch(() => {});
  return next;
}
export function onExpired(callback) {
  expired = callback;
}
async function raw(path, method = "GET", body, token) {
  if (!__DEV__ && !API.startsWith("https://"))
    throw new Error("앱 배포에는 HTTPS 서버 주소가 필요합니다.");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(API + path, {
      method,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message =
        response.status === 401
          ? path === "/auth/login"
            ? "이메일 또는 비밀번호를 확인해주세요."
            : "로그인이 만료되었습니다. 다시 로그인해주세요."
          : response.status === 409
            ? "요청이 중복되었거나 이야기가 변경되었습니다. 새로고침 후 확인해주세요."
            : response.status === 404
              ? "접근할 수 없거나 존재하지 않는 항목입니다."
              : response.status === 429
                ? "요청이 많습니다. 잠시 후 다시 시도해주세요."
                : response.status >= 500
                  ? "서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요."
                  : typeof data.detail === "string"
                    ? data.detail
                    : "입력 내용을 확인해주세요.";
      throw Object.assign(new Error(message), {
        status: response.status,
        retryAfter: Number(response.headers?.get?.("Retry-After")) || undefined,
      });
    }
    return data;
  } catch (e) {
    if (e.name === "AbortError")
      throw new Error(
        "응답 시간이 초과되었습니다. 연결을 확인하고 다시 시도해주세요.",
      );
    if (e instanceof TypeError)
      throw new Error("서버에 연결할 수 없습니다. 네트워크를 확인해주세요.");
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}
function validSession(value) {
  return (
    value &&
    typeof value.access_token === "string" &&
    value.access_token.length > 0 &&
    typeof value.refresh_token === "string" &&
    value.refresh_token.length > 0 &&
    typeof value.user?.id === "string"
  );
}
async function persist(value, expected) {
  if (!validSession(value))
    throw new Error("로그인 정보를 확인할 수 없습니다.");
  await storage(async () => {
    if (expected !== generation) throw sessionChanged();
    await SecureStore.setItemAsync(KEY, JSON.stringify(value));
  });
  if (expected !== generation) throw sessionChanged();
  session = value;
  return value;
}
export async function clearSession() {
  const own = ++generation;
  session = null;
  refreshPromise = null;
  await storage(() => SecureStore.deleteItemAsync(KEY));
  return own;
}
export async function restoreSession() {
  const expected = generation;
  const saved = await storage(() => SecureStore.getItemAsync(KEY));
  if (expected !== generation) throw sessionChanged();
  if (!saved) return null;
  let parsed;
  try {
    parsed = JSON.parse(saved);
  } catch {
    parsed = null;
  }
  if (!validSession(parsed)) {
    await clearSession();
    return null;
  }
  session = parsed;
  return parsed;
}
export async function authenticate(register, body) {
  const expected = await clearSession();
  if (expected !== generation) throw sessionChanged();
  return persist(
    await raw(register ? "/auth/register" : "/auth/login", "POST", body),
    expected,
  );
}
export async function accessToken() {
  if (!session) throw new Error("로그인이 필요합니다.");
  return session.access_token;
}
async function refresh() {
  if (refreshPromise) return refreshPromise;
  const expected = generation;
  const source = session;
  if (!source) throw new Error("로그인이 필요합니다.");
  const task = (async () => {
    try {
      return await persist(
        await raw("/auth/refresh", "POST", {
          refresh_token: source.refresh_token,
        }),
        expected,
      );
    } catch (e) {
      if (
        e.status === 401 &&
        expected === generation &&
        session?.refresh_token === source.refresh_token
      ) {
        try {
          await clearSession();
        } finally {
          expired();
        }
      }
      throw e;
    }
  })().finally(() => {
    if (refreshPromise === task) refreshPromise = null;
  });
  refreshPromise = task;
  return task;
}
export async function request(path, method = "GET", body, expectedUserId) {
  if (expectedUserId && session?.user.id !== expectedUserId)
    throw sessionChanged();
  const expected = generation;
  const original = await accessToken();
  assertGeneration(expected);
  try {
    const result = await raw(path, method, body, original);
    assertGeneration(expected);
    return result;
  } catch (e) {
    assertGeneration(expected);
    if (e.status !== 401) throw e;
    // A late 401 from the previous token must not rotate a fresh token again.
    if (session.access_token === original) await refresh();
    assertGeneration(expected);
    const result = await raw(path, method, body, await accessToken());
    assertGeneration(expected);
    return result;
  }
}
export async function logout() {
  const expected = generation;
  await request("/auth/logout", "POST");
  if (expected === generation) await clearSession();
}

export function requestForUser(userId, path, method = "GET", body) {
  return request(path, method, body, userId);
}
