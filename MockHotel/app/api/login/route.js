import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import { setSession } from "@/lib/session";

export async function POST(request) {
  const { username, password } = await request.json();

  if (!username || !password) {
    return NextResponse.json({ error: "Username and password are required" }, { status: 400 });
  }

  const result = await query(
    `
      SELECT id, username, role
      FROM account
      WHERE username = $1
        AND password_hash = crypt($2, password_hash)
      LIMIT 1
    `,
    [username, password]
  );

  const user = result.rows[0];
  if (!user) {
    return NextResponse.json({ error: "Invalid username or password" }, { status: 401 });
  }

  await setSession(user);
  return NextResponse.json({ user });
}
