// All dependencies are injected so the same controller runs in the browser and tests.
export function createWriterClient({
  api,
  onStatus,
  onCommit,
  onError,
  id,
  visible = () => true,
  now = () => Date.now(),
  schedule = setTimeout,
  cancel = clearTimeout,
}) {
  let room = null,
    epoch = 0,
    timer = null,
    lease = "",
    state = null,
    lastCount = 0,
    lastAlive = 0;
  const path = () => "/rooms/" + room + "/writer";
  function clear() {
    if (timer !== null) cancel(timer);
    timer = null;
  }
  async function consume(next, own) {
    if (own !== epoch) return;
    state = next;
    onStatus(next);
    if (next.message_count > lastCount) {
      lastCount = next.message_count;
      await onCommit(next, room);
    }
  }
  async function poll(own) {
    if (own !== epoch || !room) return;
    try {
      await consume(await api(path()), own);
      if (own !== epoch) return;
      if (
        state.status === "writing" &&
        lease === state.run_id &&
        visible() &&
        now() - lastAlive >= 15000
      ) {
        lastAlive = now();
        await consume(
          await api(path() + "/keepalive", "POST", { run_id: lease }),
          own,
        );
      }
    } catch (error) {
      if (own === epoch) onError(error);
    }
    if (own === epoch && state?.status === "writing" && visible())
      timer = schedule(() => {
        timer = null;
        poll(own);
      }, 2500);
  }
  return {
    async open(roomId, messageCount) {
      clear();
      const own = ++epoch;
      room = roomId;
      lease = "";
      state = null;
      lastCount = messageCount;
      await poll(own);
    },
    async start(direction = "") {
      if (!room) return;
      clear();
      const own = ++epoch;
      const startingRoom = room;
      const next = await api(path() + "/start", "POST", {
        request_id: id(),
        direction,
        sections: 4,
        continuous: true,
      });
      if (own !== epoch) {
        await api("/rooms/" + startingRoom + "/writer/pause", "POST", {
          run_id: next.run_id,
        });
        return;
      }
      lease = next.run_id;
      lastAlive = 0;
      await consume(next, own);
      await poll(own);
    },
    async pause() {
      if (!room) return;
      clear();
      const own = ++epoch;
      const runId = state?.run_id || lease;
      lease = "";
      try {
        await consume(
          await api(path() + "/pause", "POST", { run_id: runId }),
          own,
        );
      } catch (error) {
        if (own === epoch) onError(error);
      }
    },
    async direction(content) {
      if (!state || state.status !== "writing") return this.start(content);
      const own = epoch;
      await consume(
        await api(path() + "/direction", "POST", { request_id: id(), content }),
        own,
      );
    },
    async leave() {
      clear();
      const previous = room,
        runId = lease;
      ++epoch;
      room = null;
      lease = "";
      state = null;
      if (previous && runId) {
        try {
          await api("/rooms/" + previous + "/writer/pause", "POST", {
            run_id: runId,
          });
        } catch (error) {
          onError(error);
        }
      }
    },
    get state() {
      return state;
    },
  };
}
