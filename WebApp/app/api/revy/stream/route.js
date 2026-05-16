import { getRevyData } from "@/lib/revyData";
import { getRevyThinkingStatus } from "../status/route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const encoder = new TextEncoder();
const POLL_MS = 1800;

async function buildPayload(accountId, propertyId) {
  const [revyData, status] = await Promise.all([
    getRevyData({ accountId, propertyId }),
    getRevyThinkingStatus(accountId),
  ]);
  return {
    ...revyData,
    status,
    streamUpdatedAt: new Date().toISOString(),
  };
}

function writeSse(controller, event, payload) {
  controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
}

export async function GET(request) {
  const accountId = request.nextUrl.searchParams.get("accountId");
  const propertyId = request.nextUrl.searchParams.get("propertyId");

  if (!accountId) {
    return new Response("accountId is required", { status: 400 });
  }

  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      let lastSignature = "";
      let isPolling = false;
      let intervalId = null;

      const close = () => {
        closed = true;
        if (intervalId) clearInterval(intervalId);
        try {
          controller.close();
        } catch {
          // The connection may already be closed by the browser.
        }
      };

      const sendIfChanged = async (force = false) => {
        if (closed || isPolling) return;
        isPolling = true;
        try {
          const payload = await buildPayload(accountId, propertyId || null);
          const statusRevision = payload.status
            ? {
                isThinking: payload.status.isThinking,
                runId: payload.status.runId,
                propertyId: payload.status.propertyId,
                conversationId: payload.status.conversationId,
                status: payload.status.status,
              }
            : null;
          const signature = JSON.stringify({ revision: payload.revision, status: statusRevision });
          if (force || signature !== lastSignature) {
            lastSignature = signature;
            writeSse(controller, "revy", payload);
          }
        } catch (error) {
          writeSse(controller, "revy-error", { error: error.message || "Failed to stream Revy data" });
        } finally {
          isPolling = false;
        }
      };

      request.signal.addEventListener("abort", close, { once: true });
      await sendIfChanged(true);
      intervalId = setInterval(() => {
        sendIfChanged(false);
      }, POLL_MS);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
