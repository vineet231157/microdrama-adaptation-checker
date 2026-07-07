import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: "default" | "success" | "error" | "muted" }) {
  const styles = {
    default: "bg-primary/10 text-primary",
    success: "bg-emerald-100 text-emerald-700",
    error: "bg-red-100 text-red-700",
    muted: "bg-muted text-muted-foreground",
  }[variant];
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", styles, className)}
      {...props}
    />
  );
}
