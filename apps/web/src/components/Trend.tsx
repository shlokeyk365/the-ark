export type Tone = "cyan" | "red" | "green" | "amber";

interface SparklineProps {
  values: number[];
  activeIndex: number;
  tone: Tone;
  label: string;
}

/**
 * A four-point series across the scenario's flood frames. Every point is a
 * real derived value; no interpolation or smoothing is applied.
 */
export function Sparkline({ values, activeIndex, tone, label }: SparklineProps) {
  const width = 54;
  const height = 24;
  const inset = 3;

  if (values.length < 2) {
    return <span className="sparkline-empty" aria-hidden="true" />;
  }

  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const span = highest - lowest || 1;
  const step = (width - inset * 2) / (values.length - 1);

  const points = values.map((value, index) => ({
    x: inset + index * step,
    // A flat series sits on the mid-line rather than pinned to the floor.
    y:
      highest === lowest
        ? height / 2
        : height - inset - ((value - lowest) / span) * (height - inset * 2),
  }));

  const line = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${line} ${points[points.length - 1].x.toFixed(1)},${height} ${inset},${height}`;
  const active = points[Math.max(0, Math.min(activeIndex, points.length - 1))];

  return (
    <svg
      className={`sparkline tone-${tone}`}
      height={height}
      role="img"
      aria-label={label}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
    >
      <polygon className="sparkline-area" points={area} />
      <polyline className="sparkline-line" points={line} />
      <circle className="sparkline-head" cx={active.x} cy={active.y} r="2.6" />
    </svg>
  );
}

interface DeltaProps {
  current: number;
  previous: number | undefined;
  /** When true a rise is bad news and should read red. */
  riseIsBad?: boolean;
  suffix?: string;
}

export function Delta({ current, previous, riseIsBad = true, suffix = "" }: DeltaProps) {
  if (previous === undefined || previous === current) {
    return <span className="delta flat">—</span>;
  }

  const change = current - previous;
  const rising = change > 0;
  const bad = riseIsBad ? rising : !rising;

  return (
    <span className={`delta ${bad ? "bad" : "good"}`}>
      <i aria-hidden="true">{rising ? "▲" : "▼"}</i>
      {rising ? "+" : "−"}
      {Math.abs(change).toLocaleString()}
      {suffix}
    </span>
  );
}
