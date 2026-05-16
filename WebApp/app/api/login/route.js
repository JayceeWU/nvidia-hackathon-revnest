import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import { setSessionCookie } from "@/lib/serverSession";

export async function POST(request) {
  let input = {};
  try {
    input = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid login request." }, { status: 400 });
  }

  const { email, password } = input;

  if (!email || !password) {
    return NextResponse.json({ error: "Email and password are required" }, { status: 400 });
  }

  const normalizedEmail = email.trim().toLowerCase();

  try {
    const result = await query(
      `
        SELECT id, email, name, role, account_type AS "accountType"
        FROM account
        WHERE email = $1
          AND password_hash = crypt($2, password_hash)
        LIMIT 1
      `,
      [normalizedEmail, password]
    );

    const user = result.rows[0];
    if (!user) {
      return NextResponse.json({ error: "Invalid email or password" }, { status: 401 });
    }

    const response = NextResponse.json({ user });
    setSessionCookie(response, user);
    return response;
  } catch (error) {
    if (error.code !== "42703") {
      console.error("Login failed", error);
      return NextResponse.json({ error: "Login failed. Check the database connection and logs." }, { status: 500 });
    }

    const legacyEmail = normalizedEmail === "hotel@revnest.ai" ? "motel@revnest.ai" : normalizedEmail;
    const legacyResult = await query(
      `
        SELECT id, email, name, role
        FROM account
        WHERE email = $1
          AND password_hash = crypt($2, password_hash)
        LIMIT 1
      `,
      [legacyEmail, password]
    );

    const legacyUser = legacyResult.rows[0];
    if (!legacyUser) {
      return NextResponse.json({ error: "Invalid email or password" }, { status: 401 });
    }

    const legacyPayload = {
      user: {
        ...legacyUser,
        email: normalizedEmail === "hotel@revnest.ai" ? "hotel@revnest.ai" : legacyUser.email,
        name: normalizedEmail === "hotel@revnest.ai" ? "Hotel Operator" : legacyUser.name,
        accountType: normalizedEmail === "airbnb@revnest.ai" ? "airbnb" : "hotel",
      },
      warning: "Using legacy account schema. Rebuild the local database to persist account_type.",
    };
    const response = NextResponse.json(legacyPayload);
    setSessionCookie(response, legacyPayload.user);
    return response;
  }
}
