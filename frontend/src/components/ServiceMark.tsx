import type { IconName } from "./icons";

/**
 * The real logos of the services a run actually touches.
 *
 * Drawn here rather than fetched from a logo CDN, for three reasons:
 * the app has to work behind a firewall and offline, where a remote
 * image is a broken box; an image request from a signed-in page tells
 * a third party which services this company uses, on every page view;
 * and logo CDNs move their paths without telling anybody.
 *
 * They are used to say "your work went to Gmail" — identifying the
 * service we connected to, which is what these marks are for.
 * Anything without a mark here falls back to a plain icon rather than
 * to an approximation of somebody's brand.
 */

export type ServiceKey =
  | "gmail"
  | "gcalendar"
  | "gdrive"
  | "outlook"
  | "onedrive"
  | "postgres"
  | "gemini";

/** Which service a tool name belongs to, or null for "no logo". */
export function serviceForTool(tool: string): ServiceKey | null {
  if (/^gmail_/.test(tool)) return "gmail";
  if (/^google_calendar_/.test(tool)) return "gcalendar";
  if (/^google_drive_/.test(tool)) return "gdrive";
  if (/^outlook_calendar_/.test(tool)) return "outlook";
  if (/^outlook_/.test(tool)) return "outlook";
  if (/^onedrive_/.test(tool)) return "onedrive";
  if (/^run_query$|^list_tables$|^describe_table$/.test(tool)) return "postgres";
  return null;
}

/** The model vendor behind a model id, for the thinking step. */
export function vendorFor(model: string): { label: string; color: string } | null {
  const m = model.toLowerCase();
  if (m.includes("gemini")) return { label: "Gemini", color: "#1a73e8" };
  if (m.includes("claude")) return { label: "Claude", color: "#d97757" };
  if (m.includes("gpt") || m.includes("openai")) return { label: "OpenAI", color: "#10a37f" };
  if (m.includes("llama")) return { label: "Llama", color: "#0668e1" };
  if (m.includes("deepseek")) return { label: "DeepSeek", color: "#4d6bfe" };
  if (m.includes("mistral")) return { label: "Mistral", color: "#fa520f" };
  return null;
}

export const SERVICE_NAME: Record<ServiceKey, string> = {
  gmail: "Gmail",
  gcalendar: "Google Calendar",
  gdrive: "Google Drive",
  outlook: "Outlook",
  onedrive: "OneDrive",
  postgres: "PostgreSQL",
  gemini: "Gemini",
};

/** A plain icon for anything with no logo of its own. */
export const SERVICE_FALLBACK: Record<string, IconName> = {
  web: "link",
  memory: "memory",
  specialist: "employees",
  tool: "terminal",
};

