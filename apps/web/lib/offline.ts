import { openDB, type DBSchema } from "idb";
import { API_BASE, csrfToken } from "./api";

interface Mutation {
  id: string;
  kind: "annotation" | "inbox" | "inbox_file";
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
  window.dispatchEvent(new Event("signal-offline-queue"));
  if ("serviceWorker" in navigator) {
    void navigator.serviceWorker.ready.then(async registration => {
      const syncManager = (registration as ServiceWorkerRegistration & {sync?: {register(tag: string): Promise<void>}}).sync;
      if (syncManager) await syncManager.register("signal-index-sync");
    }).catch((error: unknown) => console.error("background_sync_registration_failed", error));
  }
  return row;
}

export async function syncMutations() {
  if (!database || !navigator.onLine) return { synced: 0, conflicts: 0, queued: 0 };
  const db = await database;
  const rows = await db.getAllFromIndex("mutations", "by-state", "queued");
  let synced = 0;
  let conflicts = 0;
  for (const row of rows) {
    const csrf = csrfToken();
    let response: Response;
    if (row.kind === "inbox_file") {
      const form = new FormData();
      for (const [key, value] of Object.entries(row.payload)) {
        if (value == null) continue;
        form.set(key, value instanceof Blob ? value : String(value));
      }
      form.set("client_id", row.id);
      response = await fetch(`${API_BASE}/inbox/upload`, {
        method: "POST",
        credentials: "include",
        headers: {...(csrf ? {"x-csrf-token": csrf} : {})},
        body: form,
      });
    } else {
      response = await fetch(`${API_BASE}/${row.kind === "annotation" ? "annotations" : "inbox"}`, {
        method: "POST",
        credentials: "include",
        headers: {"content-type": "application/json", ...(csrf ? {"x-csrf-token": csrf} : {})},
        body: JSON.stringify({...row.payload, client_id: row.id}),
      });
    }
    if (response.status === 409) {
      await db.put("mutations", {...row, state: "conflict"});
      window.dispatchEvent(new Event("signal-offline-queue"));
      conflicts += 1;
    } else if (!response.ok) {
      throw new Error(`offline_sync_failed:${response.status}`);
    } else {
      await db.delete("mutations", row.id);
      window.dispatchEvent(new Event("signal-offline-queue"));
      synced += 1;
    }
  }
  const queued = (await db.getAllFromIndex("mutations", "by-state", "queued")).length;
  conflicts += (await db.getAllFromIndex("mutations", "by-state", "conflict")).length;
  return { synced, conflicts, queued };
}

export async function offlineQueueStatus() {
  if (!database) return { conflicts: 0, queued: 0 };
  const db = await database;
  const [conflicts, queued] = await Promise.all([
    db.getAllFromIndex("mutations", "by-state", "conflict"),
    db.getAllFromIndex("mutations", "by-state", "queued"),
  ]);
  return { conflicts: conflicts.length, queued: queued.length };
}
