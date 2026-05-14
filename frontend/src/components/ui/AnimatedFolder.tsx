import { motion } from "framer-motion";

interface Props {
  className?: string;
}

export function AnimatedFolder({ className = "w-10 h-10" }: Props) {
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
        <linearGradient id="folder-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f59e0b" /> {/* amber-500 */}
          <stop offset="100%" stopColor="#fbbf24" /> {/* amber-400 */}
        </linearGradient>
      </defs>

      {/* Back flap */}
      <motion.path
        d="M 15 25 L 35 25 L 45 35 L 85 35 L 85 75 L 15 75 Z"
        fill="none"
        stroke="#fbbf24"
        strokeWidth="4"
        strokeLinejoin="round"
        variants={{
          animate: { y: [0, -2, 0], transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } },
        }}
      />

      {/* Documents inside */}
      <motion.path
        d="M 25 35 L 75 35 L 75 45 L 25 45 Z"
        fill="#e5e7eb"
        stroke="#9ca3af"
        strokeWidth="2"
        variants={{
          animate: { y: [0, -6, 0], transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } },
          hover: { y: -10, transition: { duration: 0.3 } }
        }}
      />
      <motion.path
        d="M 30 30 L 70 30 L 70 40 L 30 40 Z"
        fill="#f3f4f6"
        stroke="#9ca3af"
        strokeWidth="2"
        variants={{
          animate: { y: [0, -4, 0], transition: { duration: 3, repeat: Infinity, ease: "easeInOut", delay: 0.2 } },
          hover: { y: -15, transition: { duration: 0.3 } }
        }}
      />

      {/* Front flap */}
      <motion.path
        d="M 15 45 L 85 45 L 80 80 L 20 80 Z"
        fill="white"
        stroke="url(#folder-gradient)"
        strokeWidth="6"
        strokeLinejoin="round"
        variants={{
          animate: { 
            y: [0, -2, 0], 
            rotateX: [0, 5, 0],
            transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } 
          },
          hover: { rotateX: 15, y: 2, scale: 1.05, transition: { duration: 0.3 } }
        }}
        style={{ originY: "80px", transformPerspective: 500 }}
      />
    </motion.svg>
  );
}

