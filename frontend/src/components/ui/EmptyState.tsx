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
}

export function EmptyState({ title, description, icon = "documents", action }: EmptyStateProps) {
  let IconComponent;
  switch (icon) {
    case "briefcase":
      IconComponent = <AnimatedBriefcase className="w-16 h-16" />;
      break;
    case "organize":
      IconComponent = <AnimatedFolder className="w-16 h-16" />;
      break;
    case "checklists":
      IconComponent = <AnimatedChecklist className="w-16 h-16" />;
      break;
    case "documents":
    default:
      IconComponent = <AnimatedDocument className="w-16 h-16" />;
      break;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="flex flex-col items-center justify-center p-10 text-center max-w-sm mx-auto h-full min-h-[300px] glass-fallback rounded-3xl"
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
        className="w-24 h-24 mb-6 flex items-center justify-center relative"
      >
        <div className="absolute inset-0 bg-brand-100 rounded-full blur-xl opacity-50 mix-blend-multiply"></div>
        <div className="relative z-10">{IconComponent}</div>
      </motion.div>
      
      <h3 className="text-xl font-bold text-gray-800 mb-2 tracking-tight">{title}</h3>
      <p className="text-sm text-gray-500 mb-6 leading-relaxed balance-text">
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

