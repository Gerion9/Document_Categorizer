interface NovaMarkProps {
  className?: string;
  variant?: "gold" | "white";
}

export const APP_LOGO_SRC = "/LOGOTIPO_MANUEL_SOLIS_02.png";

export function NovaMark({ className = "h-7 w-7" }: NovaMarkProps) {
  return (
    <img
      src={APP_LOGO_SRC}
      alt=""
      aria-hidden="true"
      className={`object-contain ${className}`}
    />
  );
}
