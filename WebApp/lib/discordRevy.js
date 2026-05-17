import { getRun, isHostRunProcessAlive, startAgentRun } from "@/lib/agentRunStore";
import { query } from "@/lib/db";

const DEMO_HOTEL_ACCOUNT_ID = "00000000-0000-0000-0000-000000000103";
const PRICING_WORDS = ["run", "refresh", "price", "pricing", "reprice", "rate", "rates", "revpar", "定价", "收益", "价格", "刷新", "跑", "酒店"];
const STATUS_WORDS = ["status", "progress", "thinking", "running", "进度", "状态", "在跑", "运行"];
const IDENTITY_PATTERNS = [
  /\bwho\s+are\s+you\b/i,
  /\bwhat\s+are\s+you\b/i,
  /\bwho\s+is\s+revy\b/i,
  /\bintroduce\s+yourself\b/i,
  /你是谁/,
  /你是誰/,
  /你叫什么/,
  /自我介绍/,
  /你能做什么/,
];

function includesAny(text, words) {
  const lowered = String(text || "").toLowerCase();
  return words.some((word) => lowered.includes(word));
}

function prefersChinese(text) {
  return /[\u3400-\u9fff]/.test(String(text || ""));
}

function sanitizeConversationPart(value) {
  return String(value || "discord")
    .replace(/[^a-zA-Z0-9._-]/g, "-")
    .slice(0, 80) || "discord";
}

export function revyIdentityReply(text = "", accountType = "hotel") {
  if (prefersChinese(text)) {
    if (accountType === "hotel") {
      return "我是 Revy，RevNest 的酒店收益管理 agent。我在 RevNest/OpenClaw 环境里运行，负责读取 MockHotel/PMS 当前价格、市场信号、策略记忆和价格护栏，生成需要人工审批的酒店定价建议；我不会直接改 live PMS 价格。";
    }
    return "我是 Revy，RevNest 的收益管理 agent。我帮助 Airbnb host 和小型酒店读取市场信号、策略记忆和价格护栏，生成可解释、可审批的定价建议。";
  }
  if (accountType === "hotel") {
    return "I am Revy, RevNest's hotel revenue management agent. I run in the RevNest/OpenClaw environment, read PMS prices, market signals, strategy memory, and guardrails, then create approval-ready hotel pricing recommendations without directly mutating live PMS rates.";
  }
  return "I am Revy, RevNest's revenue management agent for Airbnb hosts and small hotels. I turn live market signals, strategy memory, and guardrails into explainable pricing recommendations.";
}

function helpReply(text = "") {
  if (prefersChinese(text)) {
    return "我是 Revy。你可以问我“你是谁”、问“状态/进度”，或者发 “run hotel pricing” 来启动 Dream Inn 酒店全房型定价流程。";
  }
  return "I am Revy. Ask who I am, ask for status, or send `run hotel pricing` to start the Dream Inn all-room-types pricing workflow.";
}

function isIdentityQuestion(text) {
  return IDENTITY_PATTERNS.some((pattern) => pattern.test(String(text || "")));
}

function isStatusQuestion(text) {
  return includesAny(text, STATUS_WORDS);
}

function isHotelPricingRequest(text) {
  const value = String(text || "").toLowerCase();
  if (!includesAny(value, PRICING_WORDS)) return false;
  return value.includes("hotel") || value.includes("dream inn") || value.includes("酒店") || value.includes("room") || value.includes("房型");
}

async function accountType(accountId) {
  const result = await query(
    `
      SELECT account_type
      FROM account
      WHERE id = $1::uuid
      LIMIT 1
    `,
    [accountId],
  );
  return result.rows[0]?.account_type || "hotel";
}

