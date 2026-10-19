import type { ReactNode } from "react";

/**
 * The run's answer, set as prose.
 *
 * Models write Markdown whether or not you ask them to, so a raw
 * `whitespace-pre-wrap` dump shows people `**bold**` and `- item` and
 * makes the product look unfinished. This renders the handful of
 * things that actually turn up in an answer — headings, bullets,
 * numbered steps, bold, inline code, fenced blocks, links — and
 * leaves everything else as plain text.
 *
 * Deliberately not a Markdown library: those are 40–90 KB for a
 * feature list we do not use, and they bring an HTML sanitiser
 * question with them. Here nothing is ever set as HTML, so model
 * output cannot inject anything — it can only ever become text inside
 * elements we chose.
 */

/** Bold, inline code and links, inside one line of text. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  // One pass, four patterns, `**` before `*` so bold wins over italic
  // — the other order leaves a stray asterisk either side of every
  // bold run, which is exactly how this looked before.
  const pattern =
    /(\*\*[^*]+\*\*)|(`[^`]+`)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))|(\*[^*\n]+\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const [whole] = match;

    if (whole.startsWith("**")) {
      out.push(<strong key={`${keyPrefix}-b${i}`}>{whole.slice(2, -2)}</strong>);
    } else if (whole.startsWith("*")) {
      out.push(<em key={`${keyPrefix}-i${i}`}>{whole.slice(1, -1)}</em>);
    } else if (whole.startsWith("`")) {
      out.push(<code key={`${keyPrefix}-c${i}`}>{whole.slice(1, -1)}</code>);
    } else {
      const label = whole.slice(1, whole.indexOf("]"));
      const href = match[4];
      out.push(
        // `noreferrer` matters here: the destination came from a model,
        // which got it from somewhere we do not control.
        <a key={`${keyPrefix}-a${i}`} href={href} target="_blank" rel="noreferrer noopener">
          {label}
        </a>,
      );
    }
    last = match.index + whole.length;
    i += 1;
  }

  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Prose({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];

  let bullets: string[] = [];
  let numbers: string[] = [];
  let fence: string[] | null = null;
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) {
      blocks.push(
        <p key={`p${blocks.length}`}>{inline(paragraph.join(" "), `p${blocks.length}`)}</p>,
      );
      paragraph = [];
    }
    if (bullets.length) {
      blocks.push(
        <ul key={`u${blocks.length}`}>
          {bullets.map((b, i) => (
            <li key={i}>{inline(b, `u${blocks.length}-${i}`)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
    if (numbers.length) {
      blocks.push(
        <ol key={`o${blocks.length}`}>
          {numbers.map((n, i) => (
            <li key={i}>{inline(n, `o${blocks.length}-${i}`)}</li>
          ))}
        </ol>,
      );
      numbers = [];
    }
  };

  for (const line of lines) {
    if (line.trimStart().startsWith("```")) {
      if (fence === null) {
        flush();
        fence = [];
      } else {
        blocks.push(
          <pre key={`f${blocks.length}`}>
            <code>{fence.join("\n")}</code>
          </pre>,
        );
        fence = null;
      }
      continue;
    }
    if (fence !== null) {
      fence.push(line);
      continue;
    }

    const trimmed = line.trim();

    if (!trimmed) {
      flush();
      continue;
    }

    const heading = /^#{1,6}\s+(.*)$/.exec(trimmed);
    if (heading) {
      flush();
      blocks.push(<h3 key={`h${blocks.length}`}>{inline(heading[1], `h${blocks.length}`)}</h3>);
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(trimmed);
    if (quote) {
      flush();
      blocks.push(
        <blockquote key={`q${blocks.length}`}>{inline(quote[1], `q${blocks.length}`)}</blockquote>,
      );
      continue;
    }

    const bullet = /^[-*•]\s+(.*)$/.exec(trimmed);
    if (bullet) {
      if (paragraph.length || numbers.length) flush();
      bullets.push(bullet[1]);
      continue;
    }

    const numbered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    if (numbered) {
      if (paragraph.length || bullets.length) flush();
      numbers.push(numbered[1]);
      continue;
    }

    if (bullets.length || numbers.length) flush();
    paragraph.push(trimmed);
  }

  // An answer that ends inside a fence is truncated output, not a
  // reason to lose it.
  if (fence !== null) {
    blocks.push(
      <pre key={`f${blocks.length}`}>
        <code>{fence.join("\n")}</code>
      </pre>,
    );
  }
  flush();

  return <div className="result-prose">{blocks}</div>;
}