export function ServiceMark({ service, size = 18 }: { service: ServiceKey; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 48 48",
    role: "img" as const,
    "aria-label": SERVICE_NAME[service],
    style: { display: "block" as const },
  };

  switch (service) {
    case "gmail":
      return (
        <svg {...common}>
          <path fill="#4caf50" d="M45 16.2l-5 2.75-5 4.75L35 40h7a3 3 0 0 0 3-3V16.2z" />
          <path fill="#1e88e5" d="M3 16.2l3.614 1.71L13 23.7V40H6a3 3 0 0 1-3-3V16.2z" />
          <path fill="#e53935" d="M35 11.2L24 19.45 13 11.2l-1 5.8 1 6.7 11 8.25 11-8.25 1-6.7z" />
          <path fill="#c62828" d="M3 12.298V16.2l10 7.5V11.2L9.876 8.859A4.298 4.298 0 0 0 3 12.298z" />
          <path fill="#fbc02d" d="M45 12.298V16.2l-10 7.5V11.2l3.124-2.341A4.298 4.298 0 0 1 45 12.298z" />
        </svg>
      );

    case "gcalendar":
      return (
        <svg {...common}>
          <path fill="#fff" d="M11 11h26v26H11z" />
          <path fill="#1e88e5" d="M37 11v7h6v-4a3 3 0 0 0-3-3h-3z" />
          <path fill="#fbc02d" d="M37 37h3a3 3 0 0 0 3-3v-4h-6v7z" />
          <path fill="#4caf50" d="M11 37v6h26v-6H11z" />
          <path fill="#1565c0" d="M43 30H37v-12h6v12z" />
          <path fill="#e53935" d="M37 37H11v6h26v-6z" opacity="0" />
          <path fill="#2e7d32" d="M11 37H8a3 3 0 0 1-3-3v-4h6v7z" />
          <path fill="#1e88e5" d="M5 18V14a3 3 0 0 1 3-3h3v7H5z" />
          <path fill="#1565c0" d="M5 18h6v12H5z" />
          <path fill="#1e88e5" d="M11 11h26v7H11z" />
          <text
            x="24"
            y="33"
            textAnchor="middle"
            fontSize="17"
            fontWeight="600"
            fill="#1a73e8"
            fontFamily="system-ui, sans-serif"
          >
            31
          </text>
        </svg>
      );

    case "gdrive":
      return (
        <svg {...common}>
          <polygon fill="#fbc02d" points="17,6 31,6 45,30 31,30" />
          <polygon fill="#1e88e5" points="9.875,42 16.938,30 45,30 37.938,42" />
          <polygon fill="#4caf50" points="3,30 17,6 24,18 10,42" />
        </svg>
      );

    case "outlook":
      return (
        <svg {...common}>
          <path fill="#0364b8" d="M43 12H24v8l9 5 10-4V13a1 1 0 0 0-1-1z" />
          <path fill="#0f78d4" d="M24 20h19v9H24z" />
          <path fill="#28a8ea" d="M24 29h19v8a1 1 0 0 1-1 1H24z" />
          <path fill="#14447d" d="M24 12h-1l-1 .2V37l1 .2h1z" />
          <rect x="5" y="10" width="21" height="28" rx="2" fill="#0a2767" />
          <path
            fill="#fff"
            d="M15.5 17.4c-3.2 0-5.3 2.6-5.3 6.6s2.1 6.6 5.3 6.6 5.3-2.6 5.3-6.6-2.1-6.6-5.3-6.6zm0 10.6c-1.7 0-2.8-1.6-2.8-4s1.1-4 2.8-4 2.8 1.6 2.8 4-1.1 4-2.8 4z"
          />
        </svg>
      );

    case "onedrive":
      return (
        <svg {...common}>
          <path
            fill="#0364b8"
            d="M19.5 15.5a9.5 9.5 0 0 1 16.3 3.6 7.6 7.6 0 0 1 6.2 7.5 7.6 7.6 0 0 1-7.6 7.6H13.5A8.5 8.5 0 0 1 5 25.7a8.5 8.5 0 0 1 7.1-8.4 9.5 9.5 0 0 1 7.4-1.8z"
          />
          <path
            fill="#0f78d4"
            d="M35.8 19.1a7.6 7.6 0 0 1 6.2 7.5 7.6 7.6 0 0 1-7.6 7.6H19.9l-4.3-9.4 4-7.2 16.2 1.5z"
          />
          <path
            fill="#28a8ea"
            d="M42 26.6a7.6 7.6 0 0 1-7.6 7.6h-14l-2-7 23.4-2.3c.1.5.2 1.1.2 1.7z"
          />
        </svg>
      );

    case "postgres":
      return (
        <svg {...common}>
          <ellipse cx="24" cy="12" rx="15" ry="6" fill="#336791" />
          <path fill="#336791" d="M9 12v24c0 3.3 6.7 6 15 6s15-2.7 15-6V12H9z" />
          <ellipse cx="24" cy="12" rx="15" ry="6" fill="#4a7fa8" />
          <path
            d="M9 20c0 3.3 6.7 6 15 6s15-2.7 15-6M9 29c0 3.3 6.7 6 15 6s15-2.7 15-6"
            stroke="#8ab4d4"
            strokeWidth="1.6"
            fill="none"
          />
        </svg>
      );

    case "gemini":
      // The four-pointed star: concave diamond, equal on both axes.
      return (
        <svg {...common}>
          <path
            fill="#1a73e8"
            d="M24 4c0 11 9 20 20 20-11 0-20 9-20 20 0-11-9-20-20-20 11 0 20-9 20-20z"
          />
        </svg>
      );
  }
}

/** A lettermark for a model vendor we have no logo for. */
export function VendorChip({ label, color, size = 18 }: { label: string; color: string; size?: number }) {
  return (
    <span
      aria-label={label}
      role="img"
      className="flex shrink-0 items-center justify-center rounded-[5px] font-display font-bold"
      style={{
        width: size,
        height: size,
        background: color,
        color: "#fff",
        fontSize: size * 0.58,
        lineHeight: 1,
      }}
    >
      {label.charAt(0)}
    </span>
  );
}