function channelMatches(row, { guildId, channelId, userId }) {
  const data = row.data || {};
  const guildValues = [data.guildId, data.serverId, data.discordGuildId].filter(Boolean).map(String);
  const channelValues = [data.channelId, data.discordChannelId].filter(Boolean).map(String);
  const userValues = [data.userId, data.discordUserId, ...(Array.isArray(data.userIds) ? data.userIds : [])].filter(Boolean).map(String);
  let score = 0;
  if (guildId && guildValues.includes(String(guildId))) score += 4;
  if (channelId && channelValues.includes(String(channelId))) score += 6;
  if (userId && userValues.includes(String(userId))) score += 2;
  return score;
}

export async function resolveDiscordAccount({ guildId, channelId, userId } = {}) {
  if (process.env.REVNEST_DISCORD_ACCOUNT_ID) {
    return { accountId: process.env.REVNEST_DISCORD_ACCOUNT_ID, source: "env" };
  }

  const result = await query(
    `
      SELECT account_id::text AS account_id, data
      FROM account_channel
      WHERE lower(id) = 'discord'
         OR lower(data->>'id') = 'discord'
         OR lower(data->>'name') = 'discord'
      ORDER BY created_at, id
    `,
  );

  if (result.rows.length === 0) {
    if (process.env.NODE_ENV !== "production") {
      return { accountId: DEMO_HOTEL_ACCOUNT_ID, source: "local-demo-default" };
    }
    return null;
  }

  const scored = result.rows
    .map((row) => ({ row, score: channelMatches(row, { guildId, channelId, userId }) }))
    .sort((left, right) => right.score - left.score);
  if (scored[0]?.score > 0) {
    return { accountId: scored[0].row.account_id, source: "account_channel_match" };
  }
  if (result.rows.length === 1) {
    return { accountId: result.rows[0].account_id, source: "single_discord_channel" };
  }
  return null;
}

async function getHotelRoomTypeProperties(accountId) {
  const result = await query(
    `
      SELECT id, data
      FROM property
      WHERE account_id = $1::uuid
        AND data->>'propertyType' = 'Hotel Room Type'
      ORDER BY id
    `,
    [accountId],
  );
  return result.rows;
}

function runningRunForProperties(properties) {
  for (const row of properties) {
    const runId = row.data?.activeAgentRunId;
    if (!runId) continue;
    const run = getRun(runId);
    if (run.status === "running" || isHostRunProcessAlive(runId)) return run;
  }
  return null;
}

async function hotelStatusReply(accountId, text) {
  const properties = await getHotelRoomTypeProperties(accountId);
  const running = runningRunForProperties(properties);
  if (running) {
    return prefersChinese(text)
      ? `Revy 正在运行酒店定价流程：${running.runId}，状态 ${running.status}。打开 RevNest WebApp 的 Revy 页可以看实时 reasoning trace。`
      : `Revy is already running a hotel pricing workflow: ${running.runId} (${running.status}). Open the RevNest WebApp Revy page for the live reasoning trace.`;
  }
  return prefersChinese(text) ? "Revy 现在空闲，没有正在运行的酒店定价流程。" : "Revy is idle; no hotel pricing workflow is currently running.";
}

