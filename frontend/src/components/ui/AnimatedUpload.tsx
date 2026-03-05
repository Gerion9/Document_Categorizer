import { motion } from "framer-motion";

interface Props {
  className?: string;
  isDragging?: boolean;
}

export function AnimatedUpload({ className = "w-12 h-12", isDragging = false }: Props) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 100 100"
      className={className}
      initial="initial"
      animate={isDragging ? "dragging" : "animate"}
      whileHover="hover"
    >
      <defs>
        <linearGradient id="upload-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#60a5fa" /> {/* blue-400 */}
          <stop offset="100%" stopColor="#3b82f6" /> {/* blue-500 */}
        </linearGradient>
        <linearGradient id="cloud-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#bfdbfe" /> {/* blue-200 */}
          <stop offset="100%" stopColor="#eff6ff" /> {/* blue-50 */}
        </linearGradient>
      </defs>

      {/* Cloud Base */}
      <motion.path
        d="M 25 65 C 15 65, 10 55, 15 45 C 20 30, 40 25, 45 35 C 55 20, 75 25, 80 40 C 90 40, 95 55, 85 65 Z"
        fill="url(#cloud-gradient)"
        stroke="url(#upload-gradient)"
        strokeWidth="4"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -2, 0], scale: 1, transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } },
          dragging: { scale: 1.1, y: -4, transition: { type: "spring", stiffness: 300, damping: 15 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Arrow Stem */}
      <motion.line
        x1="50"
        y1="75"
        x2="50"
        y2="45"
        stroke="url(#upload-gradient)"
        strokeWidth="6"
        strokeLinecap="round"
        variants={{
          animate: { y1: 75, y2: 45, transition: { duration: 2, repeat: Infinity, ease: "easeInOut" } },
          hover: { y1: 70, y2: 40, transition: { duration: 0.3 } },
          dragging: { y1: 65, y2: 35, strokeDasharray: "10 5", transition: { duration: 0.5, repeat: Infinity, ease: "linear" } }
        }}
      />

      {/* Arrow Head */}
      <motion.path
        d="M 35 55 L 50 40 L 65 55"
        fill="none"
        stroke="url(#upload-gradient)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 2, repeat: Infinity, ease: "easeInOut" } },
          hover: { y: -5, transition: { duration: 0.3 } },
          dragging: { y: [-10, -15, -10], transition: { duration: 1, repeat: Infinity, ease: "easeInOut" } }
        }}
      />

      {/* Floating particles (files going up) */}
      <motion.rect
        x="35"
        y="85"
        width="6"
        height="8"
        rx="1"
        fill="#93c5fd"
        variants={{
          animate: { y: [0, -40], opacity: [0, 1, 0], scale: [0.5, 1, 0.5], transition: { duration: 2.5, repeat: Infinity, ease: "easeOut", delay: 0 } },
          dragging: { y: [0, -50], opacity: [0, 1, 0], scale: [0.8, 1.2, 0.8], transition: { duration: 1.5, repeat: Infinity, ease: "easeOut", delay: 0 } }
        }}
      />
      <motion.rect
        x="60"
        y="90"
        width="8"
        height="10"
        rx="2"
        fill="#bfdbfe"
        variants={{
          animate: { y: [0, -45], opacity: [0, 1, 0], scale: [0.5, 1, 0.5], transition: { duration: 3, repeat: Infinity, ease: "easeOut", delay: 1 } },
          dragging: { y: [0, -55], opacity: [0, 1, 0], scale: [0.8, 1.2, 0.8], transition: { duration: 1.8, repeat: Infinity, ease: "easeOut", delay: 0.5 } }
        }}
      />
    </motion.svg>
  );
}

