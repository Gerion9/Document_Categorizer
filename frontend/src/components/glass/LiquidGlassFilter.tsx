import React, { useEffect, useState } from "react";
import { generateDisplacementMap } from "../../lib/liquid-glass/displacementMap";
import { SurfaceProfile } from "../../lib/liquid-glass/surfaceFunctions";
import { supportsLiquidGlass } from "../../lib/liquid-glass/featureDetection";

export interface FilterDef {
  id: string;
  width: number;
  height: number;
  bezel: number;
  thickness: number;
  profile: SurfaceProfile;
  scale?: number;
}

// We will export a registry of filters we want to generate globally
export const liquidFilters: Record<string, FilterDef> = {
  "glass-header": { id: "glass-header", width: 1400, height: 80, bezel: 40, thickness: 15, profile: "convex-squircle" },
  "glass-card": { id: "glass-card", width: 400, height: 300, bezel: 20, thickness: 10, profile: "convex-squircle" },
  "glass-panel": { id: "glass-panel", width: 600, height: 800, bezel: 30, thickness: 15, profile: "convex-squircle" },
  "glass-thumbnail": { id: "glass-thumbnail", width: 150, height: 200, bezel: 10, thickness: 5, profile: "convex-squircle" },
  "glass-button": { id: "glass-button", width: 120, height: 40, bezel: 15, thickness: 8, profile: "convex-squircle" },
  "glass-tabs": { id: "glass-tabs", width: 400, height: 50, bezel: 15, thickness: 8, profile: "lip" },
};

export function LiquidGlassFilters() {
  const [maps, setMaps] = useState<Record<string, { dataUrl: string; maxDisplacement: number }>>({});
  const isSupported = supportsLiquidGlass();

  useEffect(() => {
    if (!isSupported) return;
    
    const newMaps: Record<string, { dataUrl: string; maxDisplacement: number }> = {};
    for (const key of Object.keys(liquidFilters)) {
      const def = liquidFilters[key];
      newMaps[def.id] = generateDisplacementMap(def.width, def.height, def.bezel, def.thickness, def.profile);
    }
    setMaps(newMaps);
  }, [isSupported]);

  if (!isSupported) return null;

  return (
    <svg style={{ position: "absolute", width: 0, height: 0, pointerEvents: "none" }} aria-hidden="true">
      <defs>
        {Object.values(liquidFilters).map((def) => {
          const mapData = maps[def.id];
          if (!mapData) return null;
          
          return (
            <filter id={def.id} key={def.id} colorInterpolationFilters="sRGB" x="-20%" y="-20%" width="140%" height="140%">
              <feImage
                href={mapData.dataUrl}
                x="0"
                y="0"
                width="100%"
                height="100%"
                result="displacement_map"
                preserveAspectRatio="none"
              />
              <feDisplacementMap
                in="SourceGraphic"
                in2="displacement_map"
                scale={def.scale ?? mapData.maxDisplacement}
                xChannelSelector="R"
                yChannelSelector="G"
                result="refraction"
              />
            </filter>
          );
        })}
      </defs>
    </svg>
  );
}

