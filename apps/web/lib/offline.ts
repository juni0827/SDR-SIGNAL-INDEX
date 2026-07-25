import { openDB, type DBSchema } from "idb";
import { API_BASE, csrfToken } from "./api";

interface Mutation {
  id: string;
  kind: "annotation" | "inbox";
  payload: Record<string, unknown>;
  state: "queued" | "syncing" | "conflict";
  created_at_utc: string;
}
interface SignalDB extends DBSchema {
  mutations: {key: string; value: Mutation; indexes: {"by-state": Mutation["state"]}};
  recent: {key: string; value: {key: string; payload: unknown; cached_at_utc: string}};
}
const database = typeof indexedDB === "undefined" ? null : openDB<SignalDB>("signal-index", 1, {
  upgrade(db) {
    const store = db.createObjectStore("mutations", {keyPath: "id"});
    store.createIndex("by-state", "state");
    db.createObjectStore("recent", {keyPath: "key"});
  },
});

export async function queueOffline(kind: Mutation["kind"], payload: Record<string, unknown>) {
  if (!database) throw new Error("indexeddb_unavailable");
  const row: Mutation = {id: crypto.randomUUID(), kind, payload, state: "queued", created_at_utc: new Date().toISOString()};
  await (await database).put("mutations", row);
  return row;
}

export async function syncMutations() {
  if (!database || !navigator.onLine) return;
  const db = await database;
  const rows = await db.getAllFromIndex("mutations", "by-state", "queued");
  for (const row of rows) {
    const csrf = csrfToken();
    const response = await fetch(`${API_BASE}/${row.kind === "annotation" ? "annotations" : "inbox"}`, {
      method: "POST",
      credentials: "include",
      headers: {"content-type": "application/json", ...(csrf ? {"x-csrf-token": csrf} : {})},
      body: JSON.stringify({...row.payload, offline_id: row.id}),
    });
    if (response.status === 409) {
      await db.put("mutations", {...row, state: "conflict"});
    } else if (!response.ok) {
      throw new Error(`offline_sync_failed:${response.status}`);
    } else {
      await db.delete("mutations", row.id);
    }
  }
}

