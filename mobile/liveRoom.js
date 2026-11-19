// A single reconnect owner prevents foreground events and retry timers opening duplicate sockets.
export function connectLiveRoom({
  url,
  getToken,
  onSnapshot,
  onStatus,
  onDenied,
  WebSocketImpl = WebSocket,
  schedule = setTimeout,
  cancel = clearTimeout,
}) {
  let stopped = false,
    connecting = false,
    socket = null,
    timer = null,
    failures = 0,
    generation = 0;
  const status = (value) => {
    if (!stopped) onStatus(value);
  };
  const retry = () => {
    if (stopped || timer !== null) return;
    status("연결 끊김 · 재연결 중");
    timer = schedule(
      () => {
        timer = null;
        connect();
      },
      Math.min(30000, 1000 * 2 ** Math.min(failures++, 5)),
    );
  };
  const connect = async () => {
    if (stopped || connecting || (socket && socket.readyState < 2)) return;
    connecting = true;
    const own = ++generation;
    try {
      status("연결 중");
      const access_token = await getToken();
      if (stopped || own !== generation) return;
      const current = new WebSocketImpl(url);
      socket = current;
      const active = () => !stopped && own === generation && socket === current;
      current.onopen = () => {
        if (active()) current.send(JSON.stringify({ access_token }));
      };
      current.onmessage = (event) => {
        if (!active()) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === "snapshot" && data.room) {
            failures = 0;
            status("실시간 연결됨");
            onSnapshot(data.room);
          }
        } catch {
          status("동기화 오류");
        }
      };
      current.onerror = () => {
        if (active()) status("연결 끊김 · 재연결 중");
      };
      current.onclose = (event) => {
        if (!active()) return;
        socket = null;
        if (event.code === 4403) {
          status("방 참여 권한이 없습니다.");
          stopped = true;
          onDenied?.();
          return;
        }
        retry();
      };
    } catch {
      if (!stopped && own === generation) retry();
    } finally {
      if (own === generation) connecting = false;
    }
  };
  connect();
  return {
    resume() {
      if (stopped) return;
      if (socket?.readyState === 1) {
        socket.send("sync");
        return;
      }
      if (connecting || socket?.readyState === 0) return;
      if (timer !== null) {
        cancel(timer);
        timer = null;
      }
      connect();
    },
    stop() {
      stopped = true;
      generation++;
      if (timer !== null) cancel(timer);
      socket?.close();
    },
  };
}
