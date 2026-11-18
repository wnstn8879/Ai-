import { initialState } from "./commuteStory";
import { opening, advance } from "./offlineStory";
export function createOfflineStore(
  db,
  uuid,
  clock = () => new Date().toISOString(),
) {
  let queue = Promise.resolve();
  const serial = (fn) => {
    const next = queue.then(fn);
    queue = next.catch(() => {});
    return next;
  };
  const get = async (tx, id) => {
    const row = await tx.getFirstAsync(
      "SELECT payload FROM preview_rooms WHERE id=?",
      id,
    );
    if (!row) throw new Error("이야기를 찾을 수 없습니다.");
    return JSON.parse(row.payload);
  };
  const write = (tx, room) =>
    tx.runAsync(
      "INSERT OR REPLACE INTO preview_rooms(id,payload,updated_at) VALUES(?,?,?)",
      room.id,
      JSON.stringify(room),
      room.updatedAt,
    );
  const mutate = (fn) =>
    serial(async () => {
      let result;
      await db.withExclusiveTransactionAsync(async (tx) => {
        result = await fn(tx);
      });
      return result;
    });
  const fork = (tx, source, index, title) => {
    if (!Number.isInteger(index) || index < 0 || index > source.messages.length)
      throw new Error("분기 위치가 올바르지 않습니다.");
    const room = JSON.parse(JSON.stringify(source));
    room.id = uuid();
    room.parentId = source.id;
    room.forkIndex = index;
    room.title = title || source.title + " · 다른 선택";
    room.createdAt = room.updatedAt = clock();
    room.messages = room.messages.slice(0, index);
    room.state = index
      ? room.messages[index - 1].stateAfter
      : source.storyVersion === 2
        ? initialState()
        : { scene: 0, ending: false };
    return write(tx, room).then(() => room);
  };
  return {
    initialize: () =>
      serial(() =>
        db.execAsync(
          "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS preview_drafts(room_id TEXT PRIMARY KEY,content TEXT NOT NULL); CREATE TABLE IF NOT EXISTS preview_rooms(id TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS preview_saves(id TEXT PRIMARY KEY,room_id TEXT NOT NULL,label TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS preview_saves_room ON preview_saves(room_id);",
        ),
      ),
    saveDraft: (_scope, roomId, content) =>
      serial(async () => {
        if (content.length > 1000)
          throw new Error("초안은 1000자 이내로 작성해주세요.");
        await db.runAsync(
          "INSERT OR REPLACE INTO preview_drafts(room_id,content) VALUES(?,?)",
          roomId,
          content,
        );
      }),
    getDraft: (_scope, roomId) =>
      serial(
        async () =>
          (
            await db.getFirstAsync(
              "SELECT content FROM preview_drafts WHERE room_id=?",
              roomId,
            )
          )?.content || "",
      ),
    list: () =>
      serial(async () =>
        (
          await db.getAllAsync(
            "SELECT payload FROM preview_rooms ORDER BY updated_at DESC,id",
          )
        ).map((r) => JSON.parse(r.payload)),
      ),
    get: (id) => serial(() => get(db, id)),
    create: (version = 2) =>
      mutate(async (tx) => {
        const room = opening(uuid(), "출근길의 수상한 봉투", clock(), version);
        await write(tx, room);
        return room;
      }),
    send: (id, text) =>
      mutate(async (tx) => {
        const room = advance(await get(tx, id), text, uuid(), clock());
        await write(tx, room);
        const draft = await tx.getFirstAsync(
          "SELECT content FROM preview_drafts WHERE room_id=?",
          id,
        );
        if (draft?.content.trim() === text.trim())
          await tx.runAsync("DELETE FROM preview_drafts WHERE room_id=?", id);
        return room;
      }),
    save: (id, label = "잠깐 쉬어가기") =>
      mutate(async (tx) => {
        const room = await get(tx, id);
        const point = {
          id: uuid(),
          roomId: id,
          label,
          messageIndex: room.messages.length,
          createdAt: clock(),
        };
        await tx.runAsync(
          "INSERT INTO preview_saves VALUES(?,?,?,?,?)",
          point.id,
          id,
          label,
          JSON.stringify(room),
          point.createdAt,
        );
        return point;
      }),
    saves: (id) =>
      serial(async () =>
        (
          await db.getAllAsync(
            "SELECT id,label,payload,created_at FROM preview_saves WHERE room_id=? ORDER BY created_at DESC,id",
            id,
          )
        ).map((r) => ({
          id: r.id,
          label: r.label,
          createdAt: r.created_at,
          messageIndex: JSON.parse(r.payload).messages.length,
        })),
      ),
    fork: (id, index) =>
      mutate(async (tx) => fork(tx, await get(tx, id), index)),
    resume: (saveId) =>
      mutate(async (tx) => {
        const row = await tx.getFirstAsync(
          "SELECT payload FROM preview_saves WHERE id=?",
          saveId,
        );
        if (!row) throw new Error("저장 지점을 찾을 수 없습니다.");
        const source = JSON.parse(row.payload);
        return fork(
          tx,
          source,
          source.messages.length,
          source.title + " · 저장 지점 분기",
        );
      }),
  };
}
