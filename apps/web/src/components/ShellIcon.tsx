export type IconName =
  | "activity"
  | "alert"
  | "bell"
  | "bridge"
  | "check"
  | "chevron"
  | "clock"
  | "compass"
  | "crosshair"
  | "drop"
  | "history"
  | "hospital"
  | "layers"
  | "map"
  | "minus"
  | "pause"
  | "people"
  | "play"
  | "plus"
  | "rain"
  | "report"
  | "reset"
  | "road"
  | "search"
  | "shelter"
  | "shield"
  | "waves"
  | "x";

interface ShellIconProps {
  name: IconName;
  size?: number;
  strokeWidth?: number;
}

export function ShellIcon({ name, size = 16, strokeWidth = 1.7 }: ShellIconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
  };

  const paths: Record<IconName, React.ReactNode> = {
    activity: <path d="M3 12h3.5l2.5-7 4 14 2.5-7H21" />,
    alert: <path d="M12 3 2.8 20h18.4L12 3Zm0 6v5m0 3.2v.1" />,
    bell: <path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7m-8 11h4" />,
    bridge: (
      <>
        <path d="M2 9h20M4 9v11M20 9v11" />
        <path d="M4 15c4.5 0 6-5 8-5s3.5 5 8 5" />
        <path d="M9.5 12.2V20m5-7.8V20" />
      </>
    ),
    check: <path d="m4.5 12.5 5 5 10-11" />,
    chevron: <path d="m9 5 7 7-7 7" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    compass: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" />
      </>
    ),
    crosshair: (
      <>
        <circle cx="12" cy="12" r="7.5" />
        <path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22" />
      </>
    ),
    drop: <path d="M12 3s6 6.4 6 10.4A6 6 0 0 1 6 13.4C6 9.4 12 3 12 3Z" />,
    history: (
      <>
        <path d="M3.5 8V3.5M3.5 8H8" />
        <path d="M3.9 8.4A9 9 0 1 1 3 12" />
        <path d="M12 7.5V12l3 2" />
      </>
    ),
    hospital: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M7 12h10" />
      </>
    ),
    layers: <path d="m12 3 9 5-9 5-9-5 9-5Zm-8 10 8 4 8-4m-16 5 8 4 8-4" />,
    map: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </>
    ),
    minus: <path d="M5 12h14" />,
    pause: <path d="M9 5v14M15 5v14" />,
    people: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 20c0-4 2-7 6-7s6 3 6 7m1-11a3 3 0 0 1 0 6m1 0c2.5.5 4 2.2 4 5" />
      </>
    ),
    play: <path d="m8 5 11 7-11 7V5Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    rain: (
      <>
        <path d="M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11-1A4.5 4.5 0 0 0 7 15Z" />
        <path d="m8 18-1 2m6-2-1 2m6-2-1 2" />
      </>
    ),
    report: (
      <>
        <path d="M6 3h9l4 4v14H6V3Z" />
        <path d="M14 3v5h5M9 13h6m-6 4h6" />
      </>
    ),
    reset: (
      <>
        <path d="M4 7v5h5" />
        <path d="M5.5 16a8 8 0 1 0 .8-9.5L4 9" />
      </>
    ),
    road: (
      <>
        <path d="m8 3-2 18m10-18 2 18M12 4v3m0 3v4m0 3v3" />
      </>
    ),
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    shelter: (
      <>
        <path d="m3 11 9-7 9 7" />
        <path d="M5 10v10h14V10m-9 10v-6h4v6" />
      </>
    ),
    shield: <path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Zm-3 9 2 2 4-5" />,
    waves: (
      <path d="M2 7c3-3 5 3 8 0s5 3 8 0 4 0 4 0M2 12c3-3 5 3 8 0s5 3 8 0 4 0 4 0M2 17c3-3 5 3 8 0s5 3 8 0 4 0 4 0" />
    ),
    x: <path d="m6 6 12 12M18 6 6 18" />,
  };

  return <svg {...common}>{paths[name]}</svg>;
}
