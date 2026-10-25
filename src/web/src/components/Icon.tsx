import type { CSSProperties } from "react";
import styles from "../App.module.css";

// A line icon of the Figma set; the mask paints it in the colour of the text around it.
export function Icon({
  name,
  size = 16,
  label,
  className = "",
}: {
  name: string;
  size?: number;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={`${styles.glyph} ${className}`}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-icon={name}
      style={
        {
          "--icon": `url(/icons/${name}.svg)`,
          width: size,
          height: size,
        } as CSSProperties
      }
    />
  );
}
