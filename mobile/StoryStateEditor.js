import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet } from "react-native";
const copy = (state) => JSON.parse(JSON.stringify(state));
const lines = (text) =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
const emptyCharacter = () => ({
  name: "",
  personality: "",
  speech_style: "",
  goal: "",
  relationships: "",
  condition: "",
  memories: [],
});
export default function StoryStateEditor({ room, canEdit, busy, onSave }) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState(null),
    [base, setBase] = useState(0),
    [details, setDetails] = useState(false);
  const state = room.story_state;
  if (!state) return null;
  const button = (label, action) => (
    <Pressable
      accessibilityRole="button"
      disabled={busy}
      onPress={action}
      style={styles.button}
    >
      <Text style={styles.text}>{label}</Text>
    </Pressable>
  );
  const input = (label, value, change, maxLength) => (
    <View style={styles.field}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        editable={!busy}
        multiline
        style={styles.input}
        value={value}
        onChangeText={change}
        maxLength={maxLength}
      />
    </View>
  );
  const change = (key, value) => setDraft({ ...draft, [key]: value });
  const changeCharacter = (index, key, value) =>
    setDraft({
      ...draft,
      characters: draft.characters.map((c, i) =>
        i === index ? { ...c, [key]: value } : c,
      ),
    });
  return (
    <View style={styles.card}>
      <Text style={styles.heading}>세계관과 현재 장면</Text>
      <Text style={styles.muted}>
        상태 버전 {room.state_revision} · 저장 지점에서 함께 복원됩니다.
      </Text>
      {!editing ? (
        <>
          <Text selectable style={styles.text}>
            {state.location || "장소 미설정"}
            {state.summary ? "\n" + state.summary : ""}
          </Text>
          {button(details ? "설정 접기" : "세계관·캐릭터 자세히 보기", () =>
            setDetails(!details),
          )}
          {details && (
            <>
              <Text selectable style={styles.muted}>
                세계관 규칙: {state.world_rules}
              </Text>
              {state.facts.map((fact, i) => (
                <Text key={i} style={styles.muted}>
                  • {fact}
                </Text>
              ))}
              {state.characters.map((c, i) => (
                <View key={i} style={styles.character}>
                  <Text style={styles.text}>
                    {c.name}
                    {c.condition ? " · " + c.condition : ""}
                  </Text>
                  {!!c.personality && (
                    <Text style={styles.muted}>성격: {c.personality}</Text>
                  )}
                  {!!c.speech_style && (
                    <Text style={styles.muted}>말투: {c.speech_style}</Text>
                  )}
                  {!!c.relationships && (
                    <Text style={styles.muted}>관계: {c.relationships}</Text>
                  )}
                  {!!c.goal && <Text style={styles.muted}>목표: {c.goal}</Text>}
                  {!!c.memories.length && (
                    <Text style={styles.muted}>
                      기억: {c.memories.join(" / ")}
                    </Text>
                  )}
                </View>
              ))}
            </>
          )}
          {canEdit &&
            button("세계관·캐릭터 상태 편집", () => {
              setDraft(copy(state));
              setBase(room.state_revision);
              setEditing(true);
            })}
        </>
      ) : (
        <>
          {base !== room.state_revision && (
            <Text accessibilityRole="alert" style={styles.error}>
              다른 변경이 있습니다. 입력은 유지됩니다. 취소 후 최신 상태에서
              다시 편집해주세요.
            </Text>
          )}
          {input(
            "세계관 규칙",
            draft.world_rules,
            (v) => change("world_rules", v),
            20000,
          )}
          {input(
            "현재 장소",
            draft.location,
            (v) => change("location", v),
            200,
          )}
          {input(
            "현재 장면과 사건 요약",
            draft.summary,
            (v) => change("summary", v),
            2000,
          )}
          {input(
            "중요한 사실 (한 줄에 하나, 최대 30개)",
            draft.facts.join("\n"),
            (v) => change("facts", v.split("\n")),
            9300,
          )}
          {draft.characters.map((c, i) => (
            <View key={i} style={styles.character}>
              {input(
                "캐릭터 이름",
                c.name,
                (v) => changeCharacter(i, "name", v),
                120,
              )}
              {input(
                "성격",
                c.personality,
                (v) => changeCharacter(i, "personality", v),
                500,
              )}
              {input(
                "말투",
                c.speech_style,
                (v) => changeCharacter(i, "speech_style", v),
                300,
              )}
              {input("목표", c.goal, (v) => changeCharacter(i, "goal", v), 500)}
              {input(
                "관계",
                c.relationships,
                (v) => changeCharacter(i, "relationships", v),
                1000,
              )}
              {input(
                "현재 상태",
                c.condition,
                (v) => changeCharacter(i, "condition", v),
                500,
              )}
              {input(
                "중요한 기억 (한 줄에 하나, 최대 20개)",
                c.memories.join("\n"),
                (v) => changeCharacter(i, "memories", v.split("\n")),
                6200,
              )}
              {button("이 캐릭터 제거", () =>
                change(
                  "characters",
                  draft.characters.filter((_, index) => index !== i),
                ),
              )}
            </View>
          ))}
          {draft.characters.length < 30 &&
            button("캐릭터 추가", () =>
              change("characters", [...draft.characters, emptyCharacter()]),
            )}
          {button("상태 저장", async () => {
            const next = {
              ...draft,
              facts: lines(draft.facts.join("\n")),
              characters: draft.characters.map((c) => ({
                ...c,
                memories: lines(c.memories.join("\n")),
              })),
            };
            if (await onSave(base, next)) setEditing(false);
          })}
          {button("편집 취소", () => setEditing(false))}
        </>
      )}
    </View>
  );
}
const styles = StyleSheet.create({
  card: { backgroundColor: "#1b2639", padding: 16, borderRadius: 14, gap: 12 },
  heading: { color: "#f3f3ff", fontSize: 18, fontWeight: "700" },
  text: { color: "#eef2fa", lineHeight: 24 },
  muted: { color: "#a8b5c9", lineHeight: 22 },
  field: { gap: 6 },
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
  character: {
    borderTopWidth: 1,
    borderTopColor: "#3a4962",
    paddingTop: 12,
    gap: 10,
  },
  error: { color: "#ffb7b7", lineHeight: 24 },
});
