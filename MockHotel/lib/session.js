import crypto from "crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = "mock_hotel_session";
const secret = process.env.SESSION_SECRET || "mock-hotel-local-secret";

function sign(payload) {
  return crypto.createHmac("sha256", secret).update(payload).digest("base64url");
}

export function createSessionValue(user) {
  const body = Buffer.from(
    JSON.stringify({
      id: user.id,
      username: user.username,
      role: user.role,
      exp: Date.now() + 1000 * 60 * 60 * 8
    })
  ).toString("base64url");

  return `${body}.${sign(body)}`;
}

export async function setSession(user) {
  const jar = await cookies();
  jar.set(COOKIE_NAME, createSessionValue(user), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 8
  });
}

export async function clearSession() {
  const jar = await cookies();
  jar.delete(COOKIE_NAME);
}

export async function getSession() {
  const jar = await cookies();
  const value = jar.get(COOKIE_NAME)?.value;
  if (!value) {
    return null;
  }

  const [body, signature] = value.split(".");
  if (!body || !signature || sign(body) !== signature) {
    return null;
  }

  try {
    const session = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (!session.exp || session.exp < Date.now()) {
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export async function requireSession() {
  const session = await getSession();
  if (!session) {
    throw Object.assign(new Error("Authentication required"), { status: 401 });
  }
  return session;
}
