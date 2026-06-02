import React from "react";
import { motion } from "framer-motion";
import { AnimatedDocument } from "./AnimatedDocument";
import { AnimatedFolder } from "./AnimatedFolder";
import { AnimatedChecklist } from "./AnimatedChecklist";
import { AnimatedBriefcase } from "./AnimatedBriefcase";

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: "documents" | "organize" | "checklists" | "briefcase";
  action?: React.ReactNode;
  compact?: boolean;
}

export function EmptyState({
  title,
  description,
  icon = "documents",
  action,
  compact = false,
}: EmptyStateProps) {
  const iconClassName = compact ? "w-10 h-10" : "w-16 h-16";
  let IconComponent;
  switch (icon) {
    case "briefcase":
      IconComponent = <AnimatedBriefcase className={iconClassName} />;
      break;
    case "organize":
      IconComponent = <AnimatedFolder className={iconClassName} />;
      break;
    case "checklists":
      IconComponent = <AnimatedChecklist className={iconClassName} />;
      break;
    case "documents":
    default:
      IconComponent = <AnimatedDocument className={iconClassName} />;
      break;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className={`solid-panel mx-auto flex w-full flex-col items-center justify-center text-center ${
        compact
          ? "min-h-[180px] rounded-2xl p-6"
          : "h-full min-h-[300px] max-w-sm rounded-3xl p-10"
      }`}
    >
      <motion.div
        initial={{ scale: 0.8 }}
        animate={{ scale: 1 }}
        transition={{
          delay: 0.1,
          type: "spring",
          stiffness: 200,
          damping: 15,
        }}
        className={`relative flex items-center justify-center ${
          compact ? "mb-3 h-14 w-14" : "mb-6 h-24 w-24"
        }`}
      >
        <div className="absolute inset-0 bg-brand-100 rounded-full blur-xl opacity-50 mix-blend-multiply"></div>
        <div className="relative z-10">{IconComponent}</div>
      </motion.div>
      
      <h3
        className={`mb-2 font-bold tracking-tight text-brand-800 ${
          compact ? "text-base" : "text-xl"
        }`}
      >
        {title}
      </h3>
      <p
        className={`leading-relaxed text-brand-500 text-balance ${
          compact ? "mb-0 text-xs" : "mb-6 text-sm"
        }`}
      >
        {description}
      </p>

      {action && (
        <motion.div
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {action}
        </motion.div>
      )}
    </motion.div>
  );
}

