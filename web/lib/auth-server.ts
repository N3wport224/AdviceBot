import { timingSafeEqual } from "crypto";

export { ACCESS_HEADER } from "./auth";

/** Is the password gate enabled on this deployment? */
export function gateEnabled(): boolean {
  return Boolean(process.env.ACCESS_PASSWORD);
}

/**
 * Constant-time password check against ACCESS_PASSWORD.
 * When the env var is unset the gate is disabled and everything passes
 * (local dev convenience — set it in production!).
 */
export function passwordOk(supplied: string | null | undefined): boolean {
  const expected = process.env.ACCESS_PASSWORD ?? "";
  if (!expected) return true;
  const a = Buffer.from(supplied ?? "");
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
