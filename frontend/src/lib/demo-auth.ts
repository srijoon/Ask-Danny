// Prototype sign-in. ALSAC / ALSAC is checked here in the browser and never
// reaches Flask, so the dashboard opens even when no backend is running. Any
// other credentials still go to POST /api/login as before.
//
// The flag lives in sessionStorage: it ends when the tab closes, and the
// accessor can throw (private windows, blocked site data), hence the try/catch.
// Remove this file once the team has real accounts in the backend.
import type { User } from "@/lib/api";

const DEMO_USERNAME = "ALSAC";
const DEMO_PASSWORD = "ALSAC";
const STORAGE_KEY = "ask-danny-demo-session";

// stands in for the /api/me response so pages can render the same way
export const DEMO_USER: User = {
  id: "demo",
  username: DEMO_USERNAME,
  groups: [],
  isAdmin: false,
  pools: [{ id: "shared", type: "shared", name: "Shared" }],
};

export function isDemoCredentials(username: string, password: string): boolean {
  return username.trim() === DEMO_USERNAME && password === DEMO_PASSWORD;
}

// false when the browser refuses storage, so the caller can say why sign-in failed
export function startDemoSession(): boolean {
  try {
    sessionStorage.setItem(STORAGE_KEY, "1");
    return true;
  } catch {
    return false;
  }
}

export function endDemoSession(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // nothing stored, nothing to clear
  }
}

export function hasDemoSession(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}
