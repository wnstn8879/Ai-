import React from "react";
import { View, Text, Pressable, StyleSheet, Alert } from "react-native";
const labels = {
  queued: "연결 후 전송 대기",
  sending: "전송 중",
  review: "확인 후 다시 보내기",
  blocked: "전송할 수 없음 · 확인 필요",
};
export default function OutboxPanel({
  items,
  error,
  busy,
  onRetry,
  onDiscard,
}) {
  if (!items.length && !error) return null;
  const button = (label, action, disabled = false) => (
    <Pressable
      accessibilityRole="button"
      disabled={busy || disabled}
      onPress={action}
      style={styles.button}
    >
      <Text style={styles.text}>{label}</Text>
    </Pressable>
  );
  return (
    <View style={styles.card}>
      <Text style={styles.title}>기기에 저장된 전송 기록</Text>
      {!!error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      <Text style={styles.muted}>
        일반 메시지는 연결 후 자동 재시도합니다. AI 요청은 실패·재시작 후 다시
        보내기를 확인해야 합니다. 이미 저장된 결과는 같은 요청 ID로 확인합니다.
        같은 스토리의 앞선 전송 기록을 먼저 확인해주세요.
      </Text>
      {items.map((row) => (
        <View key={row.requestId} style={styles.item}>
          <Text style={styles.text}>{row.roomTitle || "스토리"}</Text>
          <Text style={styles.text}>
            {row.kind === "turn" ? "AI 대화" : "참가자 메시지"} ·{" "}
            {labels[row.status]}
          </Text>
          <Text selectable style={styles.text}>
            {row.content}
          </Text>
          {!!row.lastError && <Text style={styles.muted}>{row.lastError}</Text>}
          {button(
            row.kind === "turn" ? "AI 요청 다시 보내기" : "메시지 다시 보내기",
            () => onRetry(row),
            row.status === "sending",
          )}
          {button(
            "기기 전송 기록 삭제",
            () =>
              Alert.alert(
                "기기 기록을 삭제할까요?",
                "서버에 이미 도착한 메시지는 삭제되지 않습니다. 전송 결과가 불확실하면 먼저 다시 보내기로 확인하세요.",
                [
                  { text: "취소", style: "cancel" },
                  {
                    text: "기기 기록 삭제",
                    style: "destructive",
                    onPress: () => onDiscard(row),
                  },
                ],
              ),
            row.status === "sending",
          )}
        </View>
      ))}
    </View>
  );
}
const styles = StyleSheet.create({
  card: { backgroundColor: "#1b2639", padding: 16, borderRadius: 14, gap: 12 },
  title: { color: "#f3f3ff", fontWeight: "700", fontSize: 18 },
  text: { color: "#eef2fa", lineHeight: 24 },
  muted: { color: "#a8b5c9", lineHeight: 22 },
  error: { color: "#ffb7b7" },
  button: {
    backgroundColor: "#354469",
    padding: 14,
    borderRadius: 10,
    minHeight: 48,
  },
  item: {
    borderTopWidth: 1,
    borderTopColor: "#3a4962",
    paddingTop: 12,
    gap: 10,
  },
});
