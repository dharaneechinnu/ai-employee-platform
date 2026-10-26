/**
 * The mark, which is also the status light.
 *
 * In a slim icon rail there is no room for the "3 running / 2 waiting"
 * lines the wide menu used to carry, and those are the two things
 * someone actually wants to know at a glance. So the mark carries them:
 * the ring around it reports what your assistant is doing.
 *
 *   idle      no ring, calm
 *   running   a ring sweeping in the run colour
 *   waiting   a steady amber ring, breathing
 *
 * Waiting outranks running, because a run continues on its own and an
 * approval does not: nothing moves until you look.
 *
 * The glyph itself is a rounded tile with a smaller tile lifted off its
 * corner — a worker, and the spark handed to them. Deliberately not a
 * person silhouette, which would read as a profile picture, and
 * deliberately not a dot grid, which reads as a drag handle.
 */
export type BrandState = "idle" | "running" | "waiting";

// Spelled out for the same reason as the rail's position classes:
// Tailwind drops a component rule whose name it never sees in source.
const RING: Record<BrandState, string> = {
  idle: "",
  running: "brand-ring brand-ring-running",
  waiting: "brand-ring brand-ring-waiting",
};

export function BrandMark({
  size = 34,
  state = "idle",
}: {
  size?: number;
  state?: BrandState;
}) {
  const ring = size + Math.max(6, size * 0.2);

  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: ring, height: ring }}
      aria-hidden="true"
    >
      {state !== "idle" && (
        <span
          className={RING[state]}
          style={{ width: ring, height: ring, borderRadius: ring * 0.34 }}
        />
      )}

      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        className="relative"
        style={{ borderRadius: size * 0.3 }}
      >
        <rect width="32" height="32" rx="9.6" fill="var(--accent)" />
        {/* the worker */}
        <rect x="7" y="12" width="13" height="13" rx="4" fill="var(--on-accent)" opacity="0.95" />
        {/* the spark, lifted off the corner */}
        <rect
          x="18.5"
          y="6"
          width="8"
          height="8"
          rx="2.6"
          fill="var(--on-accent)"
          opacity="0.55"
        />
      </svg>
    </span>
  );
}
