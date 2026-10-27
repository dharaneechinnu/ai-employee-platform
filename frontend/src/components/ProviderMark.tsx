import { Icon } from "./icons";
import { ServiceMark, VendorChip } from "./ServiceMark";

/**
 * The mark for an AI provider or a search provider.
 *
 * Gemini has a real mark in ServiceMark. The rest are a lettermark in
 * the vendor's colour: ServiceMark's rule is a plain stand-in rather
 * than an approximation of somebody's logo, and that holds here. A real
 * logo for any of them is one more branch in this switch.
 */
const VENDOR: Record<string, { label: string; color: string }> = {
  anthropic: { label: "Claude", color: "#d97757" },
  openai: { label: "OpenAI", color: "#10a37f" },
  groq: { label: "Groq", color: "#f55036" },
  deepseek: { label: "DeepSeek", color: "#4d6bfe" },
  mistral: { label: "Mistral", color: "#fa520f" },
  openrouter: { label: "OpenRouter", color: "#6467f2" },
  sarvam: { label: "Sarvam", color: "#e8590c" },
  tavily: { label: "Tavily", color: "#3b6cf6" },
  brave: { label: "Brave", color: "#fb542b" },
};

export function ProviderMark({ provider, size = 28 }: { provider: string; size?: number }) {
  const key = provider.toLowerCase();

  if (key === "gemini" || key === "google") return <ServiceMark service="gemini" size={size} />;

  if (key === "custom" || key === "local" || key === "ollama") {
    return (
      <span
        role="img"
        aria-label="Model on your own machine"
        className="flex shrink-0 items-center justify-center rounded-[7px] bg-raised text-ink"
        style={{ width: size, height: size }}
      >
        <Icon name="cpu" size={Math.round(size * 0.62)} />
      </span>
    );
  }

  const vendor = VENDOR[key];
  if (vendor) return <VendorChip label={vendor.label} color={vendor.color} size={size} />;

  return <VendorChip label={provider || "?"} color="#667085" size={size} />;
}
