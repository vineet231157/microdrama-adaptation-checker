"use client";
import { useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { motion } from "framer-motion";
import { Clapperboard, FileCheck2, Wand2, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PipelineForm } from "@/components/PipelineForm";
import { FormatForm } from "@/components/FormatForm";

type Mode = "pipeline" | "format" | null;

export default function Home() {
  const { data: session } = useSession();
  const [mode, setMode] = useState<Mode>(null);

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Clapperboard className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Microdrama Adaptation Checker</h1>
            <p className="text-sm text-muted-foreground">
              Chinese microdrama → Hindi director-ready screenplay, end to end.
            </p>
          </div>
        </div>
        {session && (
          <Button variant="ghost" size="sm" onClick={() => signOut()}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        )}
      </div>

      {/* Mode selection */}
      {mode === null ? (
        <div className="grid gap-6 sm:grid-cols-2">
          <ModeCard
            icon={<Wand2 className="h-7 w-7" />}
            title="Formatting Only"
            desc="Upload an unformatted script and get a cleanly formatted, industry-standard screenplay PDF."
            cta="Format a script"
            onClick={() => setMode("format")}
          />
          <ModeCard
            icon={<FileCheck2 className="h-7 w-7" />}
            title="Full Adaptation Checker"
            desc="Drive folder of videos + Hindi script → SRTs, screenplays, master PDF and a full adaptation report."
            cta="Run the full pipeline"
            highlight
            onClick={() => setMode("pipeline")}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <Button variant="ghost" size="sm" onClick={() => setMode(null)}>
            ← Back to modes
          </Button>
          {mode === "pipeline" ? <PipelineForm /> : <FormatForm />}
        </div>
      )}
    </main>
  );
}

function ModeCard({
  icon, title, desc, cta, onClick, highlight,
}: {
  icon: React.ReactNode; title: string; desc: string; cta: string;
  onClick: () => void; highlight?: boolean;
}) {
  return (
    <motion.button
      whileHover={{ y: -4 }}
      onClick={onClick}
      className={`flex flex-col items-start gap-4 rounded-xl border p-6 text-left shadow-sm transition-colors ${
        highlight ? "border-primary/40 bg-primary/5" : "bg-card hover:bg-muted"
      }`}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {icon}
      </div>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
      </div>
      <span className="mt-2 text-sm font-medium text-primary">{cta} →</span>
    </motion.button>
  );
}
