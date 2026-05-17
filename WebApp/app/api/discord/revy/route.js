import crypto from "crypto";
import { NextResponse } from "next/server";
import { handleDiscordRevyMessage, normalizeDiscordText } from "@/lib/discordRevy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DISCORD_INTERACTION_CALLBACK = 4;
const DISCORD_PONG = 1;

function json(data, status = 200) {
  return NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function publicKeyObject(hexKey) {
  const clean = String(hexKey || "").trim();
  if (!/^[0-9a-fA-F]{64}$/.test(clean)) return null;
  const prefix = Buffer.from("302a300506032b6570032100", "hex");
  const key = Buffer.concat([prefix, Buffer.from(clean, "hex")]);
  return crypto.createPublicKey({ key, format: "der", type: "spki" });
}

function verifyDiscordSignature(request, rawBody) {
  const publicKey = process.env.DISCORD_PUBLIC_KEY || process.env.REVNEST_DISCORD_PUBLIC_KEY;
  if (!publicKey) return false;
  const signature = request.headers.get("x-signature-ed25519");
  const timestamp = request.headers.get("x-signature-timestamp");
  if (!signature || !timestamp || !/^[0-9a-fA-F]+$/.test(signature)) return false;
  const key = publicKeyObject(publicKey);
  if (!key) return false;
  try {
    return crypto.verify(null, Buffer.from(`${timestamp}${rawBody}`), key, Buffer.from(signature, "hex"));
  } catch {
    return false;
  }
}

function tokenFromRequest(request) {
  const auth = request.headers.get("authorization") || "";
  const bearer = auth.match(/^Bearer\s+(.+)$/i)?.[1];
  return bearer || request.headers.get("x-revnest-discord-token") || "";
}

function authenticate(request, rawBody) {
  const hasDiscordSignature = Boolean(request.headers.get("x-signature-ed25519"));
  if (hasDiscordSignature) {
    return verifyDiscordSignature(request, rawBody)
      ? { ok: true, source: "discord_signature" }
      : { ok: false, status: 401, error: "Invalid Discord signature" };
  }

  const expected = process.env.REVNEST_DISCORD_INBOUND_TOKEN;
  if (expected) {
    const received = tokenFromRequest(request);
    const left = Buffer.from(received);
    const right = Buffer.from(expected);
    const ok = left.length === right.length && crypto.timingSafeEqual(left, right);
    return ok ? { ok: true, source: "shared_token" } : { ok: false, status: 401, error: "Invalid Discord inbound token" };
  }

  return { ok: false, status: 401, error: "Configure DISCORD_PUBLIC_KEY or REVNEST_DISCORD_INBOUND_TOKEN before accepting Discord inbound messages" };
}

function optionValue(option) {
  if (!option || typeof option !== "object") return "";
  if (option.value !== undefined) return option.value;
  if (Array.isArray(option.options)) return option.options.map(optionValue).filter(Boolean).join(" ");
  return "";
}

function extractInteractionText(payload) {
  const options = Array.isArray(payload?.data?.options) ? payload.data.options : [];
  const direct = options.find((item) => ["message", "text", "prompt", "question"].includes(String(item?.name || "").toLowerCase()));
  const value = optionValue(direct) || options.map(optionValue).filter(Boolean).join(" ") || payload?.data?.name || "";
  return normalizeDiscordText(value);
}

function extractInbound(payload) {
  if (payload?.type === 2 || payload?.type === 3 || payload?.type === 4 || payload?.type === 5) {
    return {
      text: extractInteractionText(payload),
      guildId: payload.guild_id || null,
      channelId: payload.channel_id || null,
      userId: payload.member?.user?.id || payload.user?.id || null,
      username: payload.member?.user?.global_name || payload.member?.user?.username || payload.user?.global_name || payload.user?.username || null,
      interaction: true,
    };
  }

  const eventPayload = payload?.d && typeof payload.d === "object" ? payload.d : payload;
  return {
    text: eventPayload.content || eventPayload.text || eventPayload.message || payload?.content || payload?.text || "",
    guildId: eventPayload.guild_id || eventPayload.guildId || payload?.guild_id || payload?.guildId || null,
    channelId: eventPayload.channel_id || eventPayload.channelId || payload?.channel_id || payload?.channelId || null,
    userId: eventPayload.author?.id || eventPayload.user?.id || eventPayload.userId || payload?.userId || null,
    username: eventPayload.author?.global_name || eventPayload.author?.username || eventPayload.user?.username || payload?.username || null,
    bot: Boolean(eventPayload.author?.bot || eventPayload.user?.bot),
    interaction: false,
  };
}

function interactionResponse(content) {
  return json({ type: DISCORD_INTERACTION_CALLBACK, data: { content: String(content || "") } });
}

export async function GET() {
  return json({
    ok: true,
    route: "/api/discord/revy",
    identity: "Revy, RevNest hotel revenue management agent",
    auth: {
      discordSignature: Boolean(process.env.DISCORD_PUBLIC_KEY || process.env.REVNEST_DISCORD_PUBLIC_KEY),
      sharedToken: Boolean(process.env.REVNEST_DISCORD_INBOUND_TOKEN),
    },
  });
}

export async function POST(request) {
  const rawBody = await request.text();
  const auth = authenticate(request, rawBody);
  if (!auth.ok) return json({ error: auth.error }, auth.status);

  let payload;
  try {
    payload = rawBody ? JSON.parse(rawBody) : {};
  } catch {
    return json({ error: "Request body must be JSON" }, 400);
  }

  if (payload?.type === DISCORD_PONG) {
    return json({ type: DISCORD_PONG });
  }

  const inbound = extractInbound(payload);
  if (inbound.bot) return json({ ignored: true, reason: "bot_message" });

  try {
    const result = await handleDiscordRevyMessage(inbound);
    if (inbound.interaction) return interactionResponse(result.reply);
    return json({ ...result, auth: auth.source });
  } catch (error) {
    const message = error.message || "Revy Discord inbound route failed";
    if (inbound.interaction) return interactionResponse(`Revy could not handle that Discord request: ${message}`);
    return json({ error: message }, 500);
  }
}
