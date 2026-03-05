import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedAIBot({ className = "w-6 h-6" }: Props) {
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
        <linearGradient id="ai-glow" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#a855f7" /> {/* purple-500 */}
          <stop offset="100%" stopColor="#3b82f6" /> {/* blue-500 */}
        </linearGradient>
        <filter id="glow-blur" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Outer Tech Ring */}
      <motion.circle
        cx="50"
        cy="50"
        r="44"
        fill="none"
        stroke="url(#ai-glow)"
        strokeWidth="2.5"
        strokeDasharray="30 15 10 15"
        strokeLinecap="round"
        variants={{
          animate: { rotate: 360, transition: { duration: 12, repeat: Infinity, ease: "linear" } },
          hover: { rotate: 360, scale: 1.05, strokeWidth: 3, filter: "url(#glow-blur)", transition: { duration: 4, repeat: Infinity, ease: "linear" } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Hexagon Bot Head */}
      <motion.path
        d="M 50 22 L 72 35 L 72 65 L 50 78 L 28 65 L 28 35 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinejoin="round"
        variants={{
          animate: { opacity: 0.9 },
          hover: { scale: 1.05, stroke: "url(#ai-glow)", filter: "url(#glow-blur)" }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Bot Eyes */}
      <motion.rect
        x="36"
        y="45"
        width="8"
        height="10"
        rx="2"
        fill="currentColor"
        variants={{
          animate: { 
            scaleY: [1, 0.1, 1], 
            transition: { duration: 3.5, times: [0, 0.05, 0.1], repeat: Infinity, repeatDelay: 2 } 
          },
          hover: { fill: "#60a5fa" }
        }}
        style={{ originX: "40px", originY: "50px" }}
      />
      <motion.rect
        x="56"
        y="45"
        width="8"
        height="10"
        rx="2"
        fill="currentColor"
        variants={{
          animate: { 
            scaleY: [1, 0.1, 1], 
            transition: { duration: 3.5, times: [0, 0.05, 0.1], repeat: Infinity, repeatDelay: 2 } 
          },
          hover: { fill: "#60a5fa" }
        }}
        style={{ originX: "60px", originY: "50px" }}
      />

      {/* Brain Waves / Data lines emitting from top */}
      <motion.path
        d="M 50 22 L 50 6 M 38 27 L 26 12 M 62 27 L 74 12"
        stroke="url(#ai-glow)"
        strokeWidth="3"
        strokeLinecap="round"
        variants={{
          animate: { 
            opacity: [0.1, 1, 0.1],
            pathLength: [0, 1, 0.5],
            transition: { duration: 2, repeat: Infinity, ease: "easeInOut" } 
          }
        }}
      />
    </motion.svg>
  );
}