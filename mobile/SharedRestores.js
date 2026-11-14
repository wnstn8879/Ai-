import React, { useEffect, useRef, useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet } from "react-native";
import { request } from "./api";
const statuses = {
  pending: "동의 대기",
  approved: "전원 동의 · 방장 실행 대기",
  rejected: "거절 또는 동의 철회",
  cancelled: "방장 취소",
  expired: "동의 기한 만료",
  stale: "진행·설정·참가자 변경 · 새 동의 필요",
  applied: "새 공용 방 복원 완료",
};
export default function SharedRestores({
  room,
  user,
  owner,
  busy,
  onAction,
  onOpenRoom,
  onResume,
}) {
  const [saves, setSaves] = useState([]),
    [proposals, setProposals] = useState([]),
    [label, setLabel] = useState("함께 만든 선택"),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false);
  const mounted = useRef(false),
    serial = useRef(0);
  const load = async () => {
    const own = ++serial.current;
    const [checkpoints, votes] = await Promise.all([
      request("/rooms/" + room.id + "/saves"),
      request("/rooms/" + room.id + "/restore-proposals"),
    ]);
    if (mounted.current && own === serial.current) {
      setSaves(checkpoints.filter((s) => s.scope === "shared"));
      setProposals(votes);
      setError("");
      setLoaded(true);
    }
  };
  useEffect(() => {
    mounted.current = true;
    let timer;
    const poll = async () => {
      try {
        await load();
      } catch {
        if (mounted.current)
          setError(
            "공용 저장·동의 상태를 불러오지 못했습니다. 연결 후 다시 확인합니다.",
          );
      } finally {
        if (mounted.current) timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      mounted.current = false;
      serial.current++;
      clearTimeout(timer);
    };
  }, [room.id]);
  const action = (fn) =>
    onAction(async () => {
      serial.current++;
      await fn();
    });
  const mutate = (path, body) =>
    action(async () => {
      await request(path, "POST", body);
      await load();
    });
  const button = (text, fn) => (
    <Pressable
      accessibilityRole="button"
      disabled={busy}
      style={[styles.button, busy && styles.disabled]}
      onPress={fn}
    >
      <Text style={styles.text}>{text}</Text>
    </Pressable>
  );
  const base = "/rooms/" + room.id;
  return (
    <View style={styles.card}>
      <Text style={styles.heading}>함께 저장하고 복원하기</Text>
      <Text style={styles.muted}>
        원본 방은 그대로 남습니다. 전원 동의 후 방장이 저장 지점에서 새 공용
        방을 만듭니다.
      </Text>
      <Text style={styles.muted}>
        대화·설정·참가자가 바뀌면 새 동의가 필요합니다. 동의 기한은 15분입니다.
      </Text>
      {!!error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      {!loaded && !error && (
        <Text style={styles.muted}>공용 저장 불러오는 중…</Text>
      )}
      {owner && (
        <>
          <TextInput
            accessibilityLabel="공용 저장 이름"
            editable={!busy}
            style={styles.input}
            value={label}
            onChangeText={setLabel}
            maxLength={100}
          />
          {button("현재 장면 공용 저장", () =>
            mutate(base + "/saves", { label, scope: "shared" }),
          )}
          <Text style={styles.muted}>
            복원 제안은 방장 본인의 동의로도 기록됩니다.
          </Text>
        </>
      )}
      {loaded && saves.length === 0 && (
        <Text style={styles.muted}>
          아직 공용 저장 지점이 없습니다. 방장이 저장할 수 있습니다.
        </Text>
      )}
      {saves.map((s) => (
        <View key={s.id} style={styles.item}>
          <Text style={styles.text}>
            {s.label} · 메시지 {s.message_index}개 시점
          </Text>
          {button("공용 저장에서 개인 분기", () => onResume(s))}
          {owner &&
            button("이 지점으로 공용 복원 제안", () =>
              mutate(base + "/restore-proposals", { save_id: s.id }),
            )}
        </View>
      ))}
      {proposals.map((p) => {
        const active = p.status === "pending" || p.status === "approved";
        const mine = p.votes.find((v) => v.user_id === user.id);
        const path = base + "/restore-proposals/" + p.id;
        return (
          <View key={p.id} style={styles.item}>
            <Text style={styles.text}>
              {p.label} · {statuses[p.status] || p.status}
            </Text>
            <Text style={styles.muted}>
              복원할 위치: 메시지 {p.message_index}개 · 동의{" "}
              {p.votes.filter((v) => v.accept).length}/{p.eligible.length}
            </Text>
            {p.eligible.map((member) => {
              const v = p.votes.find((v) => v.user_id === member.user_id);
              return (
                <Text key={member.user_id} style={styles.muted}>
                  {member.display_name} ·{" "}
                  {v ? (v.accept ? "동의" : "거절") : "대기"} · 복원 캐릭터:{" "}
                  {member.character || "미배정"}
                </Text>
              );
            })}
            {active && !mine && (
              <>
                {button("공용 복원에 동의", () =>
                  mutate(path + "/vote", { accept: true }),
                )}
                {button("공용 복원 거절", () =>
                  mutate(path + "/vote", { accept: false }),
                )}
              </>
            )}
            {active &&
              mine?.accept &&
              button("공용 복원 동의 철회", () =>
                mutate(path + "/vote", { accept: false }),
              )}
            {active &&
              owner &&
              button("복원 제안 취소", () => mutate(path + "/cancel"))}
            {p.status === "approved" &&
              owner &&
              button("전원 동의한 공용 복원 실행", () =>
                action(async () => {
                  const result = await request(path + "/apply", "POST");
                  await onOpenRoom(result.room_id);
                }),
              )}
            {p.status === "applied" &&
              p.result_room_id &&
              button("복원된 공용 방 열기", () =>
                action(() => onOpenRoom(p.result_room_id)),
              )}
          </View>
        );
      })}
      {button("공용 저장·동의 새로고침", () => action(load))}
    </View>
  );
}
const styles = StyleSheet.create({
  card: { backgroundColor: "#1b2639", padding: 16, borderRadius: 14, gap: 12 },
  heading: { color: "#f3f3ff", fontSize: 18, fontWeight: "700" },
  text: { color: "#eef2fa", lineHeight: 24, textAlign: "center" },
  muted: { color: "#a8b5c9", lineHeight: 22 },
  input: {
    color: "white",
    borderWidth: 1,
    borderColor: "#52617b",
    padding: 12,
    borderRadius: 10,
    minHeight: 48,
  },
  button: {
    backgroundColor: "#354469",
    padding: 14,
    borderRadius: 10,
    minHeight: 48,
  },
  disabled: { opacity: 0.5 },
  item: {
    borderTopWidth: 1,
    borderTopColor: "#3a4962",
    paddingTop: 12,
    gap: 10,
  },
  error: { color: "#ffb7b7", lineHeight: 24 },
});
