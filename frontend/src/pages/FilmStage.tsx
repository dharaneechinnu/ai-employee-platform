import { Film } from "../components/film/Film";

/**
 * The film alone, filling the window, with no player controls.
 * `?record=1` hands control to the MP4 exporter (scripts/record-film),
 * which seeks frame by frame; without it the film simply plays.
 */
export default function FilmStage() {
  const record = new URLSearchParams(window.location.search).has("record");
  return (
    <div className="flex min-h-screen items-center justify-center bg-black">
      <div style={{ width: "min(100vw, calc(100vh * 16 / 9))" }}>
        <Film mode={record ? "record" : "player"} />
      </div>
    </div>
  );
}
