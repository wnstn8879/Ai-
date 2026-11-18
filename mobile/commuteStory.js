// Version 2 is an authored choice graph. Legacy version 1 saves stay untouched.
export const initialState = () => ({
  scene: 0,
  node: "envelope",
  ending: false,
  clues: [],
});
const options = {
  envelope: ["봉투를 열어본다", "주변에 봉투 주인이 있는지 살핀다"],
  platform: ["승차권의 보관 번호를 확인한다", "역무원에게 사진을 보여준다"],
  locker: ["편지함으로 간다", "편지를 받지 않고 출근한다"],
  decision: ["편지를 주인에게 돌려준다", "편지를 받아 읽는다"],
};
export function optionsFor(room) {
  if (
    room.state.node === "platform" &&
    !room.state.clues.includes("승차권과 사진")
  )
    return ["승차권의 보관 번호를 확인한다", "역무원에게 봉투 주인을 묻는다"];
  return options[room.state.node] || [];
}
export function start(id, title, now) {
  const state = initialState();
  return {
    id,
    title,
    storyVersion: 2,
    parentId: null,
    forkIndex: null,
    createdAt: now,
    updatedAt: now,
    state,
    messages: [
      {
        id: id + ":opening",
        actor: "이야기",
        content:
          "출근길 지하철, 빈 좌석 위에 당신의 이름이 적힌 봉투가 있다. 안에는 분실된 편지를 찾는 단서가 있다는 메모. 다음 역까지 3분이다.\n\n목표: 봉투의 주인을 확인하고, 편지를 어떻게 할지 결정하기.",
        stateAfter: JSON.parse(JSON.stringify(state)),
      },
    ],
  };
}
export function step(room, text, id, now) {
  const content = text.trim();
  if (!content || content.length > 1000)
    throw new Error("행동을 1~1000자로 입력해주세요.");
  if (room.state.ending)
    throw new Error(
      "이 사건은 마무리됐어요. 과거 장면에서 새 분기를 만들어보세요.",
    );
  const next = JSON.parse(JSON.stringify(room));
  next.messages.push({
    id: id + ":user",
    actor: "나",
    content,
    stateAfter: JSON.parse(JSON.stringify(room.state)),
  });
  const chosen = optionsFor(room).indexOf(content);
  let reply;
  if (chosen < 0) {
    reply =
      "적어주신 행동은 기록했어요. 이 선택형 체험에서는 아래 버튼 중 하나를 골라 사건을 진행해주세요. 아직 행동 결과나 선택을 확정하지 않았습니다.";
  } else {
    const s = next.state;
    s.scene++;
    if (s.node === "envelope") {
      if (chosen === 0) {
        s.clues.push("승차권과 사진");
        reply =
          "봉투 안에는 17번 보관함의 승차권과 아이를 안은 역무원 사진이 있다. 플랫폼에서 사진 속 역무원을 발견했다. 승차권부터 확인할까, 사진에 관해 물어볼까?";
      } else {
        s.clues.push("분실 신고 목격담");
        reply =
          "옆 승객이 말한다. ‘아까 역무원이 딸에게 보낼 편지를 찾던데요.’ 플랫폼 끝에 같은 봉투를 든 역무원이 서 있다. 봉투를 열지 않고도 물어볼 단서를 얻었다.";
      }
      s.node = "platform";
    } else if (s.node === "platform") {
      if (chosen === 0) {
        s.clues.push("17번 보관함");
        reply =
          "승차권 뒷면에 ‘17번, 오늘까지만 보관’이라는 메모가 보인다. 보관함은 개찰구 바로 옆이다. 주인이 누구인지는 아직 확실하지 않다.";
      } else {
        s.clues.push("주인 확인");
        reply = s.clues.includes("승차권과 사진")
          ? "역무원은 사진을 보고 고개를 끄덕인다. ‘제 딸 윤서예요. 전하지 못한 편지가 17번 함에 있습니다.’ 사진의 사연과 편지 주인을 확인했다."
          : "사진을 보려 봉투를 열기 전에 역무원이 같은 사진을 꺼낸다. ‘제 딸 윤서예요.’ 봉투를 건네 보이자 자신의 것이라고 확인한다. 편지는 17번 함에 있다고 한다.";
      }
      s.node = "locker";
    } else if (s.node === "locker") {
      if (chosen === 1) {
        s.node = "end";
        s.ending = true;
        s.outcome = "everyday";
        reply =
          "당신은 편지를 받지 않고 출근하기로 했다. 보관함 위치만 역 안내 데스크에 알려둘 수 있다. 이번 사건은 일상을 지키는 선택으로 끝났다. 다른 가능성은 과거 장면의 분기로 남아 있다.";
      } else {
        s.node = "decision";
        reply = s.clues.includes("주인 확인")
          ? "17번 함 앞에서 역무원을 다시 만났다. 봉인된 편지에는 윤서의 이름이 적혀 있다. 이제 주인에게 돌려줄지, 내용을 읽을지 선택할 수 있다."
          : "17번 함에는 윤서라는 이름의 편지가 있다. 역무원이 다가와 자신의 편지라고 말한다. 아직 신원을 확인하지 않은 상태다. 봉인을 열지 않고 전달할 수도 있다.";
      }
    } else {
      s.node = "end";
      s.ending = true;
      if (chosen === 0) {
        s.outcome = s.clues.includes("주인 확인") ? "reunited" : "unverified";
        reply =
          s.outcome === "reunited"
            ? "당신은 확인한 주인에게 봉인된 편지를 돌려줬다. 역무원은 오늘 딸을 만나러 간다며 웃었다. 편지의 내용은 끝내 읽지 않았지만, 누군가의 이야기를 제자리로 돌려놓았다. 이번 사건 완료 — 결말: 전해진 마음."
            : "당신은 편지를 자신이 주인이라고 말한 역무원에게 건넸다. 그는 고맙다며 떠났지만, 사진 속 인물인지 확인하지 않은 의문이 남았다. 이번 사건 완료 — 결말: 남겨진 물음.";
      } else {
        s.outcome = "opened";
        reply =
          "당신은 편지를 받아 읽었다. 오래전 다툰 딸에게 건네려던 서툰 사과가 적혀 있다. 사연은 알게 됐지만 봉인은 되돌릴 수 없다. 이번 사건 완료 — 결말: 열린 비밀. 원하면 편지를 열기 전 장면에서 다른 선택을 해볼 수 있다.";
      }
    }
  }
  next.messages.push({
    id: id + ":story",
    actor: "이야기",
    content: reply,
    stateAfter: JSON.parse(JSON.stringify(next.state)),
  });
  next.updatedAt = now;
  return next;
}
