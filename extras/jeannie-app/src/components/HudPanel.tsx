"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface HudPanelProps {
  title: string;
  /** Secondary label, typically the Korean name. */
  subtitle?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Entrance stagger in seconds. */
  delay?: number;
}

/** Titled translucent HUD panel with corner brackets and a staggered entrance. */
export function HudPanel({
  title,
  subtitle,
  icon,
  actions,
  children,
  className,
  bodyClassName,
  delay = 0,
}: HudPanelProps) {
  return (
    <motion.section
      aria-label={title}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -2, transition: { duration: 0.2 } }}
      className={cn("hud-panel", className)}
    >
      <header className="flex min-h-[34px] items-center justify-between gap-2 border-b border-neon/20 px-3 py-1">
        <div className="flex min-w-0 items-center gap-2">
          {icon ? <span className="text-neon-hot [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span> : null}
          <h2 className="hud-title truncate">{title}</h2>
          {subtitle ? <span className="hud-label truncate normal-case tracking-[0.08em]">{subtitle}</span> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </header>
      <div className={cn("p-2.5", bodyClassName)}>{children}</div>
    </motion.section>
  );
}
