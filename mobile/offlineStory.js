// Authored preview story, deliberately not presented as generated AI.
export const INTRO =
  "출근길 지하철. 빈 좌석 위에 당신의 이름이 적힌 봉투가 놓여 있다. 다음 역까지 3분. 봉투에는 ‘종점 전에 선택하세요’라고 적혀 있다.";
const scenes = [
  {
    text: "봉투 안에는 오래된 승차권과 역무원의 사진이 있다. 사진 뒷면에 ‘7번 출구’라는 글씨가 보인다. 문이 열리고, 사진 속 인물이 플랫폼에 서 있다.",
    choices: ["플랫폼에서 역무원에게 말을 건다", "열차 안에서 승차권을 살핀다"],
  },
  {
    text: "승차권의 작은 글씨는 잃어버린 편지의 보관 번호였다. 역무원은 편지함 위치를 알려주며 말한다. ‘받을지 말지는 당신이 정하세요.’ 이번 열차를 놓쳐도 다음 열차는 곧 온다.",
    choices: ["편지함으로 간다", "편지를 받지 않고 출근한다"],
  },
  {
    text: "당신 앞에 두 갈래의 시간이 놓인다. 잠깐의 호기심을 따라갈 수도, 오늘의 일상을 지킬 수도 있다. 어느 쪽이든 이 선택은 당신의 것이다.",
    choices: ["편지를 받아 읽는다", "오늘은 일상으로 돌아간다"],
  },
];
export function opening(id, title, now) {
  const state = { scene: 0, ending: false };
  return {
    id,
    title,
    parentId: null,
    forkIndex: null,
    createdAt: now,
    updatedAt: now,
    state,
    messages: [
      {
        id: id + ":opening",
        actor: "이야기",
        content: INTRO,
        stateAfter: state,
      },
    ],
  };
}
export function choicesFor(room) {
  if (room.state.ending) return ["다음 짧은 장면을 시작한다"];
  if (room.state.scene === 0)
    return ["봉투를 열어본다", "주변에 봉투 주인이 있는지 살핀다"];
  return scenes[Math.min(room.state.scene - 1, scenes.length - 1)].choices;
}
export function advance(room, text, id, now) {
  const content = text.trim();
  if (!content || content.length > 1000)
    throw new Error("행동을 1~1000자로 입력해주세요.");
  const next = JSON.parse(JSON.stringify(room));
  next.messages.push({
    id: id + ":user",
    actor: "나",
    content,
    stateAfter: { ...room.state },
  });
  const scene = room.state.ending ? 0 : room.state.scene;
  let reply;
  if (scene < scenes.length) {
    reply = scenes[scene].text;
    next.state = { scene: scene + 1, ending: false };
    if (room.state.ending)
      reply =
        "다음 날 아침, 같은 승강장에 새로운 보관 번호가 나타났다.\n\n" + reply;
    // Authored variations explicitly react to the available choices.
    if (scene === 0 && /주변/.test(content))
      reply =
        "주변 사람들은 고개를 젓는다. 역무원이 다가와 봉투 속 승차권을 확인해도 좋다고 말한다.\n\n" +
        reply;
  } else {
    const everyday = /일상|출근|않|돌아/.test(content);
    reply = everyday
      ? "당신은 오늘의 일상을 선택했다. 열차 문이 닫히고 출근길의 소음이 돌아온다. 봉투의 비밀은 다음에 다시 선택해볼 수 있다. 이번 짧은 장면은 여기서 마무리된다."
      : "편지에는 오래전 이 역을 지키던 이의 감사 인사가 담겨 있었다. 잠깐 멈춘 출근길이 누군가의 기억과 이어졌다. 이번 짧은 장면은 여기서 마무리된다.";
    next.state = { scene: scene + 1, ending: true };
  }
  next.messages.push({
    id: id + ":story",
    actor: "이야기",
    content: reply,
    stateAfter: { ...next.state },
  });
  next.updatedAt = now;
  return next;
}
