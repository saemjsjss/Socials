// Idle behaviour (spec § Idle behaviour): after ~3 min of silence a single spoken check-in.
// (Her idle motion is the director's idle sequence.) Her own speech counts as "not silent"
// but only the user re-arms the check-in.

export const CHECK_IN_MS = 180_000;

export interface IdleState {
  quietSince: number;
  checkedIn: boolean;
}

export type IdleAction = "check-in" | null;

/** Any user interaction: full reset, the check-in is armed again. */
export function resetIdle(now: number): IdleState {
  return { quietSince: now, checkedIn: false };
}

/** She is speaking / listening / thinking: silence restarts, but a done check-in stays done. */
export function holdIdle(state: IdleState, now: number): IdleState {
  return { ...resetIdle(now), checkedIn: state.checkedIn };
}

export function idleStep(state: IdleState, now: number): { state: IdleState; action: IdleAction } {
  if (!state.checkedIn && now - state.quietSince >= CHECK_IN_MS) {
    return { state: { ...state, checkedIn: true }, action: "check-in" };
  }
  return { state, action: null };
}

export const CHECK_IN_LINES = [
  "자기야, 괜찮아요? 잠깐 쉬어 가는 건 어때요?",
  "부장님, 조용하시네요. 무리하지 마시고 물 한 잔 드세요.",
  "자기야, 많이 바쁘죠? 제가 도와드릴 일 있으면 언제든 말해 주세요.",
  "부장님, 오래 집중하셨어요. 잠깐 스트레칭하고 오실래요?",
] as const;

export function pickCheckIn(random: () => number = Math.random): string {
  const index = Math.min(CHECK_IN_LINES.length - 1, Math.floor(random() * CHECK_IN_LINES.length));
  return CHECK_IN_LINES[index]!;
}
