"use client";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2, Loader2, XCircle, Download, FolderOpen, FileText,
  Film, ScrollText, Sparkles,
} from "lucide-react";
import { streamStatus, TaskState, BACKEND } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const PIPELINE_STEPS = [
  { n: 1, label: "SRT Extraction", icon: Film },
  { n: 2, label: "Screenplay Generation", icon: ScrollText },
  { n: 3, label: "Merge & Stitch", icon: FileText },
  { n: 4, label: "Formatting", icon: FileText },
  { n: 5, label: "Adaptation Evaluation", icon: Sparkles },
];

// Which download buttons to reveal, keyed by artifact name from the backend.
const ARTIFACTS: { key: string; label: string; icon: any }[] = [
  { key: "srts_zip", label: "Download SRTs (ZIP)", icon: Download },
  { key: "screenplays_zip", label: "Download Individual Screenplays (ZIP)", icon: Download },
  { key: "final_zip", label: "Download Master + Evaluation (ZIP)", icon: Download },
  { key: "format_pdf", label: "Download Formatted Script (ZIP)", icon: Download },
];

export function ProgressPanel({ taskId, mode }: { taskId: string; mode: "pipeline" | "format" }) {
  const [state, setState] = useState<TaskState | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stop = streamStatus(taskId, setState);
    return stop;
  }, [taskId]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [state?.log?.length]);

  if (!state) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> Connecting to the pipeline…
        </CardContent>
      </Card>
    );
  }

  const done = state.status === "done";
  const errored = state.status === "error";

  return (
    <div className="space-y-6">
      {/* Header + progress bar */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              {done ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-600" />
              ) : errored ? (
                <XCircle className="h-6 w-6 text-red-600" />
              ) : (
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              )}
              {state.show_title || "Processing"}
            </CardTitle>
            <Badge variant={done ? "success" : errored ? "error" : "default"}>
              {state.status.toUpperCase()}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <Progress value={state.percent} />
          <p className="text-sm text-muted-foreground">{state.step_label}</p>
          {errored && state.error && (
            <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{state.error}</p>
          )}
        </CardContent>
      </Card>

      {/* Step tracker (pipeline mode only) */}
      {mode === "pipeline" && (
        <Card>
          <CardContent className="grid grid-cols-2 gap-3 py-6 sm:grid-cols-5">
            {PIPELINE_STEPS.map((s) => {
              const active = state.step === s.n && !done;
              const complete = state.step > s.n || done;
              const Icon = s.icon;
              return (
                <div
                  key={s.n}
                  className={`flex flex-col items-center gap-2 rounded-lg border p-3 text-center transition-colors ${
                    complete ? "border-emerald-200 bg-emerald-50" : active ? "border-primary bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="relative">
                    <Icon className={`h-6 w-6 ${complete ? "text-emerald-600" : active ? "text-primary" : "text-muted-foreground"}`} />
                    {active && <Loader2 className="absolute -right-2 -top-2 h-3 w-3 animate-spin text-primary" />}
                    {complete && <CheckCircle2 className="absolute -right-2 -top-2 h-3.5 w-3.5 text-emerald-600" />}
                  </div>
                  <span className="text-xs font-medium">{s.label}</span>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Dynamic download links — appear as artifacts become ready */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Deliverables</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <AnimatePresence>
              {ARTIFACTS.filter((a) => state.artifacts[a.key]).map((a) => (
                <motion.a
                  key={a.key}
                  initial={{ opacity: 0, y: 8, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  href={state.artifacts[a.key]}
                >
                  <Button variant="default">
                    <a.icon className="h-4 w-4" /> {a.label}
                  </Button>
                </motion.a>
              ))}
            </AnimatePresence>
            {Object.keys(state.artifacts).length === 0 && (
              <p className="text-sm text-muted-foreground">
                Downloads will appear here as each stage completes…
              </p>
            )}
          </div>

          {/* Google Drive folder links */}
          {Object.keys(state.drive || {}).length > 0 && (
            <div className="flex flex-wrap gap-3 border-t pt-3">
              {state.drive.srt_folder && (
                <a href={state.drive.srt_folder} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm">
                    <FolderOpen className="h-4 w-4" /> SRTs on Drive
                  </Button>
                </a>
              )}
              {state.drive.screenplay_folder && (
                <a href={state.drive.screenplay_folder} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm">
                    <FolderOpen className="h-4 w-4" /> Screenplays on Drive
                  </Button>
                </a>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Live log */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Live log</CardTitle>
        </CardHeader>
        <CardContent>
          <div
            ref={logRef}
            className="max-h-72 overflow-y-auto rounded-md bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-200"
          >
            {(state.log || []).map((l, i) => (
              <div key={i} className={l.level === "error" ? "text-red-400" : "text-slate-300"}>
                <span className="text-slate-500">{new Date(l.ts * 1000).toLocaleTimeString()} </span>
                {l.msg}
              </div>
            ))}
            {(state.log || []).length === 0 && <span className="text-slate-500">Waiting for output…</span>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
