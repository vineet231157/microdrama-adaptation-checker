/** Thin client for the FastAPI backend. */

export const BACKEND =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export interface TaskState {
  task_id: string;
  mode: "pipeline" | "format";
  status: "queued" | "running" | "done" | "error";
  step: number;
  step_label: string;
  percent: number;
  show_title: string;
  log: { ts: number; level: string; msg: string }[];
  artifacts: Record<string, string>;
  drive: Record<string, string>;
  error: string | null;
}

export async function startPipeline(form: FormData): Promise<{ task_id: string }> {
  const res = await fetch(`${BACKEND}/api/start-pipeline`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`start-pipeline failed: ${await res.text()}`);
  return res.json();
}

export async function startFormat(form: FormData): Promise<{ task_id: string }> {
  const res = await fetch(`${BACKEND}/api/format`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`format failed: ${await res.text()}`);
  return res.json();
}

export async function getStatus(taskId: string): Promise<TaskState> {
  const res = await fetch(`${BACKEND}/api/task-status/${taskId}`);
  if (!res.ok) throw new Error("status failed");
  return res.json();
}

/**
 * Subscribe to live progress via SSE. Returns an unsubscribe function.
 * Falls back to polling if EventSource errors out.
 */
export function streamStatus(
  taskId: string,
  onUpdate: (s: TaskState) => void
): () => void {
  const url = `${BACKEND}/api/task-stream/${taskId}`;
  const es = new EventSource(url);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  es.onmessage = (e) => {
    try {
      onUpdate(JSON.parse(e.data) as TaskState);
    } catch {
      /* ignore keepalives */
    }
  };
  es.onerror = () => {
    // SSE dropped — fall back to polling every 4s.
    es.close();
    if (!pollTimer) {
      pollTimer = setInterval(async () => {
        try {
          const s = await getStatus(taskId);
          onUpdate(s);
          if (s.status === "done" || s.status === "error") {
            if (pollTimer) clearInterval(pollTimer);
          }
        } catch {
          /* keep trying */
        }
      }, 4000);
    }
  };

  return () => {
    es.close();
    if (pollTimer) clearInterval(pollTimer);
  };
}
