export type SurfaceProfile = "convex-circle" | "convex-squircle" | "concave" | "lip";

export function getSurfaceHeight(distanceFromSide: number, profile: SurfaceProfile): number {
  const x = Math.max(0, Math.min(1, distanceFromSide));
  
  switch (profile) {
    case "convex-circle":
      return 1 - Math.pow(1 - x, 2);
      
    case "convex-squircle":
      // Smooth flat to curve transition
      return 1 - Math.pow(1 - x, 4) / 4;
      
    case "concave":
      return Math.pow(1 - x, 2);
      
    case "lip": {
      const convex = 1 - Math.pow(1 - x, 2);
      const concave = Math.pow(1 - x, 2);
      const t = x * x * x * (x * (x * 6 - 15) + 10); // Smootherstep
      return convex * (1 - t) + concave * t;
    }
      
    default:
      return 1 - Math.pow(1 - x, 2);
  }
}

export function getSurfaceNormal(distanceFromSide: number, profile: SurfaceProfile) {
  const delta = 0.001;
  const y1 = getSurfaceHeight(distanceFromSide - delta, profile);
  const y2 = getSurfaceHeight(distanceFromSide + delta, profile);
  const derivative = (y2 - y1) / (2 * delta);
  // normal rotated by -90 deg
  return { x: -derivative, y: 1 };
}

