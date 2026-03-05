import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedReport({ className = "w-10 h-10" }: Props) {
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
        <linearGradient id="report-green" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#10b981" /> {/* emerald-500 */}
          <stop offset="100%" stopColor="#059669" /> {/* emerald-600 */}
        </linearGradient>
        <linearGradient id="report-purple" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#a855f7" /> {/* purple-500 */}
          <stop offset="100%" stopColor="#7c3aed" /> {/* purple-600 */}
        </linearGradient>
      </defs>

      {/* Main Document Body */}
      <motion.rect
        x="20"
        y="15"
        width="60"
        height="75"
        rx="6"
        fill="white"
        stroke="#e5e7eb"
        strokeWidth="4"
        variants={{
          animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, borderColor: "#a855f7", transition: { duration: 0.3 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Top Banner */}
      <motion.rect
        x="20"
        y="15"
        width="60"
        height="18"
        rx="6"
        fill="url(#report-purple)"
        variants={{
          animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />
      {/* Flatten bottom of the banner */}
      <motion.rect
        x="20"
        y="25"
        width="60"
        height="8"
        fill="url(#report-purple)"
        variants={{
          animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Checkmarks and lines */}
      <motion.path
        d="M 30 45 L 35 50 L 45 40"
        fill="none"
        stroke="url(#report-green)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        variants={{
          initial: { pathLength: 0 },
          animate: { 
            pathLength: [0, 1, 1],
            y: [0, -2, 0],
            transition: { duration: 4, times: [0, 0.2, 1], repeat: Infinity, ease: "easeInOut" }
          },
          hover: { scale: 1.1, y: -2 }
        }}
      />
      <motion.line x1="55" y1="45" x2="70" y2="45" stroke="#d1d5db" strokeWidth="4" strokeLinecap="round" variants={{ animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />

      <motion.path
        d="M 30 65 L 35 70 L 45 60"
        fill="none"
        stroke="url(#report-green)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        variants={{
          initial: { pathLength: 0 },
          animate: { 
            pathLength: [0, 1, 1],
            y: [0, -2, 0],
            transition: { duration: 4, times: [0, 0.2, 1], repeat: Infinity, ease: "easeInOut", delay: 1 }
          },
          hover: { scale: 1.1, y: -2 }
        }}
      />
      <motion.line x1="55" y1="65" x2="70" y2="65" stroke="#d1d5db" strokeWidth="4" strokeLinecap="round" variants={{ animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />

      {/* AI Bot eye / stamp */}
      <motion.circle
        cx="70"
        cy="80"
        r="8"
        fill="url(#report-purple)"
        variants={{
          animate: { 
            scale: [1, 1.2, 1],
            y: [0, -2, 0],
            transition: { duration: 2, repeat: Infinity, ease: "easeInOut" }
          },
          hover: { scale: 1.3, y: -2 }
        }}
      />
      <motion.circle cx="70" cy="80" r="3" fill="white" variants={{ animate: { y: [0, -2, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } } }} />
    </motion.svg>
  );
}

