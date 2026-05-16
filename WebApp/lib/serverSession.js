import crypto from "crypto";

export const SESSION_COOKIE_NAME = "revnest_session";
const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;

function sessionSecret() {
  const secret =
    process.env.REVNEST_SESSION_SECRET ||
    process.env.WEBAPP_SESSION_SECRET ||
    process.env.NEXTAUTH_SECRET;

  if (secret) {
    return secret;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("REVNEST_SESSION_SECRET must be set in production.");
  }
  return "revnest-local-dev-session-secret";
}

function secureSessionCookie() {
  return process.env.NODE_ENV === "production" && process.env.REVNEST_INSECURE_LOCAL_COOKIES !== "1";
}

function encodeJson(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function decodeJson(value) {
  return JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
}

function sign(value) {
  return crypto.createHmac("sha256", sessionSecret()).update(value).digest("base64url");
}

function safeEqual(left, right) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

export function createSessionValue(user) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    accountType: user.accountType || user.account_type || null,
    iat: now,
    exp: now + SESSION_MAX_AGE_SECONDS,
  };
  const encoded = encodeJson(payload);
  return `${encoded}.${sign(encoded)}`;
}

export function setSessionCookie(response, user) {
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: createSessionValue(user),
    httpOnly: true,
    sameSite: "lax",
    secure: secureSessionCookie(),
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export function clearSessionCookie(response) {
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: secureSessionCookie(),
    path: "/",
    maxAge: 0,
  });
}

export function readSession(request) {
  try {
    const cookie = request.cookies.get(SESSION_COOKIE_NAME)?.value;
    if (!cookie) {
      return null;
    }
    const [encoded, signature] = cookie.split(".");
    if (!encoded || !signature || !safeEqual(sign(encoded), signature)) {
      return null;
    }
    const session = decodeJson(encoded);
    const now = Math.floor(Date.now() / 1000);
    if (!session?.id || !session.exp || session.exp < now) {
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function requireAccountSession(request, accountId) {
  const session = readSession(request);
  if (!session) {
    return {
      error: { message: "A valid WebApp session is required.", status: 401 },
      session: null,
    };
  }
  if (String(session.id) !== String(accountId)) {
    return {
      error: { message: "Session account does not match accountId.", status: 403 },
      session: null,
    };
  }
  return { error: null, session };
}

export function approvalActor(session) {
  return {
    id: session.id,
    email: session.email || null,
    name: session.name || null,
    role: session.role || null,
    accountType: session.accountType || null,
  };
}
