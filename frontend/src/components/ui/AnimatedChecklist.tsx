import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedChecklist({ className = "w-10 h-10" }: Props) {
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
        <linearGradient id="check-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#10b981" /> {/* emerald-500 */}
          <stop offset="100%" stopColor="#34d399" /> {/* emerald-400 */}
        </linearGradient>
      </defs>

      {/* Clipboard board */}
      <motion.rect
        x="20"
        y="25"
        width="60"
        height="65"
        rx="4"
        fill="none"
        stroke="#9ca3af"
        strokeWidth="5"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, transition: { duration: 0.3 } }
        }}
      />
      
      {/* Clip */}
      <motion.path
        d="M 35 15 L 65 15 L 65 30 L 35 30 Z"
        fill="none"
        stroke="#6b7280"
        strokeWidth="5"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, transition: { duration: 0.3 } }
        }}
      />
      <motion.circle
        cx="50"
        cy="22"
        r="3"
        fill="#6b7280"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, transition: { duration: 0.3 } }
        }}
      />

      {/* Item 1 */}
      <motion.circle cx="35" cy="45" r="4" fill="#d1d5db" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />
      <motion.line x1="45" y1="45" x2="70" y2="45" stroke="#d1d5db" strokeWidth="4" strokeLinecap="round" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />

      {/* Item 2 with checkmark */}
      <motion.circle cx="35" cy="60" r="4" fill="url(#check-gradient)" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />
      <motion.path
        d="M 32 60 L 34 62 L 39 57"
        fill="none"
        stroke="white"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        variants={{
          initial: { pathLength: 0 },
          animate: { 
            pathLength: [0, 1, 1],
            y: [0, -3, 0],
            transition: { duration: 4, times: [0, 0.2, 1], repeat: Infinity, ease: "easeInOut" }
          }
        }}
      />
      <motion.line x1="45" y1="60" x2="65" y2="60" stroke="#d1d5db" strokeWidth="4" strokeLinecap="round" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />

      {/* Item 3 */}
      <motion.circle cx="35" cy="75" r="4" fill="#d1d5db" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />
      <motion.line x1="45" y1="75" x2="75" y2="75" stroke="#d1d5db" strokeWidth="4" strokeLinecap="round" variants={{ animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />

    </motion.svg>
  );
}

