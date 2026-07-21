import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "outline";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const styles = {
    default: "border-transparent bg-primary text-primary-foreground",
    secondary: "border-transparent bg-secondary text-secondary-foreground",
    outline: "text-foreground",
  }[variant];
  return (
    <div className={cn(
      "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors",
      styles, className)} {...props} />
  );
}
