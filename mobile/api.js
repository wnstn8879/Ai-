import * as SecureStore from "expo-secure-store";
export const API = process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000";
const KEY = "storyverse.session.v1";
let session = null;
let refreshPromise = null;
let expired = () => {};
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
      throw Object.assign(new Error(message), { status: response.status });
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
async function persist(value) {
  await SecureStore.setItemAsync(KEY, JSON.stringify(value));
  session = value;
  return value;
}
export async function clearSession() {
  session = null;
  await SecureStore.deleteItemAsync(KEY);
}
export async function restoreSession() {
  const saved = await SecureStore.getItemAsync(KEY);
  if (!saved) return null;
  try {
    session = JSON.parse(saved);
  } catch {
    await clearSession();
    return null;
  }
  return session;
}
export async function authenticate(register, body) {
  return persist(
    await raw(register ? "/auth/register" : "/auth/login", "POST", body),
  );
}
export async function accessToken() {
  if (!session) throw new Error("로그인이 필요합니다.");
  return session.access_token;
}
async function refresh() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      if (!session) throw new Error("로그인이 필요합니다.");
      try {
        return await persist(
          await raw("/auth/refresh", "POST", {
            refresh_token: session.refresh_token,
          }),
        );
      } catch (e) {
        if (e.status === 401) {
          await clearSession();
          expired();
        }
        throw e;
      }
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}
export async function request(path, method = "GET", body) {
  try {
    return await raw(path, method, body, await accessToken());
  } catch (e) {
    if (e.status !== 401) throw e;
    await refresh();
    return raw(path, method, body, await accessToken());
  }
}
export async function logout() {
  await request("/auth/logout", "POST");
  await clearSession();
}
