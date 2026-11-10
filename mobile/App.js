import React, { useEffect, useRef, useState } from "react";
import {
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  Pressable,
  View,
  Alert,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  AppState,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import * as Crypto from "expo-crypto";
import {
  API,
  request,
  authenticate,
  restoreSession,
  onExpired,
  accessToken,
  logout,
} from "./api";

export default function App() {
  const [user, setUser] = useState(null),
    [ready, setReady] = useState(false),
    [register, setRegister] = useState(false);
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState("");
  const [tab, setTab] = useState("home"),
    [rooms, setRooms] = useState([]),
    [room, setRoom] = useState(null),
    [saves, setSaves] = useState([]),
    [members, setMembers] = useState([]);
  const [title, setTitle] = useState("사라진 왕국"),
    [rules, setRules] = useState("설정을 임의로 변경하지 않는다."),
    [characters, setCharacters] = useState("");
  const [mode, setMode] = useState("solo"),
    [input, setInput] = useState(""),
    [label, setLabel] = useState("중요한 선택 전");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [live, setLive] = useState("연결 대기");
  const [friends, setFriends] = useState([]),
    [query, setQuery] = useState(""),
    [results, setResults] = useState([]),
    [code, setCode] = useState(""),
    [inviteCode, setInviteCode] = useState("");
  const [character, setCharacter] = useState(""),
    [filter, setFilter] = useState("all");
  const pending = useRef(null),
    busyRef = useRef(false);
  const reset = () => {
    setUser(null);
    setRoom(null);
    setRooms([]);
    setSaves([]);
    setFriends([]);
    setMembers([]);
    setResults([]);
    setInput("");
    setPassword("");
    setCode("");
    setInviteCode("");
    setError("");
    setNotice("");
    setTab("home");
    pending.current = null;
  };
  const run = async (fn) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const refresh = async () => setRooms(await request("/rooms"));
  const open = async (id) => {
    const [r, s, m] = await Promise.all([
      request("/rooms/" + id),
      request("/rooms/" + id + "/saves"),
      request("/rooms/" + id + "/members"),
    ]);
    setRoom(r);
    setSaves(s);
    setMembers(m);
    setInviteCode("");
    setInput("");
    pending.current = null;
  };
  useEffect(() => {
    onExpired(reset);
    restoreSession()
      .then((s) => {
        if (s) setUser(s.user);
      })
      .catch((e) => setError(e.message))
      .finally(() => setReady(true));
    return () => onExpired(() => {});
  }, []);
  useEffect(() => {
    if (user) run(refresh);
  }, [user?.id]);
  // Database snapshots are authoritative and ordered; reconnect loads the full persisted story.
  useEffect(() => {
    if (!room || !user || room.mode !== "multiplayer") return;
    let stopped = false,
      socket,
      timer,
      attempt = 0;
    const connect = async () => {
      try {
        await request("/auth/me");
        const token = await accessToken();
        if (stopped) return;
        socket = new WebSocket(
          API.replace(/^http/, "ws") + "/rooms/" + room.id + "/live",
        );
        socket.onopen = () => {
          if (stopped) {
            socket.close();
            return;
          }
          socket.send(JSON.stringify({ access_token: token }));
          setLive("실시간 연결됨");
          attempt = 0;
        };
        socket.onmessage = (event) => {
          if (stopped) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === "snapshot") setRoom(data.room);
          } catch {
            setLive("동기화 오류");
          }
        };
        socket.onerror = () => {
          if (!stopped) setLive("연결 끊김 · 재연결 중");
        };
        socket.onclose = () => {
          if (!stopped) {
            setLive("연결 끊김 · 재연결 중");
            timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt++));
          }
        };
      } catch {
        if (!stopped) {
          setLive("연결 확인 필요");
          timer = setTimeout(connect, 5000);
        }
      }
    };
    connect();
    const subscription = AppState.addEventListener("change", (state) => {
      if (
        state === "active" &&
        !stopped &&
        (!socket || socket.readyState === 3)
      ) {
        clearTimeout(timer);
        connect();
      }
    });
    return () => {
      stopped = true;
      clearTimeout(timer);
      subscription.remove();
      socket?.close();
    };
  }, [room?.id, user?.id]);
  const create = () =>
    run(async () => {
      const r = await request("/rooms", "POST", {
        title,
        world_rules: rules,
        characters: characters
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        mode,
      });
      await refresh();
      await open(r.id);
    });
  const send = (ai) =>
    run(async () => {
      if (!input.trim()) return;
      const path = "/rooms/" + room.id + (ai ? "/turns" : "/messages");
      const content = input.trim();
      if (
        !pending.current ||
        pending.current.content !== content ||
        pending.current.path !== path
      )
        pending.current = { request_id: Crypto.randomUUID(), content, path };
      const actor =
        members.find((m) => m.user_id === user.id)?.character ||
        user.display_name;
      await request(path, "POST", {
        actor,
        content,
        request_id: pending.current.request_id,
      });
      pending.current = null;
      setInput("");
      await open(room.id);
    });
  const save = () =>
    run(async () => {
      await request("/rooms/" + room.id + "/saves", "POST", {
        label,
        message_index: room.messages.length,
      });
      await open(room.id);
      setNotice("개인 저장 지점을 저장했습니다.");
    });
  const resume = (s) =>
    run(async () => {
      const r = await request("/saves/" + s.id + "/resume", "POST");
      await refresh();
      await open(r.id);
    });
  const fork = (index) =>
    run(async () => {
      const r = await request("/rooms/" + room.id + "/forks", "POST", {
        title: room.title + " · 다른 선택",
        message_index: index,
      });
      await refresh();
      await open(r.id);
    });
  const loadFriends = async () => setFriends(await request("/friends"));
  const navigate = (t) =>
    run(async () => {
      setRoom(null);
      setTab(t);
      if (t === "friends") await loadFriends();
      else await refresh();
    });
  const btn = (text, fn, secondary = false) => (
    <Pressable
      accessibilityRole="button"
      disabled={busy}
      onPress={fn}
      style={[
        styles.button,
        secondary && styles.secondary,
        busy && styles.disabled,
      ]}
    >
      <Text style={styles.buttonText}>{text}</Text>
    </Pressable>
  );
  const field = (value, change, placeholder, extra = {}) => (
    <TextInput
      accessibilityLabel={placeholder}
      style={styles.input}
      value={value}
      onChangeText={change}
      placeholder={placeholder}
      placeholderTextColor="#99a8bd"
      {...extra}
    />
  );
  const owner = members.find((m) => m.user_id === user?.id)?.role === "owner";
  const shown = rooms.filter(
    (r) =>
      filter === "all" ||
      r.mode === filter ||
      (filter === "mine" && r.role === "owner") ||
      (filter === "joined" && r.role === "participant"),
  );
  if (!ready)
    return (
      <SafeAreaView style={styles.root}>
        <ActivityIndicator
          accessibilityLabel="세션 불러오는 중"
          color="#b3a5ff"
        />
      </SafeAreaView>
    );
  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={styles.body}
        >
          <Text style={styles.brand}>
            STORYVERSE <Text style={styles.accent}>AI</Text>
          </Text>
          {busy && <ActivityIndicator color="#b3a5ff" />}
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
          {!user ? (
            <>
              <Text style={styles.hero}>
                당신의 선택이{"\n"}새로운 세계가 됩니다.
              </Text>
              <Text style={styles.muted}>
                이야기를 저장하고 친구와 함께 이어가세요.
              </Text>
              <Text style={styles.heading}>
                {register ? "계정 만들기" : "다시 만나 반가워요"}
              </Text>
              {field(email, setEmail, "이메일", {
                autoCapitalize: "none",
                keyboardType: "email-address",
                autoComplete: "email",
              })}
              {field(password, setPassword, "비밀번호 (10자 이상)", {
                secureTextEntry: true,
                autoCapitalize: "none",
                autoComplete: register ? "new-password" : "current-password",
              })}
              {register && field(name, setName, "표시 이름")}
              {btn(register ? "회원가입" : "로그인", () =>
                run(async () => {
                  const s = await authenticate(register, {
                    email,
                    password,
                    ...(register ? { display_name: name } : {}),
                  });
                  setPassword("");
                  setUser(s.user);
                }),
              )}
              {btn(
                register ? "이미 계정이 있어요" : "새 계정 만들기",
                () => setRegister(!register),
                true,
              )}
            </>
          ) : room ? (
            <>
              {btn(
                "← 보관함으로",
                () =>
                  run(async () => {
                    await refresh();
                    setRoom(null);
                  }),
                true,
              )}
              <Text style={styles.hero}>{room.title}</Text>
              <Text style={styles.muted}>
                {room.mode === "solo" ? "혼자 플레이" : "함께 플레이 · " + live}{" "}
                · 자동 저장
              </Text>
              {room.parent_room_id && (
                <Text selectable style={styles.muted}>
                  평행세계 · 부모 스토리 {room.parent_room_id}
                </Text>
              )}
              {room.messages.length === 0 && (
                <Text style={styles.muted}>
                  첫 행동이나 대사로 이야기를 시작하세요.
                </Text>
              )}
              {room.messages.map((m, i) => (
                <View
                  key={m.id}
                  style={[styles.card, m.actor === "AI" && styles.ai]}
                >
                  <Text style={styles.accent}>{m.actor}</Text>
                  <Text selectable style={styles.message}>
                    {m.content}
                  </Text>
                  {btn("여기서 개인 평행세계 만들기", () => fork(i + 1), true)}
                </View>
              ))}
              {field(input, setInput, "행동이나 대사 입력", {
                multiline: true,
                maxLength: 5000,
              })}
              {btn("AI와 이야기 이어가기", () => send(true))}
              {room.mode === "multiplayer" &&
                btn("참가자에게 메시지 보내기", () => send(false), true)}
              {btn("대화 새로고침", () => run(() => open(room.id)), true)}
              <Text style={styles.heading}>나의 저장 지점</Text>
              {field(label, setLabel, "저장 이름")}
              {btn("현재 장면 저장", save)}
              {saves.length === 0 && (
                <Text style={styles.muted}>
                  아직 수동 저장 지점이 없습니다. 메시지는 자동 저장됩니다.
                </Text>
              )}
              {saves.map((s) => (
                <View style={styles.card} key={s.id}>
                  <Text style={styles.text}>
                    {s.label} · {s.message_index}번째 메시지
                  </Text>
                  {btn("개인 분기로 이어하기", () => resume(s), true)}
                </View>
              ))}
              {btn("처음부터 개인 분기 만들기", () => fork(0), true)}
              {room.mode === "multiplayer" && (
                <>
                  <Text style={styles.heading}>참가자</Text>
                  {members.map((m) => (
                    <View key={m.user_id} style={styles.card}>
                      <Text style={styles.text}>
                        {m.display_name} ·{" "}
                        {m.role === "owner" ? "방장" : "참가자"} ·{" "}
                        {m.character || "캐릭터 미배정"}
                      </Text>
                      {owner &&
                        btn(
                          "입력한 캐릭터 배정",
                          () =>
                            run(async () => {
                              await request(
                                "/rooms/" + room.id + "/members/" + m.user_id,
                                "PUT",
                                { character },
                              );
                              await open(room.id);
                            }),
                          true,
                        )}
                    </View>
                  ))}
                  {owner ? (
                    <>
                      {field(character, setCharacter, "배정할 캐릭터 이름")}
                      {btn("1회용 초대 코드 만들기", () =>
                        run(async () =>
                          setInviteCode(
                            (
                              await request(
                                "/rooms/" + room.id + "/invitations",
                                "POST",
                              )
                            ).code,
                          ),
                        ),
                      )}
                      {!!inviteCode && (
                        <Text selectable style={styles.notice}>
                          24시간 유효 · 길게 눌러 복사{"\n"}
                          {inviteCode}
                        </Text>
                      )}
                    </>
                  ) : (
                    btn(
                      "방 나가기",
                      () =>
                        run(async () => {
                          await request("/rooms/" + room.id + "/leave", "POST");
                          setRoom(null);
                          await refresh();
                        }),
                      true,
                    )
                  )}
                </>
              )}
            </>
          ) : tab === "friends" ? (
            <>
              <Text style={styles.hero}>함께할 친구</Text>
              {field(query, setQuery, "표시 이름 또는 사용자 ID (3자 이상)")}
              {btn("사용자 검색", () =>
                run(async () =>
                  setResults(
                    await request("/users?q=" + encodeURIComponent(query)),
                  ),
                ),
              )}
              {results.map((u) => (
                <View style={styles.card} key={u.id}>
                  <Text style={styles.text}>{u.display_name}</Text>
                  {btn(
                    "친구 요청",
                    () =>
                      run(async () => {
                        await request("/friends/requests", "POST", {
                          user_id: u.id,
                        });
                        await loadFriends();
                        setNotice("친구 요청을 보냈습니다.");
                      }),
                    true,
                  )}
                </View>
              ))}
              <Text style={styles.heading}>친구 및 요청</Text>
              {friends.length === 0 && (
                <Text style={styles.muted}>
                  친구를 검색해 첫 요청을 보내세요.
                </Text>
              )}
              {friends.map((f) => (
                <View key={f.user_id} style={styles.card}>
                  <Text style={styles.text}>
                    {f.display_name} ·{" "}
                    {f.status === "accepted"
                      ? "친구"
                      : f.incoming
                        ? "받은 요청"
                        : "수락 대기"}
                  </Text>
                  {f.status === "pending" && f.incoming && (
                    <>
                      {btn("수락", () =>
                        run(async () => {
                          await request(
                            "/friends/requests/" + f.user_id + "/respond",
                            "POST",
                            { accept: true },
                          );
                          await loadFriends();
                        }),
                      )}
                      {btn(
                        "거절",
                        () =>
                          run(async () => {
                            await request(
                              "/friends/requests/" + f.user_id + "/respond",
                              "POST",
                              { accept: false },
                            );
                            await loadFriends();
                          }),
                        true,
                      )}
                    </>
                  )}
                </View>
              ))}
              {btn("친구 목록 새로고침", () => run(loadFriends), true)}
              <Text style={styles.heading}>초대받은 스토리</Text>
              {field(code, setCode, "초대 코드", { autoCapitalize: "none" })}
              {btn("초대 코드로 참여", () =>
                run(async () => {
                  const r = await request("/invitations/join", "POST", {
                    code: code.trim(),
                  });
                  setCode("");
                  await refresh();
                  await open(r.room_id);
                }),
              )}
            </>
          ) : tab === "settings" ? (
            <>
              <Text style={styles.hero}>내 프로필</Text>
              <Text style={styles.text}>{user.display_name}</Text>
              <Text style={styles.muted}>{user.email}</Text>
              <Text selectable style={styles.muted}>
                사용자 ID · {user.id}
              </Text>
              {btn(
                "로그아웃",
                () =>
                  run(async () => {
                    await logout();
                    reset();
                  }),
                true,
              )}
            </>
          ) : (
            <>
              <Text style={styles.hero}>
                {tab === "home"
                  ? "어떤 이야기를\n만들어볼까요?"
                  : "나의 스토리 보관함"}
              </Text>
              {tab === "home" && (
                <>
                  <Text style={styles.heading}>새로운 세계</Text>
                  {field(title, setTitle, "스토리 제목")}
                  {field(rules, setRules, "세계관 규칙", { multiline: true })}
                  {field(
                    characters,
                    setCharacters,
                    "캐릭터 이름 (쉼표로 구분)",
                  )}
                  {btn(
                    mode === "solo"
                      ? "모드 · 혼자 플레이"
                      : "모드 · 친구와 함께",
                    () => setMode(mode === "solo" ? "multiplayer" : "solo"),
                    true,
                  )}
                  {btn("스토리 시작", create)}
                </>
              )}
              <Text style={styles.heading}>최근 플레이한 스토리</Text>
              <View style={styles.filters}>
                {["all", "mine", "joined", "solo", "multiplayer"].map(
                  (f, i) => (
                    <Pressable
                      key={f}
                      disabled={busy}
                      onPress={() => setFilter(f)}
                      style={[styles.chip, filter === f && styles.selected]}
                    >
                      <Text style={styles.text}>
                        {["전체", "내가 만든", "참여 중", "혼자", "함께"][i]}
                      </Text>
                    </Pressable>
                  ),
                )}
              </View>
              {shown.length === 0 && (
                <Text style={styles.muted}>
                  저장된 스토리가 없습니다. 새 세계를 만들거나 초대로
                  참여하세요.
                </Text>
              )}
              {shown.map((r) => (
                <View style={styles.card} key={r.id}>
                  <Text style={styles.heading}>{r.title}</Text>
                  <Text style={styles.muted}>
                    {r.mode === "solo" ? "혼자" : "함께"}
                    {r.role === "owner"
                      ? " · 내가 만든 이야기"
                      : " · 참여 중"}{" "}
                    · {r.messages.length}개 메시지
                    {r.parent_room_id ? " · 평행세계" : ""}
                  </Text>
                  {r.parent_room_id && (
                    <Text selectable style={styles.muted}>
                      부모 · {r.parent_room_id}
                    </Text>
                  )}
                  {btn(
                    "마지막 장면에서 이어하기",
                    () => run(() => open(r.id)),
                    true,
                  )}
                </View>
              ))}
              {btn("보관함 새로고침", () => run(refresh), true)}
            </>
          )}
        </ScrollView>
        {user && !room && (
          <View style={styles.nav}>
            {[
              ["home", "홈"],
              ["library", "보관함"],
              ["friends", "친구"],
              ["settings", "설정"],
            ].map(([id, text]) => (
              <Pressable
                accessibilityRole="tab"
                accessibilityState={{ selected: tab === id }}
                key={id}
                disabled={busy}
                onPress={() => navigate(id)}
                style={styles.navItem}
              >
                <Text style={tab === id ? styles.accent : styles.muted}>
                  {text}
                </Text>
              </Pressable>
            ))}
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  flex: { flex: 1 },
  root: {
    flex: 1,
    backgroundColor: "#0e1421",
    paddingTop: Platform.OS === "android" ? 28 : 0,
  },
  body: { padding: 20, paddingBottom: 36, gap: 14 },
  brand: {
    fontSize: 18,
    color: "#f3f3ff",
    letterSpacing: 2,
    fontWeight: "800",
  },
  hero: {
    fontSize: 29,
    lineHeight: 38,
    color: "#f3f3ff",
    fontWeight: "700",
    marginTop: 18,
  },
  heading: { fontSize: 18, color: "#f3f3ff", fontWeight: "700", marginTop: 8 },
  muted: { color: "#a8b5c9", lineHeight: 22 },
  accent: { color: "#b9a6ff", fontWeight: "700" },
  input: {
    borderWidth: 1,
    borderColor: "#3a4962",
    backgroundColor: "#151f30",
    color: "white",
    borderRadius: 12,
    padding: 14,
    minHeight: 50,
    fontSize: 16,
  },
  card: { backgroundColor: "#1b2639", padding: 16, borderRadius: 14, gap: 10 },
  ai: { borderLeftWidth: 3, borderLeftColor: "#a48bf0" },
  text: { color: "#eef2fa", lineHeight: 23 },
  message: { color: "#eef2fa", fontSize: 16, lineHeight: 27 },
  button: {
    backgroundColor: "#7160c8",
    padding: 14,
    borderRadius: 11,
    alignItems: "center",
    minHeight: 48,
  },
  secondary: { backgroundColor: "#293752" },
  disabled: { opacity: 0.55 },
  buttonText: { color: "white", fontWeight: "600", textAlign: "center" },
  error: {
    color: "#ffb7b7",
    backgroundColor: "#3a202d",
    padding: 12,
    borderRadius: 8,
  },
  notice: { color: "#b4e9cd", lineHeight: 24 },
  nav: {
    flexDirection: "row",
    borderTopWidth: 1,
    borderColor: "#334158",
    paddingVertical: 8,
  },
  navItem: { flex: 1, alignItems: "center", paddingVertical: 12 },
  filters: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { padding: 10, borderRadius: 20, backgroundColor: "#26334a" },
  selected: { backgroundColor: "#7160c8" },
});
