"use client";
import { useState } from "react";
import { Upload, Play } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { startFormat } from "@/lib/api";
import { ProgressPanel } from "@/components/ProgressPanel";

export function FormatForm() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    if (!file) { setError("Upload a script (PDF, DOCX or TXT)."); return; }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("show_title", title);
      const { task_id } = await startFormat(fd);
      setTaskId(task_id);
    } catch (e: any) {
      setError(e.message || "Failed to start formatting.");
    } finally {
      setSubmitting(false);
    }
  }

  if (taskId) return <ProgressPanel taskId={taskId} mode="format" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Formatting Only</CardTitle>
        <CardDescription>
          Upload an unformatted script — the Formatter applies industry-standard screenplay formatting
          (Beta Bana Billionaire rules) and returns a clean PDF.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="ftitle">Title (optional)</Label>
          <Input id="ftitle" placeholder="Defaults to the file name"
            value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="script">Script file (PDF / DOCX / TXT)</Label>
          <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed p-4 hover:bg-muted">
            <Upload className="h-5 w-5 text-muted-foreground" />
            <span className="text-sm">{file ? file.name : "Click to upload your script"}</span>
            <input id="script" type="file" accept=".pdf,.docx,.txt" className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>

        {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        <Button size="lg" onClick={submit} disabled={submitting}>
          <Play className="h-4 w-4" /> {submitting ? "Formatting…" : "Format Script"}
        </Button>
      </CardContent>
    </Card>
  );
}
