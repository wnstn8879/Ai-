import * as SQLite from "expo-sqlite";
import { createOutboxStore } from "./outboxStore";
let opening;
export function getLocalStore() {
  if (!opening)
    opening = (async () => {
      const database = await SQLite.openDatabaseAsync(
        "storyverse-outbox-v1.db",
      );
      const store = createOutboxStore(database);
      await store.initialize();
      return store;
    })().catch((error) => {
      opening = null;
      throw error;
    });
  return opening;
}
