import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedBriefcase({ className = "w-10 h-10" }: Props) {
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
        <linearGradient id="briefcase-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#4f46e5" /> {/* indigo-600 */}
          <stop offset="100%" stopColor="#818cf8" /> {/* blue-400 */}
        </linearGradient>
      </defs>

      {/* Briefcase Handle */}
      <motion.path
        d="M 40 30 L 40 20 C 40 15, 60 15, 60 20 L 60 30"
        fill="none"
        stroke="#9ca3af"
        strokeWidth="6"
        strokeLinecap="round"
        variants={{
          animate: { y: [0, -2, 0], transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } },
          hover: { y: -5, transition: { duration: 0.3 } }
        }}
      />

      {/* Main Body */}
      <motion.rect
        x="15"
        y="30"
        width="70"
        height="50"
        rx="6"
        fill="white"
        stroke="url(#briefcase-gradient)"
        strokeWidth="6"
        variants={{
          animate: { y: [0, -3, 0], rotate: [0, 1, -1, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
      />

      {/* Center lock */}
      <motion.rect
        x="45"
        y="45"
        width="10"
        height="12"
        rx="2"
        fill="url(#briefcase-gradient)"
        variants={{
          animate: { y: [0, -3, 0], rotate: [0, 1, -1, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
      />

      {/* Horizontal line */}
      <motion.line
        x1="15"
        y1="40"
        x2="85"
        y2="40"
        stroke="url(#briefcase-gradient)"
        strokeWidth="3"
        variants={{
          animate: { y: [0, -3, 0], rotate: [0, 1, -1, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
      />
      
      {/* Sparkles around the briefcase */}
      <motion.circle
        cx="20"
        cy="20"
        r="2"
        fill="#818cf8"
        variants={{
          animate: { scale: [0, 1.5, 0], opacity: [0, 1, 0], transition: { duration: 2, repeat: Infinity, ease: "easeInOut", delay: 0.5 } }
        }}
      />
      <motion.circle
        cx="80"
        cy="15"
        r="3"
        fill="#818cf8"
        variants={{
          animate: { scale: [0, 1.5, 0], opacity: [0, 1, 0], transition: { duration: 2.5, repeat: Infinity, ease: "easeInOut", delay: 1 } }
        }}
      />
    </motion.svg>
  );
}

