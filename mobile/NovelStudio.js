import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  Alert,
} from "react-native";
import * as Crypto from "expo-crypto";
import { request } from "./api";
import { useRoomDraft } from "./useOutbox";
import OutboxPanel from "./OutboxPanel";

export default function NovelStudio({
  outbox,
  refreshKey,
  initialRoomId,
  onList,
}) {
  const [concept, setConcept] = useState(""),
    [books, setBooks] = useState([]),
    [book, setBook] = useState(null),
    [saves, setSaves] = useState([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const lock = useRef(false),
    current = useRef(null),
    alive = useRef(true),
    loadVersion = useRef(0);
  current.current = book?.id;
  const direction = useRoomDraft(outbox.store, outbox.scope, book?.id);
  const list = async () => {
    const rows = await request("/rooms");
    if (alive.current)
      setBooks(rows.filter((r) => r.narrative_format === "novel"));
  };
  const open = async (id) => {
    const version = ++loadVersion.current;
    const [r, s] = await Promise.all([
      request("/rooms/" + id),
      request("/rooms/" + id + "/saves"),
    ]);
    if (alive.current && loadVersion.current === version) {
      setBook(r);
      setSaves(s);
    }
  };
  const run = async (fn) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      if (alive.current) setError(e.message);
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    list().catch((e) => setError(e.message));
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const id = current.current;
    if (!id) return;
    let ignore = false;
    Promise.all([request("/rooms/" + id), request("/rooms/" + id + "/saves")])
      .then(([r, s]) => {
        if (!ignore && alive.current && current.current === id) {
          setBook(r);
          setSaves(s);
        }
      })
      .catch((e) => {
        if (!ignore && alive.current) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [refreshKey]);
  const button = (label, action, disabled = false) => (
    <Pressable
      accessibilityRole="button"
      disabled={busy || disabled}
      onPress={action}
      style={[styles.button, (busy || disabled) && { opacity: 0.45 }]}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
  const chapters = book?.messages.filter((m) => m.actor === "AI") || [];
  useEffect(() => {
    if (initialRoomId)
      open(initialRoomId).catch((e) => {
        if (alive.current) setError(e.message);
      });
  }, [initialRoomId]);
  const generate = () =>
    run(async () => {
      if (!direction.ready) throw Error("창작 메모를 불러오는 중입니다.");
      const content =
        direction.input.trim() ||
        (chapters.length
          ? "앞선 사건과 인물의 감정을 이어 다음 소설 장면을 써줘."
          : "원래 상상의 모든 요소를 살려 인물의 감정과 갈등이 드러나는 소설 첫 장면을 써줘. 선택지 대신 읽을 수 있는 서술과 대화로 시작해줘.");
      await outbox.enqueue({
        requestId: Crypto.randomUUID(),
        roomId: book.id,
        roomTitle: book.title,
        kind: "turn",
        actor: "작가",
        content,
      });
      direction.clearQueued(content);
      setNotice(
        "생성 요청을 저장했습니다. 응답이 오면 이 책에 자동 저장됩니다.",
      );
    });
  return (
    <View style={styles.page}>
      <Text style={styles.hero}>당신의 상상에는{"\n"}장르 칸이 없습니다.</Text>
      <Text style={styles.muted}>
        발효로 내공을 쌓는 김치 마스터, 총을 쓰는 좀비, 우주 던전과 무협. 섞고
        싶은 세계와 인물, 느끼고 싶은 감정을 자유롭게 적으세요.
      </Text>
      {!!error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      {!!notice && (
        <Text accessibilityLiveRegion="polite" style={styles.notice}>
          {notice}
        </Text>
      )}
      {!book ? (
        <>
          <TextInput
            accessibilityLabel="나만의 자유 주제"
            value={concept}
            onChangeText={setConcept}
            multiline
            maxLength={12000}
            editable={!busy}
            placeholder="어떤 상상도 좋아요. 반드시 살리고 싶은 요소와 인물의 바람을 적어주세요."
            placeholderTextColor="#99a8bd"
            style={styles.input}
          />
          {button(
            "이 상상으로 소설 만들기",
            () =>
              run(async () => {
                const text = concept.trim();
                if (!text) throw Error("상상을 한 줄 이상 적어주세요.");
                const r = await request("/rooms", "POST", {
                  title: Array.from(text).slice(0, 60).join(""),
                  world_rules: text,
                  characters: [],
                  mode: "solo",
                  narrative_format: "novel",
                });
                await open(r.id);
                setConcept("");
                setNotice("상상 원문을 저장했습니다. 첫 장면을 생성해보세요.");
              }),
            !concept.trim(),
          )}
          <Text style={styles.heading}>나의 소설</Text>
          {!books.length && (
            <Text style={styles.muted}>
              아직 소설이 없습니다. 정해진 줄거리 없이 내 상상으로 시작하세요.
            </Text>
          )}
          {books.map((r) => (
            <View key={r.id} style={styles.card}>
              <Text style={styles.heading}>{r.title}</Text>
              {r.parent_room_id && (
                <Text style={styles.muted}>
                  다른 방향으로 뻗은 이야기 · 원본 보존
                </Text>
              )}
              {button("읽고 이어 쓰기", () => run(() => open(r.id)))}
            </View>
          ))}
        </>
      ) : (
        <>
          {button("소설 목록", () =>
            run(async () => {
              loadVersion.current++;
              await list();
              setBook(null);
              onList?.();
            }),
          )}
          <Text style={styles.heading}>{book.title}</Text>
          <Text style={styles.muted}>내 상상 원문 · {book.world_rules}</Text>
          {!chapters.length && (
            <Text style={styles.muted}>
              첫 장면이 아직 없습니다. 아래 생성 버튼은 설정된 AI 서버를
              호출합니다.
            </Text>
          )}
          {chapters.map((m, i) => (
            <View style={styles.card} key={m.id}>
              <Text style={styles.muted}>장면 {i + 1}</Text>
              <Text selectable style={styles.prose}>
                {m.content}
              </Text>
              {button("이 장면에서 다른 이야기", () =>
                Alert.alert(
                  "이 장면에서 분기할까요?",
                  "선택한 장면까지 보존하고 새 소설로 이어갑니다. 원본은 바뀌지 않습니다.",
                  [
                    { text: "취소", style: "cancel" },
                    {
                      text: "새 이야기",
                      onPress: () =>
                        run(async () => {
                          const r = await request(
                            "/rooms/" + book.id + "/forks",
                            "POST",
                            {
                              title:
                                Array.from(book.title).slice(0, 100).join("") +
                                " · 다른 이야기",
                              message_index:
                                book.messages.findIndex((x) => x.id === m.id) +
                                1,
                            },
                          );
                          await open(r.id);
                        }),
                    },
                  ],
                ),
              )}
            </View>
          ))}
          <Text style={styles.heading}>어떤 방향으로 이어갈까요?</Text>
          <TextInput
            accessibilityLabel="소설 창작 방향"
            value={direction.input}
            onChangeText={direction.setInput}
            multiline
            maxLength={5000}
            editable={!busy && direction.ready}
            placeholder="이 인물을 살려줘. 로맨스로 바꿔줘. SF와 무협의 연결을 더 보여줘…"
            placeholderTextColor="#99a8bd"
            style={styles.input}
          />
          <Text style={styles.muted}>
            {direction.status === "saved"
              ? "창작 메모 저장됨"
              : direction.status === "error"
                ? "메모를 기기에 저장하지 못했습니다."
                : "창작 메모 준비·저장 중…"}
          </Text>
          {button(
            chapters.length
              ? "이 방향으로 다음 장면 쓰기"
              : "소설 첫 장면 생성",
            generate,
            !direction.ready,
          )}
          {button("읽는 위치 저장", () =>
            run(async () => {
              await request("/rooms/" + book.id + "/saves", "POST", {
                label: "소설 · " + chapters.length + "번째 장면 뒤",
                message_index: book.messages.length,
              });
              await open(book.id);
              setNotice("읽는 위치와 설정을 저장했습니다.");
            }),
          )}
          {saves.map((s) => (
            <View key={s.id} style={styles.card}>
              <Text style={styles.muted}>{s.label}</Text>
              {button("저장 지점에서 다른 방향으로", () =>
                run(async () => {
                  const r = await request("/saves/" + s.id + "/resume", "POST");
                  await open(r.id);
                }),
              )}
            </View>
          ))}
          <OutboxPanel
            items={outbox.items.filter((x) => x.roomId === book.id)}
            error={outbox.error}
            busy={busy}
            onRetry={(x) => run(() => outbox.retry(x))}
            onDiscard={(x) => run(() => outbox.discard(x))}
          />
          {button("소설 새로고침", () => run(() => open(book.id)))}
          <Text style={styles.muted}>
            생성된 장면은 자동 저장됩니다. 작품 공개·다른 독자의 재창작·게임
            전환은 아직 연결되지 않았습니다.
          </Text>
        </>
      )}
    </View>
  );
}
const styles = StyleSheet.create({
  page: { gap: 14 },
  hero: { color: "#f2efff", fontSize: 28, fontWeight: "700", lineHeight: 39 },
  heading: { color: "#eeeaff", fontSize: 19, fontWeight: "700" },
  muted: { color: "#abb7d0", lineHeight: 23 },
  prose: { color: "#f0edf7", fontSize: 17, lineHeight: 31 },
  card: { backgroundColor: "#192239", padding: 18, borderRadius: 16, gap: 14 },
  input: {
    backgroundColor: "#1c2840",
    color: "#f5f2ff",
    borderRadius: 12,
    padding: 14,
    minHeight: 110,
    textAlignVertical: "top",
    fontSize: 16,
    lineHeight: 25,
  },
  button: {
    backgroundColor: "#58418c",
    padding: 15,
    borderRadius: 12,
    minHeight: 48,
  },
  buttonText: { color: "#f4efff", fontWeight: "600", lineHeight: 22 },
  error: { color: "#ffb7ba" },
  notice: { color: "#b2e6d0", lineHeight: 22 },
});
