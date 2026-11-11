// No credentials are stored here. Every read/write is scoped to server + account + room.
export function createOutboxStore(db, now = () => Date.now()) {
  let chain = Promise.resolve();
  const serial = (fn) => {
    const next = chain.then(fn);
    chain = next.catch(() => {});
    return next;
  };
  const keys = (scope) => {
    if (!scope?.api || !scope?.userId) throw new Error("로그인이 필요합니다.");
    return [scope.api, scope.userId];
  };
  const transaction = (fn) => db.withExclusiveTransactionAsync(fn);
  const item = (row) =>
    row && {
      ...row,
      kind: row.kind,
      requestId: row.request_id,
      roomId: row.room_id,
      roomTitle: row.room_title,
      nextAttemptAt: row.next_attempt_at,
      lastError: row.last_error,
    };
  const get = (tx, scope, id) =>
    tx.getFirstAsync(
      "SELECT * FROM outbox WHERE api=? AND user_id=? AND request_id=?",
      ...keys(scope),
      id,
    );
  return {
    initialize: () =>
      serial(async () => {
        await db.execAsync(`PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS drafts (api TEXT NOT NULL,user_id TEXT NOT NULL,room_id TEXT NOT NULL,content TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(api,user_id,room_id));
        CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT NOT NULL UNIQUE,api TEXT NOT NULL,user_id TEXT NOT NULL,room_id TEXT NOT NULL,room_title TEXT NOT NULL,kind TEXT NOT NULL,actor TEXT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_outbox_scope ON outbox(api,user_id,room_id,seq);`);
        await transaction(async (tx) => {
          await tx.runAsync(
            "UPDATE outbox SET status=CASE WHEN kind='turn' THEN 'review' ELSE 'queued' END,last_error='이전 전송 결과를 확인합니다.',next_attempt_at=0 WHERE status='sending'",
          );
          await tx.runAsync(
            "UPDATE outbox SET status='review',last_error='AI 요청은 다시 보내기를 확인해주세요.' WHERE kind='turn' AND status='queued'",
          );
          await tx.runAsync(
            "DELETE FROM outbox WHERE status='sent' AND updated_at<?",
            now() - 7 * 86400000,
          );
        });
      }),
    saveDraft: (scope, roomId, content) =>
      serial(async () => {
        if (content.length > 5000)
          throw new Error("메시지는 5000자 이내로 작성해주세요.");
        await db.runAsync(
          "INSERT INTO drafts(api,user_id,room_id,content,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(api,user_id,room_id) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",
          ...keys(scope),
          roomId,
          content,
          now(),
        );
      }),
    getDraft: (scope, roomId) =>
      serial(
        async () =>
          (
            await db.getFirstAsync(
              "SELECT content FROM drafts WHERE api=? AND user_id=? AND room_id=?",
              ...keys(scope),
              roomId,
            )
          )?.content || "",
      ),
    enqueue: (
      scope,
      { requestId, roomId, kind, actor, content, roomTitle = "" },
    ) =>
      serial(async () => {
        if (
          !roomId ||
          !requestId ||
          !["message", "turn"].includes(kind) ||
          !content.trim() ||
          content.length > 5000 ||
          !actor ||
          actor.length > 120 ||
          roomTitle.length > 120
        )
          throw new Error("전송 내용을 확인해주세요.");
        let result;
        await transaction(async (tx) => {
          const previous = await tx.getFirstAsync(
            "SELECT * FROM outbox WHERE request_id=?",
            requestId,
          );
          if (previous) {
            if (
              previous.api !== scope.api ||
              previous.user_id !== scope.userId ||
              previous.room_id !== roomId ||
              previous.content !== content ||
              previous.kind !== kind ||
              previous.actor !== actor
            )
              throw new Error("다른 전송 기록에 사용된 요청입니다.");
            result = item(previous);
            return;
          }
          const count = await tx.getFirstAsync(
            "SELECT count(*) AS n FROM outbox WHERE api=? AND user_id=? AND status!='sent'",
            ...keys(scope),
          );
          if (count.n >= 100)
            throw new Error(
              "전송 대기 기록이 100개입니다. 먼저 전송하거나 정리해주세요.",
            );
          if (
            kind === "turn" &&
            (await tx.getFirstAsync(
              "SELECT request_id FROM outbox WHERE api=? AND user_id=? AND room_id=? AND kind='turn' AND status!='sent'",
              ...keys(scope),
              roomId,
            ))
          )
            throw new Error(
              "이 스토리에 대기 중인 AI 요청이 있습니다. 먼저 확인해주세요.",
            );
          await tx.runAsync(
            "INSERT INTO outbox(request_id,api,user_id,room_id,room_title,kind,actor,content,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'queued',?,?)",
            requestId,
            ...keys(scope),
            roomId,
            roomTitle,
            kind,
            actor,
            content,
            now(),
            now(),
          );
          const draft = await tx.getFirstAsync(
            "SELECT content FROM drafts WHERE api=? AND user_id=? AND room_id=?",
            ...keys(scope),
            roomId,
          );
          if (draft?.content.trim() === content)
            await tx.runAsync(
              "DELETE FROM drafts WHERE api=? AND user_id=? AND room_id=?",
              ...keys(scope),
              roomId,
            );
          result = item(await get(tx, scope, requestId));
        });
        return result;
      }),
    list: (scope) =>
      serial(async () =>
        (
          await db.getAllAsync(
            "SELECT * FROM outbox WHERE api=? AND user_id=? AND status!='sent' ORDER BY seq",
            ...keys(scope),
          )
        ).map(item),
      ),
    claim: (scope, id) =>
      serial(async () => {
        const result = await db.runAsync(
          "UPDATE outbox SET status='sending',attempts=attempts+1,updated_at=? WHERE api=? AND user_id=? AND request_id=? AND status='queued'",
          now(),
          ...keys(scope),
          id,
        );
        return result.changes === 1;
      }),
    finish: (scope, id, status, lastError = "", nextAttemptAt = 0) =>
      serial(async () => {
        if (!["sent", "queued", "review", "blocked"].includes(status))
          throw new Error("Invalid queue state");
        await db.runAsync(
          "UPDATE outbox SET status=?,last_error=?,next_attempt_at=?,updated_at=? WHERE api=? AND user_id=? AND request_id=? AND status='sending'",
          status,
          lastError,
          nextAttemptAt,
          now(),
          ...keys(scope),
          id,
        );
      }),
    retry: (scope, id) =>
      serial(async () => {
        await db.runAsync(
          "UPDATE outbox SET status='queued',last_error='',next_attempt_at=0,updated_at=? WHERE api=? AND user_id=? AND request_id=? AND status IN ('queued','review','blocked')",
          now(),
          ...keys(scope),
          id,
        );
      }),
    reviewUnsentAI: (scope) =>
      serial(async () => {
        await db.runAsync(
          "UPDATE outbox SET status='review',last_error='AI 요청은 다시 보내기를 확인해주세요.' WHERE api=? AND user_id=? AND kind='turn' AND status='queued'",
          ...keys(scope),
        );
      }),
    discard: (scope, id) =>
      serial(async () => {
        const result = await db.runAsync(
          "DELETE FROM outbox WHERE api=? AND user_id=? AND request_id=? AND status!='sending'",
          ...keys(scope),
          id,
        );
        if (result.changes !== 1)
          throw new Error("전송 중인 기록은 삭제할 수 없습니다.");
      }),
    flush: () => chain,
  };
}
