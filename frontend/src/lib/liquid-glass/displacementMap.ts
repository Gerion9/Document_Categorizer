import { calculateDisplacement } from "./refraction";
import { SurfaceProfile } from "./surfaceFunctions";

export function generateDisplacementMap(
  width: number,
  height: number,
  bezel: number,
  thickness: number,
  profile: SurfaceProfile
): { dataUrl: string, maxDisplacement: number } {
  // We use a small canvas for performance (e.g. 128x128)
  // Displacement maps are smooth so they interpolate well when scaled up
  const size = 128; 
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return { dataUrl: "", maxDisplacement: 0 };
  
  const imgData = ctx.createImageData(size, size);
  const data = imgData.data;
  
  const resolution = 256;
  const displacementCurve = new Float32Array(resolution);
  let maxDisplacement = 0;
  
  for (let i = 0; i < resolution; i++) {
    // Distance from 0 to 1 (0 = edge, 1 = inner bezel)
    const d = calculateDisplacement(i / (resolution - 1), profile, 1.5, thickness);
    displacementCurve[i] = d;
    if (Math.abs(d) > maxDisplacement) maxDisplacement = Math.abs(d);
  }
  
  if (maxDisplacement === 0) maxDisplacement = 1;
  
  const cx = size / 2;
  const cy = size / 2;
  
  // Use width/height to determine aspect ratio scaling for the displacement map
  const ratioX = width > height ? 1 : width / height;
  const ratioY = height > width ? 1 : height / width;
  
  const radiusX = (size / 2) * ratioX;
  const radiusY = (size / 2) * ratioY;
  
  const innerRadiusX = Math.max(0, radiusX - (bezel / Math.max(width, height)) * size);
  const innerRadiusY = Math.max(0, radiusY - (bezel / Math.max(width, height)) * size);
  
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - cx) / ratioX;
      const dy = (y - cy) / ratioY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      
      const maxRadius = size / 2;
      const innerRadius = Math.max(0, maxRadius - (bezel / Math.max(width, height)) * size);
      
      let dispMag = 0;
      if (dist >= innerRadius && dist <= maxRadius) {
        // Map to 0..1 (where 0 is the outer edge, 1 is the inner bezel)
        const normalizedDist = 1 - (dist - innerRadius) / (maxRadius - innerRadius);
        const idx = Math.min(resolution - 1, Math.max(0, Math.floor(normalizedDist * resolution)));
        dispMag = displacementCurve[idx];
      }
      
      const angle = Math.atan2(dy, dx);
      const normDisp = dispMag / maxDisplacement;
      
      const vx = Math.cos(angle) * normDisp;
      const vy = Math.sin(angle) * normDisp;
      
      const idx = (y * size + x) * 4;
      data[idx] = Math.max(0, Math.min(255, 128 + vx * 127));     // R
      data[idx + 1] = Math.max(0, Math.min(255, 128 + vy * 127)); // G
      data[idx + 2] = 128;                                        // B
      data[idx + 3] = 255;                                        // A
    }
  }
  
  ctx.putImageData(imgData, 0, 0);
  return {
    dataUrl: canvas.toDataURL("image/png"),
    maxDisplacement
  };
}

