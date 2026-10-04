// Preview-only QA tools for the avatar screen.

/**
 * The emote picker shows on Vercel preview deployments, and locally with `?debug=emotes`.
 * Never on production, whatever the URL says.
 */
export function emotePickerEnabled(deployEnv: string | undefined, search: string): boolean {
  if (deployEnv === "preview") return true;
  if (deployEnv !== "local") return false;
  return new URLSearchParams(search).get("debug") === "emotes";
}
