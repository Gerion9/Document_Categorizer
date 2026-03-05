let isChromium: boolean | null = null;

export function supportsLiquidGlass(): boolean {
  if (isChromium !== null) return isChromium;
  if (typeof window === "undefined") return false;
  
  // Note: backdrop-filter using SVG filters is currently a Chromium-only feature
  // We can do a rudimentary user agent check
  const isChrome = /Chrome/.test(navigator.userAgent) && /Google Inc/.test(navigator.vendor);
  const isSafari = /Safari/.test(navigator.userAgent) && /Apple Computer/.test(navigator.vendor);
  
  isChromium = isChrome && !isSafari;
  return isChromium;
}

