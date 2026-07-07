"use client";
import { useState } from "react";
import { useSession, signIn } from "next-auth/react";
import { Link2, Upload, Play, LogIn } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { startPipeline } from "@/lib/api";
import { ProgressPanel } from "@/components/ProgressPanel";

export function PipelineForm() {
  const { data: session, status } = useSession();
  const [driveUrl, setDriveUrl] = useState("");
  const [showTitle, setShowTitle] = useState("");
  const [maxEpisodes, setMaxEpisodes] = useState(0);
  const [hindiFile, setHindiFile] = useState<File | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accessToken = (session as any)?.accessToken as string | undefined;

  async function submit() {
    setError(null);
    if (!accessToken) { setError("Please sign in with Google first."); return; }
    if (!driveUrl) { setError("Provide the Google Drive folder link."); return; }
    if (!hindiFile) { setError("Upload the Hindi OG script."); return; }

    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("drive_url", driveUrl);
      fd.append("access_token", accessToken);
      fd.append("hindi_script", hindiFile);
      fd.append("show_title", showTitle);
      fd.append("max_episodes", String(maxEpisodes));
      const { task_id } = await startPipeline(fd);
      setTaskId(task_id);
    } catch (e: any) {
      setError(e.message || "Failed to start the pipeline.");
    } finally {
      setSubmitting(false);
    }
  }

  if (taskId) return <ProgressPanel taskId={taskId} mode="pipeline" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Full Adaptation Checker</CardTitle>
        <CardDescription>
          Drive folder of raw Chinese microdrama videos + your Hindi OG script → SRTs, director-ready
          screenplays, a formatted master PDF, and an adaptation-review report.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {status !== "authenticated" ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-6">
            <p className="text-sm text-muted-foreground">
              Google sign-in is required so the app can read your videos and write result folders back
              to your Drive.
            </p>
            <Button onClick={() => signIn("google")}>
              <LogIn className="h-4 w-4" /> Sign in with Google (Drive access)
            </Button>
          </div>
        ) : (
          <p className="text-sm text-emerald-700">
            ✓ Signed in as {session?.user?.email}. Drive access granted.
          </p>
        )}

        <div className="space-y-2">
          <Label htmlFor="drive">Google Drive folder link (raw videos)</Label>
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            <Input id="drive" placeholder="https://drive.google.com/drive/folders/…"
              value={driveUrl} onChange={(e) => setDriveUrl(e.target.value)} />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="title">Show title (optional)</Label>
            <Input id="title" placeholder="Defaults to the Drive folder name"
              value={showTitle} onChange={(e) => setShowTitle(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="max">Max episodes (0 = all)</Label>
            <Input id="max" type="number" min={0} value={maxEpisodes}
              onChange={(e) => setMaxEpisodes(Number(e.target.value))} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hindi">Hindi OG script (PDF / DOCX)</Label>
          <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed p-4 hover:bg-muted">
            <Upload className="h-5 w-5 text-muted-foreground" />
            <span className="text-sm">{hindiFile ? hindiFile.name : "Click to upload the Hindi script"}</span>
            <input id="hindi" type="file" accept=".pdf,.docx" className="hidden"
              onChange={(e) => setHindiFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>

        {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        <Button size="lg" onClick={submit} disabled={submitting || status !== "authenticated"}>
          <Play className="h-4 w-4" /> {submitting ? "Starting…" : "Start Full Pipeline"}
        </Button>
      </CardContent>
    </Card>
  );
}
