import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedDocument({ className = "w-10 h-10" }: Props) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 100 100"
      className={className}
      initial="initial"
      animate="animate"
      whileHover="hover"
    >
      <defs>
        <linearGradient id="doc-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#3b82f6" /> {/* blue-500 */}
          <stop offset="100%" stopColor="#60a5fa" /> {/* blue-400 */}
        </linearGradient>
      </defs>

      {/* Main Document Body */}
      <motion.path
        d="M 25 15 L 55 15 L 75 35 L 75 85 L 25 85 Z"
        fill="none"
        stroke="url(#doc-gradient)"
        strokeWidth="6"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, strokeWidth: 7, transition: { duration: 0.3 } }
        }}
      />

      {/* Folded Corner */}
      <motion.path
        d="M 55 15 L 55 35 L 75 35"
        fill="none"
        stroke="url(#doc-gradient)"
        strokeWidth="6"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, transition: { duration: 0.3 } }
        }}
      />

      {/* Text Lines */}
      <motion.line
        x1="35"
        y1="45"
        x2="65"
        y2="45"
        stroke="#9ca3af"
        strokeWidth="4"
        strokeLinecap="round"
        variants={{
          animate: { x2: [65, 55, 65], y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
        }}
      />
      <motion.line
        x1="35"
        y1="57"
        x2="55"
        y2="57"
        stroke="#9ca3af"
        strokeWidth="4"
        strokeLinecap="round"
        variants={{
          animate: { x2: [55, 65, 55], y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut", delay: 1 } },
        }}
      />
      <motion.line
        x1="35"
        y1="69"
        x2="60"
        y2="69"
        stroke="#9ca3af"
        strokeWidth="4"
        strokeLinecap="round"
        variants={{
          animate: { x2: [60, 50, 60], y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut", delay: 2 } },
        }}
      />
    </motion.svg>
  );
}

