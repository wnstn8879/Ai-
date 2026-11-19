import { PAGE } from "./page.js";
const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
const route =
  /^\/(library|rooms(?:\/[A-Za-z0-9-]+(?:\/(?:turns|forks|rewrite|saves|state|members|chapters|writer(?:\/(?:start|pause|keepalive|direction))?|memory\/(?:index|search)))?)?|saves\/[A-Za-z0-9-]+\/resume)$/;
const cacheKey = (visitor, path) => JSON.stringify([visitor, path]);
async function secure(request, env) {
  const key = request.headers.get("x-imagine-relay-key") || "";
  if (!env.RELAY_KEY || key.length > 256 || key.length < 32) return false;
  const hash = async (text) =>
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    );
  const a = await hash(key),
    b = await hash(env.RELAY_KEY);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}
async function cached(db, visitor, path) {
  const r = await db
    .prepare("SELECT payload,updated FROM story_cache WHERE key=?")
    .bind(cacheKey(visitor, path))
    .first();
  return r
    ? json(JSON.parse(r.payload), 200)
    : json(
        { detail: "AI 서버 연결을 준비 중입니다. 잠시 후 다시 시도해주세요." },
        503,
      );
}
export async function handle(request, env) {
  const url = new URL(request.url),
    db = env.DB;
  if (url.pathname.startsWith("/relay/")) {
    if (!db || !(await secure(request, env)))
      return json({ detail: "Unauthorized" }, 401);
    if (request.method !== "POST")
      return json({ detail: "Method not allowed" }, 405);
    if (url.pathname === "/relay/poll") {
      const now = Date.now();
      await db
        .prepare(
          "INSERT INTO relay_health(id,updated) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated",
        )
        .bind("agent", now)
        .run();
      const rows = await db
        .prepare(
          "SELECT id,visitor,path,method,body FROM relay_requests WHERE status='pending' AND expires>? ORDER BY created LIMIT 4",
        )
        .bind(now)
        .all();
      const jobs = [];
      for (const row of rows.results) {
        const claim = await db
          .prepare(
            "UPDATE relay_requests SET status='running' WHERE id=? AND status='pending'",
          )
          .bind(row.id)
          .run();
        if (claim.meta.changes) jobs.push(row);
      }
      return json({ jobs });
    }
    if (url.pathname === "/relay/complete") {
      const body = await request.json();
      const job = await db
        .prepare("SELECT * FROM relay_requests WHERE id=? AND status='running'")
        .bind(body.id)
        .first();
      if (!job) return json({ detail: "Unknown job" }, 404);
      if (
        !Number.isInteger(body.status) ||
        body.status < 200 ||
        body.status > 599
      )
        return json({ detail: "Invalid response" }, 400);
      const payload = JSON.stringify(body.data);
      if (payload.length > 2000000)
        return json({ detail: "Response too large" }, 413);
      const statements = [
        db
          .prepare(
            "UPDATE relay_requests SET status='done',response=?,http_status=? WHERE id=? AND status='running'",
          )
          .bind(payload, body.status, body.id),
      ];
      for (const item of (body.cache_updates || []).slice(0, 6)) {
        if (
          !route.test(item.path.split("?")[0]) ||
          item.path.includes("/turns") ||
          JSON.stringify(item.data).length > 2000000
        )
          continue;
        statements.push(
          db
            .prepare(
              "INSERT INTO story_cache(key,visitor,path,payload,updated) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
            )
            .bind(
              cacheKey(job.visitor, item.path),
              job.visitor,
              item.path,
              JSON.stringify(item.data),
              Date.now(),
            ),
        );
      }
      if (job.method === "GET" && body.status === 200)
        statements.push(
          db
            .prepare(
              "INSERT INTO story_cache(key,visitor,path,payload,updated) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
            )
            .bind(
              cacheKey(job.visitor, job.path),
              job.visitor,
              job.path,
              payload,
              Date.now(),
            ),
        );
      await db.batch(statements);
      return json({ ok: true });
    }
    return json({ detail: "Not found" }, 404);
  }
  const visitor = request.headers.get("oai-authenticated-user-id");
  if (!visitor)
    return request.url.includes("/api/")
      ? json({ detail: "로그인이 필요합니다." }, 401)
      : Response.redirect(
          url.origin + "/signin-with-chatgpt?return_to=%2F",
          302,
        );
  if (url.pathname.startsWith("/api/tasks/")) {
    if (request.method !== "GET")
      return json({ detail: "Method not allowed" }, 405);
    if (!db) return json({ detail: "저장 서비스 연결을 확인해주세요." }, 503);
    const id = url.pathname.split("/").pop();
    const job = await db
      .prepare(
        "SELECT status,response,http_status FROM relay_requests WHERE id=? AND visitor=?",
      )
      .bind(id, visitor)
      .first();
    if (!job) return json({ detail: "요청을 찾을 수 없습니다." }, 404);
    return job.status === "done"
      ? json({
          done: true,
          status: job.http_status,
          data: JSON.parse(job.response),
        })
      : json({ done: false });
  }
  if (url.pathname === "/api/status") {
    const health = db
      ? await db
          .prepare("SELECT updated FROM relay_health WHERE id=?")
          .bind("agent")
          .first()
      : null;
    const key = Array.from(
      new Uint8Array(
        await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(visitor),
        ),
      ),
    )
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
    return json({
      online: !!health && Date.now() - health.updated < 20000,
      viewerKey: key,
    });
  }
  if (url.pathname.startsWith("/api/")) {
    if (!db) return json({ detail: "저장 서비스를 준비 중입니다." }, 503);
    const path = url.pathname.slice(4) + url.search;
    if (!route.test(url.pathname.slice(4)))
      return json({ detail: "Not found" }, 404);
    if (!["GET", "POST", "PUT"].includes(request.method))
      return json({ detail: "Method not allowed" }, 405);
    if (
      request.method !== "GET" &&
      (request.headers.get("origin") !== url.origin ||
        !(request.headers.get("content-type") || "").includes(
          "application/json",
        ))
    )
      return json({ detail: "Invalid request origin" }, 403);
    const health = await db
      .prepare("SELECT updated FROM relay_health WHERE id=?")
      .bind("agent")
      .first();
    if (!health || Date.now() - health.updated > 20000)
      return request.method === "GET"
        ? cached(db, visitor, path)
        : json(
            {
              detail:
                "AI 서버가 쉬고 있습니다. 저장된 작품은 읽을 수 있으며, 생성은 서버 연결 후 가능합니다.",
            },
            503,
          );
    const body = request.method === "GET" ? null : await request.text();
    if (body && new TextEncoder().encode(body).length > 70000)
      return json({ detail: "입력이 너무 깁니다." }, 413);
    let old;
    if (body && path.endsWith("/turns")) {
      try {
        if (JSON.parse(body).request_id)
          old = await db
            .prepare(
              "SELECT id,status,response,http_status,expires FROM relay_requests WHERE visitor=? AND path=? AND body=? AND created>? ORDER BY created DESC LIMIT 1",
            )
            .bind(visitor, path, body, Date.now() - 600000)
            .first();
      } catch (_) {}
    }
    if (
      old &&
      ((old.status === "done" && old.http_status >= 400) ||
        (old.status !== "done" && old.expires <= Date.now()))
    )
      old = null;
    if (old)
      return old.status === "done"
        ? json(JSON.parse(old.response), old.http_status)
        : json({ task: old.id }, 202);
    const count = await db
      .prepare(
        "SELECT count(*) AS n FROM relay_requests WHERE visitor=? AND status IN ('pending','running') AND expires>?",
      )
      .bind(visitor, Date.now())
      .first();
    if (count.n >= 6)
      return json(
        { detail: "진행 중인 요청이 있습니다. 잠시 기다려주세요." },
        429,
      );
    const id = crypto.randomUUID(),
      now = Date.now();
    await db
      .prepare("DELETE FROM relay_requests WHERE created<?")
      .bind(now - 86400000)
      .run();
    await db
      .prepare(
        "INSERT INTO relay_requests(id,visitor,path,method,body,status,created,expires) VALUES(?,?,?,?,?,?,?,?)",
      )
      .bind(
        id,
        visitor,
        path,
        request.method,
        body,
        "pending",
        now,
        now + 240000,
      )
      .run();
    return json({ task: id }, 202);
  }
  if (url.pathname !== "/" && url.pathname !== "/library")
    return new Response("Not found", { status: 404 });
  return new Response(PAGE, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "same-origin",
      "Content-Security-Policy":
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://chatgpt.com",
    },
  });
}
export default { fetch: handle };
