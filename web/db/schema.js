import { sqliteTable, text, integer, index } from "drizzle-orm/sqlite-core";
export const requests = sqliteTable(
  "relay_requests",
  {
    id: text("id").primaryKey(),
    visitor: text("visitor").notNull(),
    path: text("path").notNull(),
    method: text("method").notNull(),
    body: text("body"),
    status: text("status").notNull().default("pending"),
    response: text("response"),
    httpStatus: integer("http_status"),
    created: integer("created").notNull(),
    expires: integer("expires").notNull(),
  },
  (t) => [index("relay_status").on(t.status, t.created)],
);
export const cache = sqliteTable("story_cache", {
  key: text("key").primaryKey(),
  visitor: text("visitor").notNull(),
  path: text("path").notNull(),
  payload: text("payload").notNull(),
  updated: integer("updated").notNull(),
});
export const health = sqliteTable("relay_health", {
  id: text("id").primaryKey(),
  updated: integer("updated").notNull(),
});
