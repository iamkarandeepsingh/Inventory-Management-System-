const STORAGE_KEY = "inv_jwt_token";

export function getToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function authHeaders(): HeadersInit {
  const t = getToken();
  if (!t) return {};
  return { Authorization: `Bearer ${t}` };
}

export type JwtDisplay = {
  sub?: string;
  username?: string;
  role?: string;
  exp?: number;
};

export function parseJwtPayload(token: string): JwtDisplay | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const pad = base64.length % 4;
    const padded = base64 + (pad ? "=".repeat(4 - pad) : "");
    const json = decodeURIComponent(
      atob(padded)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(json) as JwtDisplay;
  } catch {
    return null;
  }
}
