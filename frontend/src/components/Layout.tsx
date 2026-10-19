import { useActivity } from "../lib/activity";
import { useDock } from "../lib/dock";
import { CoachHelp, CoachProvider } from "./coach/Coach";
import Rail from "./Rail";
import { Outlet } from "react-router-dom";

export { BrandMark } from "./BrandMark";

/**
 * The shell.
 *
 * Navigation is a floating icon rail the user drags to whichever edge
 * suits them — left, right or along the bottom. The page itself is a
 * single column underneath, with padding reserved for the rail in CSS,
 * so no page has to know where the menu currently is.
 *
 * Replaces a fixed 248px sidebar. On a laptop that column cost a fifth
 * of the width to nine words, and on a phone it could only ever be a
 * drawer you had to open before you could go anywhere.
 */
export default function Layout() {
  const { running, waiting } = useActivity();
  const [dock, setDock] = useDock();

  return (
    <CoachProvider>
      <div className="flex min-h-screen flex-col">
        <main className="flex min-w-0 flex-1 flex-col" style={{ background: "var(--hero)" }}>
          <Outlet />
        </main>

        <Rail dock={dock} setDock={setDock} running={running} waiting={waiting} />
        <CoachHelp />
      </div>
    </CoachProvider>
  );
}
