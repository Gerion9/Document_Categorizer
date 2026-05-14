import { getSurfaceNormal, SurfaceProfile } from "./surfaceFunctions";

export function calculateDisplacement(
  distanceFromSide: number, // 0 to 1
  profile: SurfaceProfile,
  refractiveIndex: number = 1.5, // glass
  thickness: number = 20, // max pixel thickness
): number {
  // Ambient n1 = 1 (air), Glass n2 = 1.5
  const n1 = 1;
  const n2 = refractiveIndex;
  
  const normal = getSurfaceNormal(distanceFromSide, profile);
  
  // Normalize normal vector
  const normalLen = Math.sqrt(normal.x * normal.x + normal.y * normal.y);
  const nx = normal.x / normalLen;
  const ny = normal.y / normalLen;
  
  // Incident ray is orthogonal to the background (0, -1) coming from top to bottom
  const ix = 0;
  const iy = -1;
  
  // Dot product
  const cosi = -(ix * nx + iy * ny);
  
  // Snell's Law
  const eta = n1 / n2;
  const k = 1 - eta * eta * (1 - cosi * cosi);
  
  if (k < 0) {
    // Total internal reflection (fallback to 0 displacement)
    return 0;
  }
  
  const rx = eta * ix + (eta * cosi - Math.sqrt(k)) * nx;
  const ry = eta * iy + (eta * cosi - Math.sqrt(k)) * ny;
  
  // We need to know how far the ray hits the bottom plane
  // The glass has 'thickness' depth. 
  const h = thickness; // simplified assumption to avoid too steep angles
  
  // Ray starts at (distanceFromSide, h). It goes in direction (rx, ry).
  if (Math.abs(ry) < 0.0001) return 0;
  
  const displacement = (rx / Math.abs(ry)) * h;
  return displacement;
}

