import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  Pressable,
  TextInput,
  ScrollView,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
  Modal,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import * as SQLite from "expo-sqlite";
import * as Crypto from "expo-crypto";
import { createOfflineStore } from "./offlineStore";
import { choicesFor } from "./offlineStory";
import { useRoomDraft } from "./useOutbox";
const scope = { api: "offline://storyverse-preview", userId: "device" };
let opening;
function storage() {
  if (!opening)
    opening = (async () => {
      const db = await SQLite.openDatabaseAsync("storyverse-preview-v1.db");
      const store = createOfflineStore(db, () => Crypto.randomUUID());
      await store.initialize();
      return store;
    })().catch((e) => {
      opening = null;
      throw e;
    });
  return opening;
}
export default function OfflinePreview({ onExit }) {
  const [store, setStore] = useState(null),
    [draftStore, setDraftStore] = useState(null);
  const [rooms, setRooms] = useState([]),
    [room, setRoom] = useState(null),
    [saves, setSaves] = useState([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [timeline, setTimeline] = useState(false);
  const lock = useRef(false),
    scroll = useRef(null);
  const draft = useRoomDraft(draftStore, scope, room?.id);
  const initialize = async () => {
    const s = await storage();
    const list = await s.list();
    setStore(s);
    setDraftStore(s);
    setRooms(list);
  };
  useEffect(() => {
    initialize().catch((e) => setError(e.message));
  }, []);
  const run = async (fn) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e.message || "기기에 저장하지 못했습니다. 다시 시도해주세요.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  const open = async (r) => {
    setSaves(await store.saves(r.id));
    setRoom(r);
    setTimeline(false);
  };
  const home = async () => {
    setRooms(await store.list());
    setRoom(null);
    setTimeline(false);
  };
  const send = (text) =>
    run(async () => {
      if (!draft.ready) throw new Error("초안을 불러오는 중입니다.");
      const next = await store.send(room.id, text);
      draft.clearQueued(text.trim());
      setRoom(next);
      setNotice("기기에 자동 저장됨");
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 100);
    });
  const save = (pause) =>
    run(async () => {
      await store.save(
        room.id,
        "쉬어가기 · " + new Date().toLocaleString("ko-KR"),
      );
      if (pause) {
        await home();
        setNotice("저장했어요. 다음 출근길에 이어가세요.");
      } else {
        setSaves(await store.saves(room.id));
        setNotice("현재 장면을 기기에 저장했어요.");
      }
    });
  const fork = (index) =>
    Alert.alert(
      "여기서 다시 시작할까요?",
      "이 장면까지 복사해 새 이야기를 만듭니다. 원본 이야기는 그대로 남습니다.",
      [
        { text: "취소", style: "cancel" },
        {
          text: "새 분기 만들기",
          onPress: () =>
            run(async () => {
              await open(await store.fork(room.id, index));
              setNotice("원본을 보존하고 새 분기를 만들었어요.");
            }),
        },
      ],
    );
  const button = (label, action, secondary = false, disabled = false) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={busy || disabled}
      onPress={action}
      style={[
        styles.button,
        secondary && styles.secondary,
        (busy || disabled) && { opacity: 0.45 },
      ]}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
  const message = (m, i) => (
    <View key={m.id} style={[styles.message, m.actor === "나" && styles.mine]}>
      <Text style={styles.actor}>{m.actor}</Text>
      <Text selectable style={styles.body}>
        {m.content}
      </Text>
      {timeline &&
        button(`${i + 1}번째 메시지에서 분기`, () => fork(i + 1), true)}
    </View>
  );
  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <View style={styles.header}>
          <Text style={styles.brand}>IMAGINE</Text>
          <Text style={styles.badge}>기기 체험</Text>
        </View>
        <Text style={styles.disclosure}>
          미리 작성된 선택형 이야기 · 실제 AI/멀티플레이 아님
        </Text>
        {!!error && (
          <View style={styles.banner}>
            <Text accessibilityRole="alert" style={styles.error}>
              {error}
            </Text>
            {!store && button("다시 준비하기", () => run(initialize), true)}
          </View>
        )}
        {!!notice && (
          <Text accessibilityLiveRegion="polite" style={styles.notice}>
            {notice}
          </Text>
        )}
        {busy && <ActivityIndicator color="#b9a5ff" />}
        {!store && !error && (
          <ActivityIndicator
            accessibilityLabel="기기 저장소 준비 중"
            color="#b9a5ff"
          />
        )}
        {!room ? (
          <ScrollView contentContainerStyle={styles.page}>
            <Text style={styles.eyebrow}>
              Your Story, Your World, Your Choice.
            </Text>
            <Text style={styles.hero}>
              당신의 상상을,{"\n"}함께 탐험하는 세계로.
            </Text>
            <Text style={styles.muted}>
              짧은 장면으로 탐험하고 언제든 저장하세요. 과거 장면에서 다른
              선택으로 분기할 수 있어요. 이 기기 체험판은 준비된 이야기로
              진행합니다.
            </Text>
            {button(
              "새 이야기 시작",
              () => run(async () => open(await store.create())),
              false,
              !store,
            )}
            <Text style={styles.heading}>내 이야기 보관함</Text>
            {!rooms.length && (
              <View style={styles.card}>
                <Text style={styles.muted}>
                  아직 이야기가 없어요. 첫 출근길 모험을 시작해보세요.
                </Text>
              </View>
            )}
            {rooms.map((r) => (
              <View key={r.id} style={styles.card}>
                <Text style={styles.title}>{r.title}</Text>
                <Text style={styles.muted}>
                  {r.messages.length}개 메시지 ·{" "}
                  {r.state.ending ? "장면 마무리" : "진행 중"}
                </Text>
                {r.parentId && (
                  <Text style={styles.muted}>
                    ↳{" "}
                    {rooms.find((p) => p.id === r.parentId)?.title ||
                      "원본 이야기"}
                    의 {r.forkIndex}번째 메시지에서 분기
                  </Text>
                )}
                {button(
                  "이어서 플레이",
                  () => run(async () => open(await store.get(r.id))),
                  true,
                )}
              </View>
            ))}
            <Text style={styles.small}>
              기록과 초안은 이 휴대폰에 저장됩니다. 앱을 지우거나 앱 데이터를
              삭제하면 복구할 수 없어요. 클라우드 계정과 동기화되지 않습니다.
            </Text>
            {!!onExit && button("온라인 로그인으로 돌아가기", onExit, true)}
          </ScrollView>
        ) : (
          <>
            <View style={styles.roomHeader}>
              <Pressable
                accessibilityRole="button"
                onPress={() => run(home)}
                disabled={busy}
              >
                <Text style={styles.accent}>‹ 보관함</Text>
              </Pressable>
              <Text style={styles.title}>{room.title}</Text>
              <Text style={styles.small}>
                자동 저장 ·{" "}
                {room.state.ending ? "이번 장면 완료" : "짧은 장면 진행 중"}
              </Text>
            </View>
            <ScrollView
              ref={scroll}
              contentContainerStyle={styles.page}
              keyboardShouldPersistTaps="handled"
            >
              {room.messages.map(message)}
              <Text style={styles.heading}>
                {room.state.ending
                  ? "여기서 쉬어가도 좋아요"
                  : "다음 행동을 골라보세요"}
              </Text>
              {choicesFor(room).map((choice) => (
                <View key={choice}>
                  {button(choice, () => send(choice), true, !draft.ready)}
                </View>
              ))}
              {room.state.ending && (
                <Text style={styles.muted}>
                  원하면 다음 장면을 이어가거나 타임라인에서 다른 선택을
                  해보세요.
                </Text>
              )}
              {button("저장하고 쉬기", () => save(true))}
              {button(
                "저장 지점 · 타임라인",
                () =>
                  run(async () => {
                    setSaves(await store.saves(room.id));
                    setTimeline(true);
                  }),
                true,
              )}
            </ScrollView>
            <View style={styles.composer}>
              <TextInput
                accessibilityLabel="나의 행동 입력"
                value={draft.input}
                onChangeText={draft.setInput}
                placeholder="직접 행동을 적어도 좋아요"
                placeholderTextColor="#8d99b3"
                multiline
                maxLength={1000}
                editable={draft.ready && !busy}
                style={styles.input}
              />
              <Text
                style={draft.status === "error" ? styles.error : styles.small}
              >
                {draft.status === "saved"
                  ? "초안 저장됨"
                  : draft.status === "error"
                    ? "초안을 저장하지 못했어요"
                    : "초안 준비·저장 중…"}
              </Text>
              {button(
                "행동 보내기",
                () => send(draft.input),
                false,
                !draft.ready || !draft.input.trim(),
              )}
            </View>
          </>
        )}
        <Modal
          visible={timeline && !!room}
          animationType="slide"
          onRequestClose={() => setTimeline(false)}
        >
          <SafeAreaView style={styles.root}>
            <ScrollView contentContainerStyle={styles.page}>
              <Text style={styles.heading}>저장 지점 · 타임라인</Text>
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
              <Text style={styles.muted}>
                원본은 보존됩니다. 원하는 메시지까지 복사해 새 분기로
                이어가세요.
              </Text>
              {button("대화로 돌아가기", () => setTimeline(false), true)}
              {button("현재 장면 저장", () => save(false))}
              {saves.map((s) => (
                <View style={styles.card} key={s.id}>
                  <Text style={styles.title}>{s.label}</Text>
                  <Text style={styles.muted}>
                    {s.messageIndex}번째 메시지까지 저장
                  </Text>
                  {button(
                    "이 저장 지점에서 새 분기",
                    () =>
                      run(async () => {
                        await open(await store.resume(s.id));
                        setNotice("저장 지점에서 새 분기를 만들었어요.");
                      }),
                    true,
                  )}
                </View>
              ))}
              {room && room.messages.map(message)}
              {button("대화로 돌아가기", () => setTimeline(false), true)}
            </ScrollView>
          </SafeAreaView>
        </Modal>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0c1020" },
  flex: { flex: 1 },
  header: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 8,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  brand: {
    color: "#f4f2ff",
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 1,
  },
  accent: { color: "#c4b5fd" },
  badge: {
    color: "#d4c8ff",
    backgroundColor: "#29213f",
    padding: 7,
    borderRadius: 8,
    fontSize: 12,
  },
  disclosure: {
    color: "#a9a0bc",
    paddingHorizontal: 20,
    paddingBottom: 8,
    fontSize: 12,
  },
  page: { padding: 20, gap: 14, paddingBottom: 36 },
  eyebrow: { color: "#b9a4ff", marginTop: 18 },
  hero: { color: "#f6f3ff", fontSize: 32, lineHeight: 44, fontWeight: "800" },
  heading: { color: "#eeebff", fontSize: 20, fontWeight: "700", marginTop: 10 },
  title: { color: "#f0ecff", fontSize: 16, fontWeight: "700" },
  muted: { color: "#b1b9cf", lineHeight: 23 },
  small: { color: "#929db7", fontSize: 12, lineHeight: 19 },
  card: { backgroundColor: "#171d32", borderRadius: 18, padding: 18, gap: 10 },
  button: {
    backgroundColor: "#7553cf",
    borderRadius: 12,
    padding: 15,
    minHeight: 48,
    justifyContent: "center",
    alignItems: "center",
  },
  secondary: {
    backgroundColor: "#222b46",
    borderWidth: 1,
    borderColor: "#35415d",
  },
  buttonText: { color: "#faf8ff", fontWeight: "600", lineHeight: 21 },
  message: {
    backgroundColor: "#171d32",
    padding: 18,
    borderRadius: 16,
    gap: 9,
  },
  mine: { backgroundColor: "#28203e", marginLeft: 25 },
  actor: { color: "#bba7ff", fontSize: 12, fontWeight: "700" },
  body: { color: "#eeedf4", lineHeight: 27, fontSize: 16 },
  roomHeader: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    gap: 7,
    borderBottomWidth: 1,
    borderColor: "#252d43",
  },
  composer: {
    padding: 12,
    gap: 6,
    borderTopWidth: 1,
    borderColor: "#252d43",
    backgroundColor: "#12182b",
  },
  input: {
    color: "#f1eff9",
    fontSize: 15,
    backgroundColor: "#1e2740",
    padding: 12,
    borderRadius: 12,
    maxHeight: 100,
    minHeight: 44,
  },
  error: { color: "#ffb9bc", padding: 10 },
  notice: {
    color: "#b9ead8",
    paddingHorizontal: 20,
    paddingVertical: 6,
    fontSize: 13,
  },
  banner: { paddingHorizontal: 10 },
});
