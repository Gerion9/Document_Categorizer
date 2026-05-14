import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedPDF({ className = "w-10 h-10" }: Props) {
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
        <linearGradient id="pdf-red" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#ef4444" /> {/* red-500 */}
          <stop offset="100%" stopColor="#dc2626" /> {/* red-600 */}
        </linearGradient>
      </defs>

      {/* Main Document Body */}
      <motion.path
        d="M 25 15 L 55 15 L 75 35 L 75 85 L 25 85 Z"
        fill="white"
        stroke="url(#pdf-red)"
        strokeWidth="5"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* Folded Corner */}
      <motion.path
        d="M 55 15 L 55 35 L 75 35"
        fill="url(#pdf-red)"
        stroke="url(#pdf-red)"
        strokeWidth="2"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.05, y: -2, transition: { duration: 0.3 } }
        }}
        style={{ originX: "50%", originY: "50%" }}
      />

      {/* PDF Badge */}
      <motion.rect
        x="15"
        y="45"
        width="45"
        height="22"
        rx="4"
        fill="url(#pdf-red)"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.1, x: 2, y: -2, transition: { type: "spring", stiffness: 300, damping: 15 } }
        }}
      />
      <motion.text
        x="37"
        y="60"
        fill="white"
        fontSize="12"
        fontWeight="bold"
        fontFamily="sans-serif"
        textAnchor="middle"
        variants={{
          animate: { y: [0, -3, 0], transition: { duration: 4, repeat: Infinity, ease: "easeInOut" } },
          hover: { scale: 1.1, x: 2, y: -2, transition: { type: "spring", stiffness: 300, damping: 15 } }
        }}
      >
        PDF
      </motion.text>

      {/* Lines below badge */}
      <motion.line
        x1="35"
        y1="75"
        x2="65"
        y2="75"
        stroke="#d1d5db"
        strokeWidth="3"
        strokeLinecap="round"
        variants={{
          animate: { x2: [65, 55, 65], y: [0, -3, 0], transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } },
        }}
      />
    </motion.svg>
  );
}

