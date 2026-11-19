export function createOutboxWorker({
  store,
  scope,
  send,
  onChange = () => {},
  onSent = () => {},
  onError = () => {},
  now = () => Date.now(),
  schedule = setTimeout,
  cancel = clearTimeout,
}) {
  let stopped = false,
    active = true,
    running = false,
    timer = null,
    again = false;
  const approvedAI = new Set();
  const notify = async () => {
    const rows = await store.list(scope);
    if (!stopped) onChange(rows);
    return rows;
  };
  const process = async (row) => {
    if (stopped || !active) return;
    if (row.kind === "turn" && !approvedAI.has(row.requestId)) return;
    if (!(await store.claim(scope, row.requestId))) return;
    approvedAI.delete(row.requestId);
    try {
      await notify();
      if (stopped || !active) {
        await store.finish(
          scope,
          row.requestId,
          row.kind === "turn" ? "review" : "queued",
        );
        return;
      }
      await send(
        scope.userId,
        "/rooms/" + row.roomId + (row.kind === "turn" ? "/turns" : "/messages"),
        "POST",
        { actor: row.actor, content: row.content, request_id: row.requestId },
      );
      await store.finish(scope, row.requestId, "sent");
      if (!stopped) await onSent(row.roomId);
    } catch (error) {
      const status = error.status;
      const review = row.kind === "turn" || status === 409;
      const blocked =
        status &&
        status >= 400 &&
        status < 500 &&
        ![401, 409, 429].includes(status);
      const next =
        now() +
        (status === 429
          ? Math.max(1, error.retryAfter || 60) * 1000
          : Math.min(60000, 2000 * 2 ** Math.min(row.attempts, 5)));
      await store.finish(
        scope,
        row.requestId,
        review ? "review" : blocked ? "blocked" : "queued",
        error.message,
        next,
      );
    }
  };
  const cycle = async () => {
    if (stopped || !active) return;
    if (running) {
      again = true;
      return;
    }
    running = true;
    try {
      do {
        again = false;
        const rows = await notify();
        const rooms = new Set();
        for (const row of rows) {
          if (stopped || !active) break;
          if (rooms.has(row.roomId)) continue;
          rooms.add(row.roomId);
          if (row.status === "queued" && row.nextAttemptAt <= now())
            await process(row);
        }
        await notify();
      } while (again && !stopped && active);
    } catch (error) {
      if (!stopped) onError(error);
    } finally {
      running = false;
      if (!stopped && active)
        timer = schedule(() => {
          timer = null;
          cycle();
        }, 5000);
    }
  };
  return {
    wake(requestId) {
      if (requestId) approvedAI.add(requestId);
      if (timer !== null) {
        cancel(timer);
        timer = null;
      }
      return cycle();
    },
    setActive(value) {
      active = value;
      if (active) return this.wake();
      if (timer !== null) {
        cancel(timer);
        timer = null;
      }
    },
    stop() {
      stopped = true;
      if (timer !== null) cancel(timer);
    },
  };
}