async function startHotelPricingRun({ accountId, channelId, text }) {
  const roomTypeProperties = await getHotelRoomTypeProperties(accountId);
  if (roomTypeProperties.length === 0) {
    return {
      action: "missing_hotel_properties",
      reply: prefersChinese(text) ? "我找不到这个账号下的酒店房型 property，无法启动酒店定价流程。" : "I could not find hotel room-type properties for this account, so I cannot start the hotel pricing workflow.",
    };
  }

  const runningRun = runningRunForProperties(roomTypeProperties);
  if (runningRun) {
    return {
      action: "already_running",
      run: runningRun,
      reply: prefersChinese(text)
        ? `Revy 已经在跑酒店定价流程：${runningRun.runId}。我不会重复启动；请在 WebApp 的 Revy 页看实时进度。`
        : `Revy is already running a hotel pricing workflow: ${runningRun.runId}. I will not start a duplicate; watch the live progress in the WebApp Revy page.`,
    };
  }

  const conversationId = `discord-revy-${sanitizeConversationPart(channelId)}-${Date.now()}`;
  const run = startAgentRun({
    accountId,
    propertyIds: roomTypeProperties.map((row) => row.id),
    propertyType: "hotel",
    hotelScope: "all-room-types",
    conversationId,
    runtimeMode: "nemoclaw",
    supplementalInfo: `Discord inbound request: ${String(text || "").slice(0, 500)}`,
  });

  await query(
    `
      UPDATE property
      SET data = data - 'agentRunError' - 'pricingOutputError' - 'agentRunStopReason' - 'agentRunFinishedAt' || $3::jsonb,
          updated_at = now()
      WHERE account_id = $1::uuid
        AND id = ANY($2::text[])
    `,
    [
      accountId,
      roomTypeProperties.map((row) => row.id),
      JSON.stringify({
        activeAgentRunId: run.runId,
        activeRevyConversationId: run.conversationId,
        agentRunStatus: "running",
        agentRunStartedAt: run.startedAt,
        agentRunRuntimeMode: run.runtimeMode,
        agentRunHotelScope: run.hotelScope,
        agentRunSource: "discord",
      }),
    ],
  );

  return {
    action: "started_hotel_pricing",
    run,
    reply: prefersChinese(text)
      ? `收到。我已经在 RevNest 环境里启动 Dream Inn 全房型酒店定价流程：${run.runId}。我会读取 PMS 当前价、市场信号、策略记忆和 guardrails，并把 live PMS 写入保留给 WebApp 人工审批。`
      : `Got it. I started the Dream Inn all-room-types hotel pricing workflow in the RevNest environment: ${run.runId}. I will read PMS prices, market signals, strategy memory, and guardrails, while keeping live PMS writes behind WebApp human approval.`,
  };
}

export function normalizeDiscordText(value) {
  return String(value || "").replace(/<@!?\d+>/g, "").trim();
}

export async function handleDiscordRevyMessage({ text, guildId, channelId, userId, username } = {}) {
  const cleanText = normalizeDiscordText(text);
  const account = await resolveDiscordAccount({ guildId, channelId, userId });
  if (!account) {
    return {
      action: "account_not_mapped",
      reply: "I received the Discord message, but this Discord guild/channel is not mapped to a RevNest account. Set REVNEST_DISCORD_ACCOUNT_ID or add guildId/channelId to the Discord account_channel row.",
    };
  }

  const type = await accountType(account.accountId);
  if (!cleanText || /^(help|帮助|菜单)$/i.test(cleanText)) {
    return { action: "help", accountId: account.accountId, accountSource: account.source, reply: helpReply(cleanText) };
  }
  if (isIdentityQuestion(cleanText)) {
    return { action: "identity", accountId: account.accountId, accountSource: account.source, reply: revyIdentityReply(cleanText, type) };
  }
  if (isStatusQuestion(cleanText)) {
    return { action: "status", accountId: account.accountId, accountSource: account.source, reply: await hotelStatusReply(account.accountId, cleanText) };
  }
  if (isHotelPricingRequest(cleanText)) {
    const result = await startHotelPricingRun({ accountId: account.accountId, channelId, text: cleanText });
    return { ...result, accountId: account.accountId, accountSource: account.source };
  }

  return {
    action: "clarify",
    accountId: account.accountId,
    accountSource: account.source,
    reply: prefersChinese(cleanText)
      ? `我收到你的消息了${username ? `，${username}` : ""}。我是 Revy。现在 Discord 入站已经连接到 RevNest 环境；你可以问“你是谁”、问“状态”，或者发 “run hotel pricing” 启动酒店定价。`
      : `I received your message${username ? `, ${username}` : ""}. I am Revy, and this Discord inbound route is connected to the RevNest environment. Ask who I am, ask for status, or send \`run hotel pricing\` to start the hotel workflow.`,
  };
}
