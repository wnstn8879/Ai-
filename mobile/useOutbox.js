import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { getLocalStore } from "./localStore";
import { createOutboxWorker } from "./outboxWorker";
import { API, requestForUser } from "./api";

export function useOutbox(user, onSent) {
  const [store, setStore] = useState(null),
    [items, setItems] = useState([]),
    [error, setError] = useState("");
  const worker = useRef(null),
    callback = useRef(onSent);
  callback.current = onSent;
  const scope = user ? { api: API, userId: user.id } : null;
  useEffect(() => {
    let stopped = false,
      controller;
    setStore(null);
    setItems([]);
    setError("");
    if (!user) return;
    getLocalStore()
      .then(async (local) => {
        await local.reviewUnsentAI({ api: API, userId: user.id });
        if (stopped) return;
        controller = createOutboxWorker({
          store: local,
          scope: { api: API, userId: user.id },
          send: requestForUser,
          onChange: (rows) => {
            if (!stopped) setItems(rows);
          },
          onSent: (roomId) => callback.current?.(user.id, roomId),
          onError: (e) => {
            if (!stopped)
              setError("기기 저장소를 확인할 수 없습니다. " + e.message);
          },
        });
        worker.current = controller;
        setStore(local);
        controller.setActive(AppState.currentState === "active");
      })
      .catch((e) => {
        if (!stopped) setError("전송 기록을 열 수 없습니다. " + e.message);
      });
    const subscription = AppState.addEventListener("change", (state) =>
      controller?.setActive(state === "active"),
    );
    return () => {
      stopped = true;
      subscription.remove();
      controller?.stop();
      if (worker.current === controller) worker.current = null;
    };
  }, [user?.id]);
  const enqueue = async (data) => {
    if (!store || !scope)
      throw new Error(
        "기기 저장소를 준비하는 중입니다. 잠시 후 다시 시도해주세요.",
      );
    const row = await store.enqueue(scope, data);
    worker.current?.wake(data.kind === "turn" ? row.requestId : undefined);
    return row;
  };
  const retry = async (row) => {
    await store.retry(scope, row.requestId);
    worker.current?.wake(row.kind === "turn" ? row.requestId : undefined);
  };
  const discard = async (row) => {
    await store.discard(scope, row.requestId);
    worker.current?.wake();
  };
  return { store, scope, items, error, enqueue, retry, discard };
}

export function useRoomDraft(store, scope, roomId) {
  const [input, setValue] = useState(""),
    [status, setStatus] = useState("loading");
  const current = useRef({ key: "", version: 0 }),
    text = useRef("");
  const key =
    scope && roomId ? JSON.stringify([scope.api, scope.userId, roomId]) : "";
  useEffect(() => {
    const own = { key, version: 0 };
    current.current = own;
    text.current = "";
    setValue("");
    setStatus("loading");
    let stopped = false;
    if (store && key)
      store
        .getDraft(scope, roomId)
        .then((value) => {
          if (!stopped && current.current === own) {
            text.current = value;
            setValue(value);
            setStatus("saved");
          }
        })
        .catch(() => {
          if (!stopped) setStatus("error");
        });
    return () => {
      stopped = true;
    };
  }, [store, key]);
  const change = (value) => {
    if (!store || !key || current.current.key !== key) return;
    const own = current.current,
      version = ++own.version;
    text.current = value;
    setValue(value);
    setStatus("saving");
    store
      .saveDraft(scope, roomId, value)
      .then(() => {
        if (current.current === own && own.version === version)
          setStatus("saved");
      })
      .catch(() => {
        if (current.current === own && own.version === version)
          setStatus("error");
      });
  };
  const clearQueued = (value) => {
    if (current.current.key === key && text.current.trim() === value) {
      current.current.version++;
      text.current = "";
      setValue("");
      setStatus("saved");
    }
  };
  return {
    input,
    setInput: change,
    status,
    ready: status !== "loading" && !!store,
    clearQueued,
  };
}
