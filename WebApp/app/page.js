"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  TextField,
} from "@mui/material";
import RevyAgentPriceChart from "../components/RevyAgentPriceChart";
import RevyHistoryPanel from "../components/RevyHistoryPanel";
import RevyWorkspacePanel from "../components/RevyWorkspacePanel";
import DemandSignalCard from "../components/DemandSignalCard";
import {
  StepIcon,
  ArrowRightIcon,
  PlusIcon,
  UserIcon,
} from "../components/AgentIcons";
import { getReasoningTraceForProperty } from "../lib/reasoningTrace";

const initialPendingTasks = [];
const initialPriceLogs = [];

const zipCodeOptions = [
  { zipCode: "95060", location: "Santa Cruz, CA" },
  { zipCode: "95010", location: "Capitola, CA" },
  { zipCode: "95113", location: "San Jose, CA" },
  { zipCode: "93721", location: "Fresno, CA" },
  { zipCode: "94103", location: "San Francisco, CA" },
  { zipCode: "90012", location: "Los Angeles, CA" },
  { zipCode: "92101", location: "San Diego, CA" },
  { zipCode: "98101", location: "Seattle, WA" },
  { zipCode: "78701", location: "Austin, TX" },
  { zipCode: "10001", location: "New York, NY" },
  { zipCode: "60601", location: "Chicago, IL" },
];

const usZipPattern = /^\d{5}(-\d{4})?$/;

const planLengthOptions = [
  "1 week",
  "1 month",
  "3 months",
  "6 months",
  "1 year",
  "2 years",
];

const planLengthDays = {
  "1 week": 7,
  "1 month": 30,
  "3 months": 90,
  "6 months": 180,
  "1 year": 365,
  "2 years": 730,
};

const availableChannels = [
  {
    id: "discord",
    name: "Discord",
    support: "Very well supported right now.",
    detail: "Use Discord for mobile approvals, price alerts, and agent follow-up questions.",
  },
  {
    id: "slack",
    name: "Slack",
    support: "Supported with Socket Mode.",
    detail: "Route agent tasks into team channels and approve pricing updates from Slack.",
  },
  {
    id: "telegram",
    name: "Telegram",
    support: "Simplest way to get started.",
    detail: "Register a bot with @BotFather, connect the token, and start handling alerts.",
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    support: "Works with your own number.",
    detail: "Recommended setup is a separate phone plus eSIM for business messaging.",
  },
];

function pendingTaskClassification(task) {
  const rawType = String(task?.type || "").toLowerCase();
  const classification =
    task?.taskType ||
    task?.classification ||
    (rawType.includes("adjustment required")
      ? "price_adjustment_required"
      : rawType.includes("review recommended")
        ? "price_review_recommended"
        : "price_review_recommended");
  if (classification === "price_adjustment_required") {
    return {
      label: task?.taskTypeLabel || task?.classificationLabel || "Price adjustment required",
      approvalLabel: task?.approvalGateLabel || "Approval required",
      description:
        task?.taskTypeDescription ||
        task?.classificationDescription ||
        "Current MockHotel PMS price is outside Revy's strategy range. A human must approve before any live PMS sync.",
      className: "required",
    };
  }
  return {
    label: task?.taskTypeLabel || task?.classificationLabel || "Price review recommended",
    approvalLabel: task?.approvalGateLabel || "Review recommended",
    description:
      task?.taskTypeDescription ||
      task?.classificationDescription ||
      "Current MockHotel PMS price is inside Revy's strategy range, but the agent found a material delta, low confidence, or guardrail issue.",
    className: "recommended",
  };
}

function pendingTaskPriceDirection(task) {
  const direction = task?.priceDirection || task?.changeType || task?.price_direction || task?.type;
  if (direction === "Increase" || direction === "Decrease") {
    return direction;
  }
  return Number.parseFloat(String(task?.change || "").replace("%", "")) >= 0 ? "Increase" : "Decrease";
}

function formatTaskStrategyRange(task) {
  const range = task?.strategyRange;
  const low = Number(range?.low);
  const high = Number(range?.high);
  if (Number.isFinite(low) && Number.isFinite(high)) {
    return `$${Math.round(low)} - $${Math.round(high)}`;
  }
  if (Number.isFinite(low)) {
    return `Above $${Math.round(low)}`;
  }
  if (Number.isFinite(high)) {
    return `Below $${Math.round(high)}`;
  }
  return "Unavailable";
}

const motelProperties = [];

const demoAccounts = [
  {
    email: "airbnb@revnest.ai",
    password: "demo",
    name: "Airbnb Host",
    accountType: "airbnb",
    properties: [],
  },
  {
    email: "hotel@revnest.ai",
    password: "demo",
    name: "Hotel Operator",
    accountType: "hotel",
    properties: motelProperties,
  },
];

const defaultHotelHomeDashboard = {
  demandSignals: {
    weather: {},
    events: {},
    competitor: {},
    occupancy: {},
  },
};

const defaultRevyThinkingStatus = {
  isThinking: false,
  runId: null,
  propertyId: null,
  conversationId: null,
  status: "idle",
  error: "",
  startedAt: null,
  updatedAt: null,
  modelRouting: null,
  finalReasoningVerification: null,
  pricingReasoningSteps: [],
};

const defaultRevyState = {
  status: "idle",
  model: "qwen tool calls + Nemotron reasoning",
  headline: "Reviewing current pricing signals and waiting for the next host question.",
  updatedAt: "May 15, 2026 7:20 PM",
  events: [],
  messages: [
    {
      role: "agent",
      text: "I am watching your pricing context and ready to explain the next recommendation.",
      at: "May 15, 2026 7:20 PM",
    },
  ],
};

const displayableRevyRunStatuses = new Set(["running", "completed", "failed", "stopped"]);
const terminalRevyThinkingStatuses = new Set(["completed", "failed", "stopped", "idle"]);

function revyStateHasDisplayableRun(state) {
  return Boolean(state?.runId || state?.activeRunId || displayableRevyRunStatuses.has(state?.status));
}

function isLiveRevyThinkingStatus(status) {
  return Boolean(status?.isThinking) && !terminalRevyThinkingStatuses.has(status?.status || "idle");
}

function normalizeRevyThinkingStatus(status) {
  const next = { ...defaultRevyThinkingStatus, ...(status || {}) };
  if (!isLiveRevyThinkingStatus(next)) {
    next.isThinking = false;
  }
  return next;
}

function normalizeRevyStateForDisplay(state) {
  if (revyStateHasDisplayableRun(state)) {
    return state;
  }
  return {
    ...state,
    status: state?.status === "thinking" ? "idle" : state?.status || "idle",
    events: [],
  };
}

function runFailureReason(run) {
  return run?.error || [...(run?.events || [])].reverse().find((event) => event.error)?.error || "";
}

function runFailureHeadline(reason) {
  const detail = reason || "the pricing workflow exited before completing.";
  return `Revy hit an issue: ${detail} Please try Run Revy again.`;
}

const emptyPropertyForm = {
  name: "",
  propertyType: "Airbnb",
  roomCount: "1",
  zipCode: "",
  location: "",
  streetAddress: "",
  minGuests: "1",
  maxGuests: "2",
  bathroom: "Private",
  planDays: "90",
  beds: "",
  bedSize: "",
  fridge: false,
  washer: false,
  dryer: false,
  parking: false,
  microwave: false,
  minPrice: "",
  maxPrice: "",
  pricingConnection: "manual",
  additionalInfo: "",
  importFromAirbnb: false,
};

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20h4.6L19.3 9.3a2.1 2.1 0 0 0 0-3L17.7 4.7a2.1 2.1 0 0 0-3 0L4 15.4V20Zm2-2v-1.8L16.2 6 18 7.8 7.8 18H6Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 21a2 2 0 0 1-2-2V8H5V6h4V4h6v2h4v2h-1v11a2 2 0 0 1-2 2H8Zm0-13v11h8V8H8Zm3 2h2v7h-2v-7Z" />
    </svg>
  );
}

async function readJsonResponse(response, fallbackMessage) {
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(`${fallbackMessage} The server returned a non-JSON response (${response.status}).`);
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || fallbackMessage);
  }
  return payload;
}

function isTransientFetchError(error) {
  const message = String(error?.message || "").toLowerCase();
  const name = String(error?.name || "").toLowerCase();
  return (
    name === "aborterror" ||
    message.includes("failed to fetch") ||
    message.includes("fetch failed") ||
    message.includes("networkerror") ||
    message.includes("network request failed") ||
    (name === "typeerror" && message.includes("fetch"))
  );
}

function logNonTransientFetchError(label, error) {
  if (isTransientFetchError(error)) return;
  console.error(label, error);
}

const connectionTimeFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function formatConnectionTime(date = new Date()) {
  return connectionTimeFormatter.format(date);
}

function safeConversationPart(value) {
  return String(value || "property").replace(/[^a-zA-Z0-9._-]/g, "-").slice(0, 80) || "property";
}

function createRevyConversationId(propertyId) {
  return `revy-${safeConversationPart(propertyId)}-${Date.now()}`;
}

function parsePriceBounds(property) {
  const prices = String(property?.priceRange || "")
    .match(/\$\d+/g)
    ?.map((value) => Number(value.replace("$", "")))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (prices?.length >= 2 && prices[1] > prices[0]) {
    return { minPrice: prices[0], maxPrice: prices[1] };
  }

  const basePrice = Number(property?.fixedPrice || property?.agentAdr || 100);
  return {
    minPrice: Math.max(1, Math.round(basePrice * 0.75)),
    maxPrice: Math.max(2, Math.round(basePrice * 1.55)),
  };
}

export default function Home() {
  const router = useRouter();
  const [isAuthed, setIsAuthed] = useState(false);
  const [activeView, setActiveView] = useState("home");
  const [isPropertyDialogOpen, setIsPropertyDialogOpen] = useState(false);
  const [isExternalConnectionDialogOpen, setIsExternalConnectionDialogOpen] = useState(false);
  const [isChannelConnectionDialogOpen, setIsChannelConnectionDialogOpen] = useState(false);
  const [selectedPendingTask, setSelectedPendingTask] = useState(null);
  const [selectedPriceLog, setSelectedPriceLog] = useState(null);
  const [propertyDeleteTarget, setPropertyDeleteTarget] = useState(null);
  const [isDeletingProperty, setIsDeletingProperty] = useState(false);
  const [propertyDeleteError, setPropertyDeleteError] = useState("");
  const [editingPropertyId, setEditingPropertyId] = useState(null);
  const [propertyDialogMode, setPropertyDialogMode] = useState("add");
  const [activeAccount, setActiveAccount] = useState(demoAccounts[0]);
  const [email, setEmail] = useState(demoAccounts[0].email);
  const [password, setPassword] = useState("demo");
  const [loginError, setLoginError] = useState("");
  const [zipCodeError, setZipCodeError] = useState("");
  const [isZipMenuOpen, setIsZipMenuOpen] = useState(false);
  const [isPlanMenuOpen, setIsPlanMenuOpen] = useState(false);
  const [pendingTaskAction, setPendingTaskAction] = useState("apply");
  const [pendingFinalPrice, setPendingFinalPrice] = useState("");
  const [pendingFeedback, setPendingFeedback] = useState("");
  const [pendingTaskRecords, setPendingTaskRecords] = useState(initialPendingTasks);
  const [priceLogRecords, setPriceLogRecords] = useState(initialPriceLogs);
  const [hotelHomeDashboard, setHotelHomeDashboard] = useState(defaultHotelHomeDashboard);
  const [isPendingTasksExpanded, setIsPendingTasksExpanded] = useState(false);
  const [isPriceLogExpanded, setIsPriceLogExpanded] = useState(false);
  const [isAcceptingAllTasks, setIsAcceptingAllTasks] = useState(false);
  const [isStartingHotelRevy, setIsStartingHotelRevy] = useState(false);
  const [dashboardActionError, setDashboardActionError] = useState("");
  const [properties, setProperties] = useState(demoAccounts[0].properties);
  const [externalAccounts, setExternalAccounts] = useState([]);
  const [connectedChannels, setConnectedChannels] = useState([]);
  const [connectionError, setConnectionError] = useState("");
  const [selectedPropertyId, setSelectedPropertyId] = useState("");
  const [propertyForm, setPropertyForm] = useState(emptyPropertyForm);
  const [chatInput, setChatInput] = useState("");
  const [, setChatMessages] = useState([
    {
      role: "agent",
      text: "Hi, I am your RevNest pricing assistant. Pick a property above and I will explain its current pricing decision.",
    },
  ]);
  const [chatPropertyId, setChatPropertyId] = useState("");
  const [revyState, setRevyState] = useState(defaultRevyState);
  const [revyConversations, setRevyConversations] = useState([]);
  const [selectedRevyConversationId, setSelectedRevyConversationId] = useState("");
  const [selectedPricePoint, setSelectedPricePoint] = useState(null);
  const [pricePointConversations, setPricePointConversations] = useState([]);
  const [isPricePointHistoryLoading, setIsPricePointHistoryLoading] = useState(false);
  const [pricePointError, setPricePointError] = useState("");
  const [isStartingRevy, setIsStartingRevy] = useState(false);
  const [activeRevyRunId, setActiveRevyRunId] = useState("");
  const [revyThinkingStatus, setRevyThinkingStatus] = useState(defaultRevyThinkingStatus);
  const [isStoppingRevy, setIsStoppingRevy] = useState(false);
  const [revyStreamStatus, setRevyStreamStatus] = useState("idle");
  const [queuedRevySteer, setQueuedRevySteer] = useState(null);

  const selectedProperty = properties.find((property) => property.id === selectedPropertyId) ?? properties[0] ?? null;
  const isHotelAccount = activeAccount?.accountType === "hotel";
  const displayedPendingTasks = isPendingTasksExpanded ? pendingTaskRecords : pendingTaskRecords.slice(0, 3);
  const displayedPriceLogs = isPriceLogExpanded ? priceLogRecords : priceLogRecords.slice(0, 3);
  const revyEvents = Array.isArray(revyState.events) ? revyState.events : [];
  const isRevyThinking = Boolean(activeRevyRunId) || isLiveRevyThinkingStatus(revyThinkingStatus);
  const activeRevyConversation = revyConversations.find((conversation) => [conversation.id, conversation.conversationId].includes(selectedRevyConversationId)) || revyConversations[0] || null;
  const chatProperty = useMemo(() => {
    if (!chatPropertyId) return null;
    return properties.find((property) => property.id === chatPropertyId) || null;
  }, [chatPropertyId, properties]);
  const demandSignals = {
    ...defaultHotelHomeDashboard.demandSignals,
    ...(hotelHomeDashboard.demandSignals || {}),
  };

  function resolvePlanLength(value) {
    const normalizedValue = value.trim().toLowerCase();

    if (planLengthDays[normalizedValue]) {
      return normalizedValue;
    }

    const numericDays = Number(normalizedValue.replace(/[^0-9]/g, ""));
    if (!Number.isNaN(numericDays) && numericDays > 0) {
      return `${Math.min(numericDays, 730)} days`;
    }

    return "90 days";
  }

  const loadDashboard = useCallback(async (accountId) => {
    const response = await fetch(`/api/dashboard?accountId=${encodeURIComponent(accountId)}`);
    const payload = await readJsonResponse(response, "Failed to load dashboard data.");

    setProperties(payload.properties);
    setPendingTaskRecords(payload.pendingTasks);
    setPriceLogRecords(payload.priceLogs);
    setHotelHomeDashboard(payload.hotelHomeDashboard || defaultHotelHomeDashboard);

    return payload.properties;
  }, []);

  const loadAccountConnections = useCallback(async (accountId) => {
    const response = await fetch(`/api/account-connections?accountId=${encodeURIComponent(accountId)}`);
    const payload = await readJsonResponse(response, "Failed to load account connections.");

    setExternalAccounts(payload.externalAccounts || []);
    setConnectedChannels(payload.connectedChannels || []);
    setConnectionError("");

    return payload;
  }, []);

  const applyRevyPayload = useCallback((payload) => {
    const nextState = payload.state || defaultRevyState;
    const conversations = payload.conversations || [];

    setRevyState((current) => {
      if (revyStateHasDisplayableRun(current) && !revyStateHasDisplayableRun(nextState)) {
        return current;
      }
      return normalizeRevyStateForDisplay(nextState);
    });
    setRevyConversations(conversations);
    setSelectedRevyConversationId((current) => {
      if (current && conversations.some((conversation) => [conversation.id, conversation.conversationId].includes(current))) {
        return current;
      }
      return conversations[0]?.conversationId || conversations[0]?.id || "";
    });
    if (payload.status) {
      const nextStatus = normalizeRevyThinkingStatus(payload.status);
      setRevyThinkingStatus(nextStatus);
      setActiveRevyRunId((current) => {
        if (isLiveRevyThinkingStatus(nextStatus)) return nextStatus.runId || current || "";
        if (current && nextStatus.status === "idle") return current;
        return "";
      });
    }
    setChatMessages(Array.isArray(nextState.messages) && nextState.messages.length > 0 ? nextState.messages : defaultRevyState.messages);
  }, []);

  const loadRevyData = useCallback(async (accountId) => {
    try {
      const response = await fetch(`/api/revy?accountId=${encodeURIComponent(accountId)}`, { cache: "no-store" });
      const payload = await readJsonResponse(response, "Failed to load Revy data.");
      applyRevyPayload(payload);
      return payload;
    } catch (error) {
      if (isTransientFetchError(error)) return null;
      throw error;
    }
  }, [applyRevyPayload]);

  const loadRevyStatus = useCallback(async (accountId) => {
    if (!accountId) {
      setRevyThinkingStatus(defaultRevyThinkingStatus);
      return defaultRevyThinkingStatus;
    }
    try {
      const response = await fetch(`/api/revy/status?accountId=${encodeURIComponent(accountId)}`, { cache: "no-store" });
      const payload = await readJsonResponse(response, "Failed to load Revy status.");
      const nextStatus = normalizeRevyThinkingStatus(payload);
      setRevyThinkingStatus(nextStatus);
      setActiveRevyRunId((current) => {
        if (isLiveRevyThinkingStatus(nextStatus)) return nextStatus.runId || current || "";
        if (current && nextStatus.status === "idle") return current;
        return "";
      });
      return nextStatus;
    } catch (error) {
      if (isTransientFetchError(error)) return null;
      throw error;
    }
  }, []);

  async function loadRevyConversationsForProperty(propertyId) {
    if (!activeAccount?.id || !propertyId) return [];
    const response = await fetch(
      `/api/revy?accountId=${encodeURIComponent(activeAccount.id)}&propertyId=${encodeURIComponent(propertyId)}`,
    );
    const payload = await readJsonResponse(response, "Failed to load Revy room history.");
    return payload.conversations || [];
  }

  const startRevyRunForMessage = useCallback(async ({ message, property = chatProperty, conversationId = null }) => {
    if (!activeAccount?.id || !property) {
      throw new Error("Pick a property before asking Revy.");
    }

    const resolvedConversationId =
      conversationId ||
      selectedRevyConversationId ||
      activeRevyConversation?.conversationId ||
      createRevyConversationId(property.id);
    const { minPrice, maxPrice } = parsePriceBounds(property);
    const pricingHorizon = Math.max(property.forecast?.length || 0, 7);

    setIsStartingRevy(true);
    setPricePointError("");
    setSelectedRevyConversationId(resolvedConversationId);

    try {
      const response = await fetch("/api/agent-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accountId: activeAccount.id,
          propertyId: property.id,
          propertyType: property.propertyType,
          myPlace: property.myPlace || property.airbnbUrl || null,
          minPrice,
          maxPrice,
          pricingHorizon,
          conversationId: resolvedConversationId,
          supplementalInfo: `Host follow-up for Revy conversation ${resolvedConversationId}: ${message}`,
        }),
      });
      const payload = await readJsonResponse(response, "Failed to start Revy for this question.");
      const startedAt = payload.startedAt || new Date().toISOString();
      const nextConversationId = payload.conversationId || resolvedConversationId;

      setActiveRevyRunId(payload.runId);
      setChatPropertyId(property.id);
      setSelectedRevyConversationId(nextConversationId);
      setRevyThinkingStatus({
        isThinking: true,
        runId: payload.runId,
        propertyId: property.id,
        conversationId: nextConversationId,
        status: "running",
        error: "",
        startedAt,
        modelRouting: payload.modelRouting || null,
        finalReasoningVerification: null,
        pricingReasoningSteps: [],
        updatedAt: new Date().toISOString(),
      });
      setRevyState((current) => ({
        ...current,
        status: "running",
        model: payload.modelRouting
          ? `${payload.modelRouting.toolModel} tools + ${payload.modelRouting.reasoningModel} reasoning`
          : current.model,
        headline: `Running Revy for ${property.name}.`,
        updatedAt: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
        events: [
          {
            timestamp: startedAt,
            stage: "context",
            tool: String(property.propertyType || "").toLowerCase().includes("hotel") ? "nemoclaw agent" : "openclaw agent",
            status: "started",
            message: `Started Revy conversation ${nextConversationId} for ${property.name}.`,
          },
        ],
      }));

      return payload;
    } finally {
      setIsStartingRevy(false);
    }
  }, [activeAccount?.id, activeRevyConversation?.conversationId, chatProperty, selectedRevyConversationId]);

  useEffect(() => {
    const storedSession = window.localStorage.getItem("revnestSession");
    if (!storedSession) return;
    let cancelled = false;
    try {
      const user = JSON.parse(storedSession);
      if (!user?.id) return;
      if (!user.accountType) {
        window.localStorage.removeItem("revnestSession");
        return;
      }
      queueMicrotask(() => {
        if (cancelled) return;
        setActiveAccount(user);
        setEmail(user.email);
        setIsAuthed(true);
        const requestedView = new URLSearchParams(window.location.search).get("view");
        if (requestedView === "channels") {
          setActiveView("account");
        } else if (["trace", "memory", "about", "console"].includes(requestedView)) {
          setActiveView("revy");
        } else if (["home", "properties", "revy", "account"].includes(requestedView)) {
          setActiveView(requestedView);
        }
        loadDashboard(user.id)
          .then((accountProperties) => {
            if (cancelled) return;
            setSelectedPropertyId(accountProperties[0]?.id ?? "");
            setChatPropertyId(accountProperties[0]?.id ?? "");
          })
          .catch((error) => {
            console.error("Failed to restore dashboard session", error);
          });
        loadAccountConnections(user.id).catch((error) => {
          if (!cancelled) setConnectionError(error.message);
          console.error("Failed to restore account connections", error);
        });
        loadRevyData(user.id).catch((error) => {
          logNonTransientFetchError("Failed to restore Revy data", error);
        });
        loadRevyStatus(user.id).catch((error) => {
          logNonTransientFetchError("Failed to restore Revy status", error);
        });
      });
    } catch {
      window.localStorage.removeItem("revnestSession");
    }
    return () => {
      cancelled = true;
    };
  }, [loadAccountConnections, loadDashboard, loadRevyData, loadRevyStatus]);

  useEffect(() => {
    if (!isAuthed || !activeAccount?.id) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      loadDashboard(activeAccount.id).catch((error) => {
        console.error("Failed to refresh dashboard data", error);
      });
      if (revyStreamStatus !== "connected") {
        loadRevyStatus(activeAccount.id).catch((error) => {
          logNonTransientFetchError("Failed to refresh Revy status", error);
        });
        loadRevyData(activeAccount.id).catch((error) => {
          logNonTransientFetchError("Failed to refresh Revy data", error);
        });
      }
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [activeAccount?.id, isAuthed, loadDashboard, loadRevyData, loadRevyStatus, revyStreamStatus]);

  useEffect(() => {
    if (!isAuthed || !activeAccount?.id) {
      setRevyStreamStatus("idle");
      return undefined;
    }
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      setRevyStreamStatus("fallback");
      return undefined;
    }

    const source = new EventSource(`/api/revy/stream?accountId=${encodeURIComponent(activeAccount.id)}`);
    let didFallback = false;
    setRevyStreamStatus("connecting");

    source.addEventListener("revy", (event) => {
      try {
        const payload = JSON.parse(event.data);
        applyRevyPayload(payload);
        setRevyStreamStatus("connected");
        didFallback = false;
      } catch (error) {
        console.error("Failed to parse Revy stream payload", error);
      }
    });

    source.addEventListener("revy-error", (event) => {
      console.error("Revy stream error", event.data);
      setRevyStreamStatus("fallback");
    });

    source.onerror = () => {
      setRevyStreamStatus("fallback");
      if (!didFallback) {
        didFallback = true;
        loadRevyData(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to fallback-load Revy data", error));
        loadRevyStatus(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to fallback-load Revy status", error));
      }
    };

    return () => {
      source.close();
    };
  }, [activeAccount?.id, applyRevyPayload, isAuthed, loadRevyData, loadRevyStatus]);

  useEffect(() => {
    if (!selectedPricePoint?.property?.id) return;
    setPricePointConversations(revyConversations.filter((conversation) => conversation.propertyId === selectedPricePoint.property.id));
  }, [revyConversations, selectedPricePoint?.property?.id]);

  useEffect(() => {
    if (!activeRevyRunId) return undefined;

    let cancelled = false;
    async function pollRevyRun() {
      try {
        const response = await fetch(`/api/agent-runs/${encodeURIComponent(activeRevyRunId)}`);
        const payload = await readJsonResponse(response, "Failed to load Revy run progress.");
        if (cancelled) return;
        const failureReason = runFailureReason(payload);
        setRevyState((current) => ({
          ...current,
          status: payload.status || current.status,
          model: payload.modelRouting
            ? `${payload.modelRouting.toolModel} tools + ${payload.modelRouting.reasoningModel} reasoning`
            : current.model,
          headline:
            payload.status === "completed"
              ? "Revy finished the latest room pricing run."
              : payload.status === "failed"
                ? runFailureHeadline(failureReason)
                : current.headline,
          updatedAt: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
          events: payload.events || current.events || [],
        }));
        if (["completed", "failed", "stopped"].includes(payload.status)) {
          setActiveRevyRunId("");
          setRevyThinkingStatus((current) => ({
            ...current,
            isThinking: false,
            runId: null,
            status: payload.status || current.status,
            error: payload.error || failureReason || current.error || "",
            modelRouting: payload.modelRouting || current.modelRouting || null,
            finalReasoningVerification: payload.finalReasoningVerification || current.finalReasoningVerification || null,
            pricingReasoningSteps: payload.pricingReasoningSteps || current.pricingReasoningSteps || [],
            updatedAt: new Date().toISOString(),
          }));
          if (activeAccount?.id) {
            loadRevyStatus(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to refresh Revy status", error));
            loadRevyData(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to refresh Revy conversations", error));
          }
        } else if (payload.status === "running") {
          setRevyThinkingStatus((current) => ({
            ...current,
            isThinking: true,
            runId: payload.runId || activeRevyRunId,
            propertyId: payload.propertyId || current.propertyId,
            status: "running",
            error: payload.error || "",
            startedAt: payload.startedAt || current.startedAt,
            modelRouting: payload.modelRouting || current.modelRouting || null,
            finalReasoningVerification: payload.finalReasoningVerification || current.finalReasoningVerification || null,
            pricingReasoningSteps: payload.pricingReasoningSteps || current.pricingReasoningSteps || [],
            updatedAt: new Date().toISOString(),
          }));
        }
      } catch (error) {
        if (!cancelled) setPricePointError(error.message);
      }
    }

    pollRevyRun();
    const intervalId = window.setInterval(pollRevyRun, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeAccount?.id, activeRevyRunId, loadRevyData, loadRevyStatus]);

  useEffect(() => {
    if (!queuedRevySteer || isRevyThinking || activeRevyRunId || isStartingRevy) return undefined;

    let cancelled = false;
    async function runQueuedSteer() {
      const property = properties.find((item) => item.id === queuedRevySteer.propertyId) || chatProperty;
      if (!property) return;
      const queued = queuedRevySteer;
      setQueuedRevySteer(null);
      setChatMessages((current) => [
        ...current,
        { role: "agent", text: `Starting queued Revy steer for ${property.name}.` },
      ]);
      try {
        await startRevyRunForMessage({
          message: queued.text,
          property,
          conversationId: queued.conversationId,
        });
      } catch (error) {
        if (!cancelled) {
          setPricePointError(error.message);
          setChatMessages((current) => [...current, { role: "agent", text: error.message }]);
        }
      }
    }

    runQueuedSteer();
    return () => {
      cancelled = true;
    };
  }, [activeRevyRunId, chatProperty, isRevyThinking, isStartingRevy, properties, queuedRevySteer, startRevyRunForMessage]);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoginError("");

    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    let payload = {};
    try {
      payload = await readJsonResponse(response, "Use one of the demo accounts below. Password is demo.");
    } catch (error) {
      setLoginError(error.message);
      return;
    }

    let accountProperties = [];
    try {
      accountProperties = await loadDashboard(payload.user.id);
    } catch (error) {
      setLoginError(error.message);
      return;
    }
    try {
      await loadAccountConnections(payload.user.id);
    } catch (error) {
      setConnectionError(error.message);
    }
    try {
      await loadRevyData(payload.user.id);
    } catch (error) {
      logNonTransientFetchError("Failed to load Revy data", error);
    }
    try {
      await loadRevyStatus(payload.user.id);
    } catch (error) {
      logNonTransientFetchError("Failed to load Revy status", error);
    }

    setActiveAccount(payload.user);
    setEmail(payload.user.email);
    window.localStorage.setItem("revnestSession", JSON.stringify(payload.user));
    setSelectedPropertyId(accountProperties[0]?.id ?? "");
    setChatPropertyId(accountProperties[0]?.id ?? "");
    setActiveView("home");
    setIsAuthed(true);
  }

  function handleLogout() {
    fetch("/api/logout", { method: "POST" }).catch(() => {});
    window.localStorage.removeItem("revnestSession");
    window.localStorage.removeItem("revnestWizardDraft");
    setIsAuthed(false);
    setActiveView("home");
    setChatPropertyId("");
    setExternalAccounts([]);
    setConnectedChannels([]);
    setConnectionError("");
    setDashboardActionError("");
    setRevyState(defaultRevyState);
    setRevyThinkingStatus(defaultRevyThinkingStatus);
    setActiveRevyRunId("");
    setRevyConversations([]);
    setSelectedRevyConversationId("");
    setChatMessages([
      {
        role: "agent",
        text: "Hi, I am your RevNest pricing assistant. Pick a property above and I will explain its current pricing decision.",
      },
    ]);
  }

  function buildChatReply(message) {
    if (properties.length === 0) {
      return "I do not see any properties in this account yet. Add a property first, then I can explain its pricing decision.";
    }
    if (!chatProperty) {
      return "Pick a property in the dropdown above and I will explain its current pricing decision step by step.";
    }
    const propertyTrace = getReasoningTraceForProperty(chatProperty.id);
    const final = propertyTrace.summary.final_price;
    const old = chatProperty.fixedPrice ?? propertyTrace.summary.old_price;
    const change = propertyTrace.summary.change_pct;
    return `For ${chatProperty.name}, I moved the rate from $${old} to $${final} (${change > 0 ? "+" : ""}${change}%). The driver was: ${propertyTrace.summary.why} Ask "open full trace" to inspect every tool call.`;
  }

  async function stopRevyThinking() {
    if (!activeAccount?.id || isStoppingRevy) return;
    setIsStoppingRevy(true);
    try {
      const response = await fetch("/api/revy/stop-thinking", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accountId: activeAccount.id, runId: revyThinkingStatus.runId || activeRevyRunId || undefined }),
      });
      const payload = await readJsonResponse(response, "Failed to stop Revy thinking.");
      const nextStatus = normalizeRevyThinkingStatus(payload.status || payload);
      setRevyThinkingStatus(nextStatus);
      setActiveRevyRunId("");
      setQueuedRevySteer(null);
      setRevyState((current) => ({
        ...current,
        status: "stopped",
        headline: "Revy stopped the current room pricing run.",
        updatedAt: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
      }));
      await loadDashboard(activeAccount.id);
    } catch (error) {
      setPricePointError(error.message);
    } finally {
      setIsStoppingRevy(false);
    }
  }

  async function handleChatSubmit(event) {
    event.preventDefault();
    const message = chatInput.trim();
    if (isRevyThinking) {
      if (message) {
        const property = chatProperty || (revyThinkingStatus.propertyId ? properties.find((item) => item.id === revyThinkingStatus.propertyId) : null);
        setQueuedRevySteer({
          text: message,
          propertyId: property?.id || revyThinkingStatus.propertyId || "",
          conversationId: revyThinkingStatus.conversationId || selectedRevyConversationId || activeRevyConversation?.conversationId || "",
          queuedAt: new Date().toISOString(),
        });
        setChatMessages((current) => [
          ...current,
          { role: "user", text: message },
          { role: "agent", text: "Queued. I will use this as the next Revy instruction when the current run frees up." },
        ]);
        setChatInput("");
        return;
      }
      await stopRevyThinking();
      return;
    }
    if (!message) return;

    const lower = message.toLowerCase();
    if (chatProperty && (lower.includes("trace") || lower.includes("steps"))) {
      setChatMessages((current) => [
        ...current,
        { role: "user", text: message },
        { role: "agent", text: `Opening Revy reasoning for ${chatProperty.name}.` },
      ]);
      setChatInput("");
      setSelectedPropertyId(chatProperty.id);
      setActiveView("properties");
      return;
    }

    if (!activeAccount?.id || !chatProperty) {
      setChatMessages((current) => [
        ...current,
        { role: "user", text: message },
        { role: "agent", text: buildChatReply(message) },
      ]);
      setChatInput("");
      return;
    }

    const conversationId = selectedRevyConversationId || activeRevyConversation?.conversationId || createRevyConversationId(chatProperty.id);

    setChatMessages((current) => [
      ...current,
      { role: "user", text: message },
      { role: "agent", text: `Starting Revy with conversation ${conversationId}.` },
    ]);
    setChatInput("");

    try {
      await startRevyRunForMessage({
        message,
        property: chatProperty,
        conversationId,
      });
    } catch (error) {
      setPricePointError(error.message);
      setChatMessages((current) => [...current, { role: "agent", text: error.message }]);
    }
  }

  async function openPricePointDialog(point, index) {
    if (!selectedProperty) return;

    setSelectedPricePoint({ property: selectedProperty, point, index });
    setPricePointConversations([]);
    setPricePointError("");
    setIsPricePointHistoryLoading(true);
    try {
      const conversations = await loadRevyConversationsForProperty(selectedProperty.id);
      setPricePointConversations(conversations);
    } catch (error) {
      setPricePointError(error.message);
    } finally {
      setIsPricePointHistoryLoading(false);
    }
  }

  function closePricePointDialog() {
    setSelectedPricePoint(null);
    setPricePointConversations([]);
    setPricePointError("");
    setIsPricePointHistoryLoading(false);
    setIsStartingRevy(false);
  }

  async function runHotelRevyBatch() {
    if (!activeAccount?.id || isRevyThinking || isStartingHotelRevy) return;

    setIsStartingHotelRevy(true);
    setDashboardActionError("");
    try {
      const response = await fetch("/api/agent-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accountId: activeAccount.id,
          propertyType: "hotel",
          hotelScope: "all-room-types",
          runtimeMode: "nemoclaw",
          supplementalInfo: "Hotel Home Run Revy requested for all hotel room types.",
        }),
      });
      const payload = await readJsonResponse(response, "Failed to start Revy for all hotel room types.");
      const startedAt = payload.startedAt || new Date().toISOString();
      const firstPropertyId = payload.propertyIds?.[0] || payload.propertyId || null;

      setActiveRevyRunId(payload.runId);
      setSelectedRevyConversationId(payload.conversationId || "");
      setRevyThinkingStatus({
        isThinking: true,
        runId: payload.runId,
        propertyId: firstPropertyId,
        conversationId: payload.conversationId || null,
        status: "running",
        error: "",
        startedAt,
        modelRouting: payload.modelRouting || null,
        finalReasoningVerification: null,
        pricingReasoningSteps: [],
        updatedAt: new Date().toISOString(),
      });
      setRevyState((current) => ({
        ...current,
        status: "running",
        model: payload.modelRouting
          ? `${payload.modelRouting.toolModel} tools + ${payload.modelRouting.reasoningModel} reasoning`
          : current.model,
        headline: "Running Revy for all hotel room types.",
        updatedAt: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
        events: [
          {
            timestamp: startedAt,
            stage: "context",
            tool: "nemoclaw agent",
            status: "started",
            message: `Started hotel all-room-types Revy run for ${payload.propertyIds?.length || 0} room types.`,
          },
        ],
      }));
      setActiveView("revy");
      loadDashboard(activeAccount.id).catch((error) => console.error("Failed to refresh dashboard after hotel Revy start", error));
      loadRevyStatus(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to refresh Revy status after hotel Revy start", error));
      loadRevyData(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to refresh Revy data after hotel Revy start", error));
    } catch (error) {
      setDashboardActionError(error.message);
    } finally {
      setIsStartingHotelRevy(false);
    }
  }

  async function runRevyForPricePoint() {
    if (!selectedPricePoint?.property || !activeAccount?.id) return;

    const property = selectedPricePoint.property;
    const { minPrice, maxPrice } = parsePriceBounds(property);
    const pricingHorizon = Math.max(property.forecast?.length || 0, 7);
    const conversationId = createRevyConversationId(property.id);

    setIsStartingRevy(true);
    setPricePointError("");
    try {
      const response = await fetch("/api/agent-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accountId: activeAccount.id,
          propertyId: property.id,
          propertyType: property.propertyType,
          myPlace: property.myPlace || property.airbnbUrl || null,
          minPrice,
          maxPrice,
          pricingHorizon,
          conversationId,
          supplementalInfo: `Run requested from My Properties price point for ${property.name} on ${selectedPricePoint.point?.day || "the selected date"}. Conversation id: ${conversationId}.`,
        }),
      });
      const payload = await readJsonResponse(response, "Failed to start Revy for this room.");
      const startedAt = payload.startedAt || new Date().toISOString();
      const nextConversationId = payload.conversationId || conversationId;
      setActiveRevyRunId(payload.runId);
      setSelectedRevyConversationId(nextConversationId);
      setChatPropertyId(property.id);
      setRevyThinkingStatus({
        isThinking: true,
        runId: payload.runId,
        propertyId: property.id,
        conversationId: nextConversationId,
        status: "running",
        error: "",
        startedAt,
        modelRouting: payload.modelRouting || null,
        finalReasoningVerification: null,
        updatedAt: new Date().toISOString(),
      });
      setRevyState((current) => ({
        ...current,
        status: "running",
        model: payload.modelRouting
          ? `${payload.modelRouting.toolModel} tools + ${payload.modelRouting.reasoningModel} reasoning`
          : current.model,
        headline: `Running Revy for ${property.name} on ${selectedPricePoint.point?.day || "the selected date"}.`,
        updatedAt: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
        events: [
          {
            timestamp: startedAt,
            stage: "context",
            tool: "agent-browser",
            status: "started",
            message: `Started Revy conversation ${nextConversationId} for ${property.name}.`,
          },
        ],
      }));
      setSelectedPricePoint(null);
      setActiveView("revy");
      loadDashboard(activeAccount.id).catch((error) => console.error("Failed to refresh dashboard after Revy start", error));
      loadRevyStatus(activeAccount.id).catch((error) => logNonTransientFetchError("Failed to refresh Revy status after start", error));
    } catch (error) {
      setPricePointError(error.message);
    } finally {
      setIsStartingRevy(false);
    }
  }

  function askRevyAboutPricePoint() {
    if (!selectedPricePoint?.property) return;
    const { property, point } = selectedPricePoint;
    const price = Number.isFinite(Number(point?.agent)) ? `${Math.round(Number(point.agent))}` : "this price";
    setChatPropertyId(property.id);
    setChatMessages([
      {
        role: "user",
        text: `Ask Revy About This Price: Why did you recommend ${price} for ${property.name} on ${point?.day || "this date"}?`,
      },
      {
        role: "agent",
        text: `I can explain the historical context, demand signals, and guardrails behind ${price} for ${property.name}.`,
      },
    ]);
    setSelectedPricePoint(null);
    setActiveView("revy");
  }

  function openPendingTaskDialog(task) {
    setSelectedPendingTask(task);
    setPendingTaskAction("apply");
    setPendingFinalPrice(task.agentSuggestedPrice.replace("$", ""));
    setPendingFeedback("");
  }

  function askAgentAboutPendingTask(task) {
    const matchingProperty = properties.find((property) => property.name === task.property);
    const classification = pendingTaskClassification(task);
    const priceDirection = pendingTaskPriceDirection(task).toLowerCase();
    setSelectedPendingTask(null);
    setChatPropertyId(matchingProperty?.id || chatPropertyId || properties[0]?.id || "");
    setChatMessages((current) => [
      ...current,
      {
        role: "agent",
        text: `I am ready to explain why this task is "${classification.label}" for ${task.property} on ${task.priceDate}. Ask me about the human approval gate, demand signals, guardrails, or why I suggested a ${priceDirection} to ${task.agentSuggestedPrice}.`,
      },
    ]);
    setActiveView("revy");
  }

  async function confirmPendingTask() {
    if (!selectedPendingTask) {
      return;
    }

    const finalPrice =
      pendingFinalPrice.trim().startsWith("$")
        ? pendingFinalPrice.trim()
        : `$${pendingFinalPrice.trim() || selectedPendingTask.agentSuggestedPrice.replace("$", "")}`;

    const response = await fetch("/api/pricing-records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        accountId: activeAccount.id,
        taskId: selectedPendingTask.id,
        action: pendingTaskAction,
        finalPrice,
        feedback: pendingFeedback,
      }),
    });
    let payload = {};
    try {
      payload = await readJsonResponse(response, "Failed to update this task.");
    } catch (error) {
      setPendingFeedback(error.message);
      return;
    }

    if (pendingTaskAction === "apply") {
      setPriceLogRecords((current) => [
        payload.log,
        ...current,
      ]);
    }

    setPendingTaskRecords((current) => current.filter((task) => task.id !== selectedPendingTask.id));
    setSelectedPendingTask(null);
    setPendingTaskAction("apply");
    setPendingFinalPrice("");
    setPendingFeedback("");
  }

  async function acceptAllPendingTasks() {
    if (!activeAccount?.id || pendingTaskRecords.length === 0) return;

    setIsAcceptingAllTasks(true);
    setDashboardActionError("");
    try {
      const response = await fetch("/api/pricing-records/accept-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accountId: activeAccount.id }),
      });
      const payload = await readJsonResponse(response, "Failed to accept pending tasks.");
      setPendingTaskRecords([]);
      setPriceLogRecords((current) => [...(payload.logs || []), ...current]);
      setIsPendingTasksExpanded(false);
      await loadDashboard(activeAccount.id);
    } catch (error) {
      setDashboardActionError(error.message);
    } finally {
      setIsAcceptingAllTasks(false);
    }
  }

  function openAddPropertyDialog() {
    setEditingPropertyId(null);
    setPropertyDialogMode("add");
    setPropertyForm(emptyPropertyForm);
    setZipCodeError("");
    setIsPropertyDialogOpen(true);
  }

  function openEditPropertyDialog(mode = "main") {
    if (!selectedProperty) {
      return;
    }

    setEditingPropertyId(selectedProperty.id);
    setPropertyDialogMode(mode);
    setPropertyForm({
      name: selectedProperty.name,
      propertyType: selectedProperty.propertyType,
      roomCount: String(selectedProperty.roomCount ?? 1),
      zipCode: selectedProperty.zipCode ?? "",
      location: selectedProperty.location,
      streetAddress: selectedProperty.streetAddress ?? "",
      minGuests: selectedProperty.guests.split("-")[0] || "1",
      maxGuests: selectedProperty.guests.match(/-(\d+)/)?.[1] || "2",
      bathroom: selectedProperty.bathroom,
      planDays: selectedProperty.planDuration || "90",
      beds: selectedProperty.beds.replace(" beds", "").replace(" bed", ""),
      bedSize: selectedProperty.bedSize,
      fridge: selectedProperty.amenities.includes("Fridge"),
      washer: selectedProperty.amenities.includes("Washer"),
      dryer: selectedProperty.amenities.includes("Dryer"),
      parking: selectedProperty.amenities.includes("Parking"),
      microwave: selectedProperty.amenities.includes("Microwave"),
      minPrice: selectedProperty.priceRange.match(/\$(\d+)/)?.[1] || "",
      maxPrice: selectedProperty.priceRange.match(/-\$(\d+)/)?.[1] || "",
      pricingConnection: selectedProperty.pricingConnection ?? "manual",
      additionalInfo: selectedProperty.additionalInfo ?? "",
      importFromAirbnb: Boolean(selectedProperty.importFromAirbnb),
    });
    setZipCodeError("");
    setIsPropertyDialogOpen(true);
  }

  async function handleDeleteProperty() {
    if (!propertyDeleteTarget || !activeAccount?.id) {
      return;
    }

    setIsDeletingProperty(true);
    setPropertyDeleteError("");
    try {
      const response = await fetch(
        `/api/properties/${encodeURIComponent(propertyDeleteTarget.id)}?accountId=${encodeURIComponent(activeAccount.id)}`,
        { method: "DELETE" }
      );
      await readJsonResponse(response, "Failed to delete property.");

      const nextProperties = properties.filter((property) => property.id !== propertyDeleteTarget.id);
      const nextSelectedId = nextProperties[0]?.id ?? "";
      setProperties(nextProperties);
      setSelectedPropertyId(nextSelectedId);
      setChatPropertyId((current) => (current === propertyDeleteTarget.id ? nextSelectedId : current));
      setPropertyDeleteTarget(null);
    } catch (deleteError) {
      setPropertyDeleteError(deleteError.message);
    } finally {
      setIsDeletingProperty(false);
    }
  }

  function updatePropertyForm(field, value) {
    setPropertyForm((current) => ({ ...current, [field]: value }));
  }

  function handleZipCodeChange(value) {
    const option = zipCodeOptions.find((zipOption) => zipOption.zipCode === value);

    setPropertyForm((current) => ({
      ...current,
      zipCode: value,
      location: option?.location ?? "",
    }));
    setZipCodeError("");
  }

  async function handlePropertySave(event) {
    event.preventDefault();

    if (!usZipPattern.test(propertyForm.zipCode.trim())) {
      setZipCodeError("Enter a valid United States ZIP code, for example 95060.");
      return;
    }

    const amenities = [
      propertyForm.fridge ? "Fridge" : null,
      propertyForm.washer ? "Washer" : null,
      propertyForm.dryer ? "Dryer" : null,
      propertyForm.parking ? "Parking" : null,
      propertyForm.microwave ? "Microwave" : null,
    ].filter(Boolean);

    const basePrice = Number(propertyForm.minPrice || 145);
    const dynamicBase = Math.round(basePrice * 1.18);
    const resolvedLocation = zipCodeOptions.find((zipOption) => zipOption.zipCode === propertyForm.zipCode.trim())?.location ?? "United States ZIP area";
    const generatedName = `${resolvedLocation} ${propertyForm.propertyType === "Airbnb" ? "Stay" : "Room Type"} ${propertyForm.roomCount || 1}`;
    const nextProperty = {
      id: editingPropertyId ?? `property-${Date.now()}`,
      name: propertyForm.name.trim() || generatedName,
      propertyType: propertyForm.propertyType,
      roomCount: Number(propertyForm.roomCount || 1),
      zipCode: propertyForm.zipCode.trim(),
      location: resolvedLocation,
      streetAddress: propertyForm.streetAddress.trim() || "Not specified",
      guests: `${propertyForm.minGuests}-${propertyForm.maxGuests} guests`,
      bathroom: propertyForm.bathroom,
      beds: propertyForm.beds ? `${propertyForm.beds} beds` : "Not specified",
      bedSize: propertyForm.bedSize || "Not specified",
      amenities,
      fixedPrice: basePrice,
      agentAdr: dynamicBase,
      occupancy: "76%",
      revparLift: "+$1,200/mo",
      planDuration: resolvePlanLength(propertyForm.planDays),
      priceRange: propertyForm.minPrice && propertyForm.maxPrice ? `$${propertyForm.minPrice}-$${propertyForm.maxPrice}` : "Not specified",
      pricingConnection: propertyForm.pricingConnection,
      additionalInfo: propertyForm.additionalInfo.trim() || "Not specified",
      importFromAirbnb: propertyForm.propertyType === "Airbnb" ? propertyForm.importFromAirbnb : false,
      forecast: [
        { day: "May 10", fixed: basePrice, agent: dynamicBase },
        { day: "May 11", fixed: basePrice, agent: dynamicBase + 8 },
        { day: "May 12", fixed: basePrice, agent: dynamicBase - 4 },
        { day: "May 13", fixed: basePrice, agent: dynamicBase + 14 },
        { day: "May 14", fixed: basePrice, agent: dynamicBase + 24 },
        { day: "May 15", fixed: basePrice, agent: dynamicBase + 32 },
        { day: "May 16", fixed: basePrice, agent: dynamicBase + 19 },
      ],
    };

    const response = await fetch("/api/properties", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accountId: activeAccount.id, property: nextProperty }),
    });
    try {
      await readJsonResponse(response, "Failed to save property.");
    } catch (error) {
      setZipCodeError(error.message);
      return;
    }

    setProperties((current) => {
      if (editingPropertyId) {
        return current.map((property) => (property.id === editingPropertyId ? nextProperty : property));
      }
      return [...current, nextProperty];
    });
    setSelectedPropertyId(nextProperty.id);
    setActiveView("properties");
    setIsPropertyDialogOpen(false);
  }

  async function saveAccountConnection(type, connection) {
    if (!activeAccount?.id) {
      throw new Error("No signed-in account was found.");
    }

    const response = await fetch("/api/account-connections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        accountId: activeAccount.id,
        type,
        connection,
      }),
    });
    const payload = await readJsonResponse(response, "Failed to save account connection.");
    return payload.connection;
  }

  async function connectExternalAccount(provider) {
    const accountConfig =
      provider === "Airbnb"
        ? {
            id: "airbnb-main",
            name: "Airbnb Host Account",
            provider: "Airbnb",
            accountId: "airbnb@revnest.ai",
          }
        : {
            id: "hotel-pms-main",
            name: "Hotel PMS Price Publisher",
            provider: "Hotel pricing system",
            accountId: "pms-fresno-40",
          };

    if (externalAccounts.some((account) => account.id === accountConfig.id)) {
      return;
    }

    setConnectionError("");
    try {
      const savedConnection = await saveAccountConnection("externalAccount", {
        ...accountConfig,
        status: "Connected",
        connectedAt: formatConnectionTime(),
      });
      setExternalAccounts((current) => [...current, savedConnection]);
    } catch (error) {
      setConnectionError(error.message);
    }
  }

  async function connectChannel(channel) {
    if (connectedChannels.some((connectedChannel) => connectedChannel.id === channel.id)) {
      return;
    }

    setConnectionError("");
    try {
      const savedConnection = await saveAccountConnection("channel", {
        id: channel.id,
        name: channel.name,
        accountId: `${channel.name} mobile channel`,
        status: "Connected",
        connectedAt: formatConnectionTime(),
      });
      setConnectedChannels((current) => [...current, savedConnection]);
    } catch (error) {
      setConnectionError(error.message);
    }
  }

  if (!isAuthed) {
    return (
      <main className="welcome-shell">
        <div className="hero-overlay" />
        <section className="welcome-content" aria-label="Welcome">
          <div className="brand-lockup">
            <Image src="/icon.png" alt="RevNest" width={54} height={54} priority />
            <span>RevNest</span>
          </div>
          <div className="welcome-copy">
            <p className="eyebrow">RevNest · Pricing Agent</p>
            <h1>Watch the agent decide your nightly rate.</h1>
            <p>
              Multi-step reasoning over weather, events, competitor rates, and your own history — every tool call is auditable.
            </p>
          </div>
          <form className="login-panel" onSubmit={handleSubmit}>
            <div>
              <h2>Host Login</h2>
              <p>Enter the demo dashboard to view the agent workflow.</p>
            </div>
            <label>
              Email
              <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required />
            </label>
            <label>
              Password
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                placeholder="demo"
              />
            </label>
            {loginError ? <p className="login-error">{loginError}</p> : null}
            <div className="demo-accounts">
              <span>Demo accounts</span>
              {demoAccounts.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  onClick={() => {
                    setEmail(account.email);
                    setPassword(account.password);
                    setLoginError("");
                  }}
                >
                  {account.email}
                </button>
              ))}
            </div>
            <button type="submit">Sign in</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="airbnb-shell">
      <header className="airbnb-topbar">
        <div className="airbnb-topbar-left">
          <button className="airbnb-brand" type="button" onClick={() => setActiveView("home")} aria-label="RevNest Home">
            <Image src="/icon.png" alt="" width={34} height={34} />
            <span>RevNest</span>
          </button>
          <nav className="airbnb-topnav" aria-label="Main navigation">
            <button className={activeView === "home" ? "active" : ""} type="button" onClick={() => setActiveView("home")}>
              Home
            </button>
            <button className={activeView === "properties" ? "active" : ""} type="button" onClick={() => setActiveView("properties")}>
              My Properties
            </button>
            <button className={activeView === "revy" ? "active revy-nav-button" : "revy-nav-button"} type="button" onClick={() => setActiveView("revy")}>
              <Image className="topnav-revy-icon" src="/Revy.png" alt="" width={20} height={20} />
              Revy
            </button>
          </nav>
        </div>
        <div className="airbnb-topbar-right">
          <button
            className={activeView === "account" ? "airbnb-account-button active" : "airbnb-account-button"}
            type="button"
            onClick={() => setActiveView("account")}
            aria-label="Account"
            title="Account"
          >
            <UserIcon width={20} height={20} />
          </button>
        </div>
      </header>

      <section className="airbnb-main">
        {!isHotelAccount && activeView === "home" ? (
          <section className="home-page overview-page airbnb-home-page">
            <section className="empty-overview">
              <div className="empty-overview-copy">
                <h1>Welcome to RevNest</h1>
                <p>
                  Build a pricing cockpit that understands your properties, watches the market while you sleep,
                  and helps every stay earn what it should.
                </p>
                <div className="empty-overview-actions">
                  <button type="button" className="primary-action" onClick={() => router.push("/properties/new")}>
                    Add Property
                    <ArrowRightIcon width={14} height={14} />
                  </button>
                </div>
              </div>

              <div className="empty-overview-flow" aria-label="Pricing setup flow">
                <article>
                  <span>
                    <StepIcon name="occupancy" width={18} height={18} />
                  </span>
                  <div>
                    <strong>Add the listing</strong>
                    <p>Save the listing URL, guest capacity, room details, and host price guardrails.</p>
                  </div>
                </article>
                <article>
                  <span>
                    <StepIcon name="competitor" width={18} height={18} />
                  </span>
                  <div>
                    <strong>Collect market signals</strong>
                    <p>The pricing skill checks events, weather, holidays, hotel comps, vacation-rental comps, and tourism demand.</p>
                  </div>
                </article>
                <article>
                  <span>
                    <StepIcon name="shield" width={18} height={18} />
                  </span>
                  <div>
                    <strong>Review guarded prices</strong>
                    <p>Every recommendation stays inside your min/max range and comes with a readable agent trace.</p>
                  </div>
                </article>
              </div>
            </section>
          </section>
        ) : null}

        {isHotelAccount && activeView === "home" ? (
          <section className="home-page overview-page hotel-home-page">
            <section className="hotel-market-panel" aria-label="Market Signals Dashboard">
              <header className="hotel-dashboard-header">
                <h1>Market Signals Dashboard</h1>
                <button
                  className="primary-action compact-button hotel-run-revy-button"
                  type="button"
                  onClick={runHotelRevyBatch}
                  disabled={isRevyThinking || isStartingHotelRevy || isStartingRevy}
                >
                  {isStartingHotelRevy ? "Starting..." : isRevyThinking ? "Running..." : "Run Revy"}
                </button>
              </header>

              <section className="signal-grid hotel-signal-grid" aria-label="Market Signals">
              <DemandSignalCard
                icon="weather"
                label="Weather"
                value={demandSignals.weather.summary || "No forecast"}
                detail={`${demandSignals.weather.high_f ?? "--"}F / ${demandSignals.weather.low_f ?? "--"}F - ${demandSignals.weather.precip_pct ?? "--"}% precip`}
                trend={demandSignals.weather.impactTrend || "flat"}
                footnote={demandSignals.weather.footnote || "No major impact"}
                collectedAt={demandSignals.weather.collectedAt || hotelHomeDashboard?.marketDataRun?.collectedAt || hotelHomeDashboard?.marketDataRun?.updatedAt}
              />
              <DemandSignalCard
                icon="event"
                label="Local events"
                value={demandSignals.events.headline || "No major events"}
                detail={`${demandSignals.events.upcoming_count ?? 0} upcoming - ${demandSignals.events.location || "Unknown"}`}
                trend={demandSignals.events.trend || "flat"}
                footnote={demandSignals.events.footnote || "No major impact"}
                collectedAt={demandSignals.events.collectedAt || hotelHomeDashboard?.marketDataRun?.collectedAt || hotelHomeDashboard?.marketDataRun?.updatedAt}
              />
              <DemandSignalCard
                icon="competitor"
                label="Competitor Change"
                value={`${Number(demandSignals.competitor.delta_pct || 0) >= 0 ? "+" : ""}${demandSignals.competitor.delta_pct ?? 0}%`}
                detail={`${demandSignals.competitor.sample_size ?? 0} comps in ${demandSignals.competitor.location || "Unknown"}`}
                trend={demandSignals.competitor.trend || "flat"}
                footnote={`Median rate $${demandSignals.competitor.median_rate ?? "--"}`}
                collectedAt={demandSignals.competitor.collectedAt || hotelHomeDashboard?.marketDataRun?.collectedAt || hotelHomeDashboard?.marketDataRun?.updatedAt}
              />
              <DemandSignalCard
                icon="occupancy"
                label="Occupancy / demand"
                value={`${Math.round(Number(demandSignals.occupancy.portfolio_rate || 0) * 100)}%`}
                detail={`${demandSignals.occupancy.booked_room_nights ?? 0}/${demandSignals.occupancy.available_room_nights ?? 0} room nights`}
                trend={demandSignals.occupancy.trend || "flat"}
                footnote={`${demandSignals.occupancy.delta_vs_last_month_pct ?? 0}% vs last month`}
                collectedAt={demandSignals.occupancy.collectedAt || hotelHomeDashboard?.marketDataRun?.collectedAt || hotelHomeDashboard?.marketDataRun?.updatedAt}
              />
              </section>
            </section>

            <section className="panel hotel-list-panel">
              <div className="panel-heading hotel-panel-heading">
                <div className="hotel-panel-title">
                  <h2>Pending Tasks</h2>
                  <span className="pill live">{pendingTaskRecords.length} action{pendingTaskRecords.length === 1 ? "" : "s"}</span>
                </div>
                <div className="panel-actions">
                  <button className="primary-action compact-button" type="button" onClick={acceptAllPendingTasks} disabled={pendingTaskRecords.length === 0 || isAcceptingAllTasks}>
                    {isAcceptingAllTasks ? "Accepting..." : "Accept all"}
                  </button>
                  <button className="secondary-button compact-button" type="button" onClick={() => setIsPendingTasksExpanded((current) => !current)} disabled={pendingTaskRecords.length <= 3}>
                    {isPendingTasksExpanded ? "Show top 3" : "Show all"}
                  </button>
                </div>
              </div>
              {dashboardActionError ? <div className="form-error">{dashboardActionError}</div> : null}
              <div className="task-list">
                {displayedPendingTasks.map((task) => {
                  const priceDirection = pendingTaskPriceDirection(task);
                  return (
                    <button key={task.id} className="task-card" type="button" onClick={() => openPendingTaskDialog(task)}>
                      <div>
                        <div className="pending-task-topline">
                          <strong>{task.property}</strong>
                        </div>
                        <div className="price-log-times">
                          <span><b>Price date</b>{task.priceDate}</span>
                          <span><b>Strategy range</b>{formatTaskStrategyRange(task)}</span>
                          <span><b>Agent suggested at</b>{task.agentSuggestedAt}</span>
                        </div>
                        <span>{task.reviewReason || task.reason}</span>
                      </div>
                      <div className="task-actions">
                        <span>{priceDirection}: {task.currentPrice} to {task.agentSuggestedPrice}</span>
                        <b>{task.change}</b>
                      </div>
                    </button>
                  );
                })}
                {pendingTaskRecords.length === 0 ? (
                  <div className="empty-state">
                    <strong>No pending tasks</strong>
                    <span>Revy has no price changes waiting for review.</span>
                  </div>
                ) : null}
              </div>
            </section>

            <section className="panel hotel-list-panel">
              <div className="panel-heading hotel-panel-heading">
                <div className="hotel-panel-title">
                  <h2>Price Log</h2>
                  <span className="pill">{priceLogRecords.length} records</span>
                </div>
                <div className="panel-actions">
                  <button className="secondary-button compact-button" type="button" onClick={() => setIsPriceLogExpanded((current) => !current)} disabled={priceLogRecords.length <= 3}>
                    {isPriceLogExpanded ? "Show top 3" : "Show all"}
                  </button>
                </div>
              </div>
              <div className="price-log-list">
                {displayedPriceLogs.map((log) => (
                  <button className="price-log-row" key={log.id} type="button" onClick={() => setSelectedPriceLog(log)}>
                    <div>
                      <strong>{log.property}</strong>
                      <div className="price-log-times">
                        <span><b>Price date</b>{log.priceDate}</span>
                        <span><b>Modified at</b>{log.adjustedAt}</span>
                      </div>
                    </div>
                    <div className="price-log-change">
                      <em className={log.type === "Increase" ? "increase" : "decrease"}>{log.type}</em>
                      <span>{log.oldPrice} to {log.newPrice}</span>
                      <b>{log.change}</b>
                    </div>
                  </button>
                ))}
                {priceLogRecords.length === 0 ? (
                  <div className="empty-state">
                    <strong>No price history yet</strong>
                    <span>Accepted pricing changes will appear here after the first property is active.</span>
                  </div>
                ) : null}
              </div>
            </section>
          </section>
        ) : null}

        {activeView === "revy" ? (
          <RevyWorkspacePanel
            revyState={revyState}
            events={revyEvents}
            thinkingStatus={revyThinkingStatus}
            queuedSteer={queuedRevySteer}
            chatInput={chatInput}
            onChatInputChange={setChatInput}
            onChatSubmit={handleChatSubmit}
            isThinking={isRevyThinking}
            isStarting={isStartingRevy || isStartingHotelRevy}
            isStopping={isStoppingRevy}
            activeRunId={activeRevyRunId}
            onStopThinking={stopRevyThinking}
            conversations={revyConversations}
            selectedConversationId={selectedRevyConversationId}
            onSelectConversation={setSelectedRevyConversationId}
          />
        ) : null}

        {activeView === "properties" ? (
          <section className="airbnb-properties-page">
            <aside className="airbnb-property-rail">
              <div className="airbnb-rail-heading">
                <div>
                  <strong>My Properties</strong>
                </div>
                <span>{properties.length}</span>
              </div>
              {!isHotelAccount ? (
                <button className="airbnb-rail-add" type="button" onClick={() => router.push("/properties/new")}>
                  <PlusIcon />
                  Add Property
                </button>
              ) : null}
              <div className="airbnb-property-list">
                {properties.length > 0 ? (
                  properties.map((property) => (
                    <button
                      key={property.id}
                      className={selectedProperty?.id === property.id ? "airbnb-property-row selected" : "airbnb-property-row"}
                      type="button"
                      onClick={() => setSelectedPropertyId(property.id)}
                    >
                      <strong>{property.name}</strong>
                      <span>{isHotelAccount ? `room count: ${property.roomCount ?? 0}` : property.streetAddress || property.location || "Address pending"}</span>
                    </button>
                  ))
                ) : (
                  <div className="airbnb-rail-empty">
                    <strong>{isHotelAccount ? "No rooms yet" : "No properties yet"}</strong>
                    <span>{isHotelAccount ? "Hotel room types will appear here after the data seed is loaded." : "Add your first property to start pricing."}</span>
                  </div>
                )}
              </div>
            </aside>

            <section className="airbnb-property-workspace">
              {selectedProperty ? (
                <>
                  <section className="airbnb-property-card airbnb-property-summary-card">
                    <div className="airbnb-property-title-row">
                      <div>
                        <h1>{selectedProperty.name}</h1>
                      </div>
                      {!isHotelAccount ? (
                        <div className="airbnb-property-actions">
                          <button className="icon-button" type="button" onClick={() => openEditPropertyDialog("main")} aria-label="Edit property" title="Edit property">
                            <PencilIcon />
                          </button>
                          <button
                            className="icon-button danger-icon-button"
                            type="button"
                            onClick={() => {
                              setPropertyDeleteError("");
                              setPropertyDeleteTarget(selectedProperty);
                            }}
                            aria-label="Delete property"
                            title="Delete property"
                          >
                            <TrashIcon />
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <div className="airbnb-detail-grid">
                      {isHotelAccount ? (
                        <>
                          <article>
                            <span>Room Count</span>
                            <strong>{selectedProperty.roomCount || "Not specified"}</strong>
                          </article>
                          <article>
                            <span>Capacity</span>
                            <strong>{selectedProperty.guests || "Not specified"}</strong>
                          </article>
                          <article>
                            <span>Average Daily Rate (ADR)</span>
                            <strong>{selectedProperty.adr || (selectedProperty.agentAdr ? "$" + selectedProperty.agentAdr : "Not specified")}</strong>
                          </article>
                          <article>
                            <span>Revenue Per Available Room (RevPAR)</span>
                            <strong>{selectedProperty.revpar || "Not specified"}</strong>
                          </article>
                        </>
                      ) : (
                        <>
                          <article>
                            <span>Address</span>
                            <strong>{selectedProperty.streetAddress || selectedProperty.location || "Not specified"}</strong>
                          </article>
                          <article>
                            <span>ZIP code</span>
                            <strong>{selectedProperty.zipCode || "Not specified"}</strong>
                          </article>
                          <article>
                            <span>Capacity</span>
                            <strong>{selectedProperty.guests || "Not specified"}</strong>
                          </article>
                          <article>
                            <span>URL</span>
                            {selectedProperty.airbnbUrl ? (
                              <a href={selectedProperty.airbnbUrl} target="_blank" rel="noreferrer">
                                {selectedProperty.airbnbUrl}
                              </a>
                            ) : (
                              <strong>Not specified</strong>
                            )}
                          </article>
                        </>
                      )}
                    </div>
                  </section>

                  <section className="airbnb-property-card">
                    <div className="airbnb-section-heading">
                      <h2>Revy Suggested Prices</h2>
                    </div>
                    <RevyAgentPriceChart
                      data={selectedProperty.forecast}
                      error={selectedProperty.pricingOutputError}
                      onPointClick={openPricePointDialog}
                    />
                  </section>
                </>
              ) : (
                <section className="airbnb-empty-workspace">
                  <h1>No property selected</h1>
                  <p>{isHotelAccount ? "No hotel room type is selected." : "Add a property to see listing details and Revy prices."}</p>
                  {!isHotelAccount ? (
                    <button className="primary-action" type="button" onClick={() => router.push("/properties/new")}>
                      Add Property
                      <ArrowRightIcon width={14} height={14} />
                    </button>
                  ) : null}
                </section>
              )}
            </section>
          </section>
        ) : null}

        {activeView === "account" ? (
          <section className="account-page">
            <section className="panel" id="account-settings">
              <div className="panel-heading">
                <h2>Account Setting</h2>
                <span className="pill">Demo</span>
              </div>
              <div className="account-summary">
                <span>Account</span>
                <strong>{activeAccount.name}</strong>
                <span>Signed in as</span>
                <strong>{email}</strong>
                <span aria-hidden="true" />
                <button className="secondary-button compact-button" type="button" onClick={handleLogout}>
                  Logout
                </button>
              </div>
              {connectionError ? <div className="form-error">{connectionError}</div> : null}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h2>External Accounts</h2>
                <div className="panel-actions">
                  <span className="pill">{externalAccounts.length} connected</span>
                  <button className="primary-action compact-button" type="button" onClick={() => setIsExternalConnectionDialogOpen(true)}>Add Connection</button>
                </div>
              </div>
              <div className="external-account-list">
                {externalAccounts.length > 0 ? (
                  externalAccounts.map((account) => (
                    <article className="external-account-card" key={account.id}>
                      <div>
                        <strong>{account.name}</strong>
                        <span>{account.provider} / {account.accountId}</span>
                      </div>
                      <div>
                        <em>{account.status}</em>
                        <small>{account.connectedAt}</small>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="empty-state">
                    <strong>No external accounts connected</strong>
                    <span>Connect a publisher when this account is ready to sync prices.</span>
                  </div>
                )}
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h2>Channels</h2>
                <div className="panel-actions">
                  <span className="pill">{connectedChannels.length} connected</span>
                  <button className="primary-action compact-button" type="button" onClick={() => setIsChannelConnectionDialogOpen(true)}>Add Channel</button>
                </div>
              </div>
              <div className="external-account-list">
                {connectedChannels.length > 0 ? (
                  connectedChannels.map((channel) => (
                    <article className="external-account-card" key={channel.id}>
                      <div>
                        <strong>{channel.name}</strong>
                        <span>{channel.accountId}</span>
                      </div>
                      <div>
                        <em>{channel.status}</em>
                        <small>{channel.connectedAt}</small>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="empty-state">
                    <strong>No channels connected</strong>
                    <span>Connect a channel when this account needs alerts or approvals.</span>
                  </div>
                )}
              </div>
            </section>
          </section>
        ) : null}
      </section>

      <Dialog open={isPropertyDialogOpen} onClose={() => setIsPropertyDialogOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>
          {propertyDialogMode === "optional" ? "Modify Additional Room Information" : editingPropertyId ? "Modify Room Settings" : "Add New Property"}
        </DialogTitle>
        <DialogContent>
          <form className="property-form" id="property-form" onSubmit={handlePropertySave}>
            {propertyDialogMode !== "optional" ? (
              <>
                <TextField
                  label="Property name"
                  value={propertyForm.name}
                  onChange={(event) => updatePropertyForm("name", event.target.value)}
                  fullWidth
                />
                <TextField select label="Property type" value={propertyForm.propertyType} onChange={(event) => updatePropertyForm("propertyType", event.target.value)} fullWidth required>
                  <MenuItem value="Airbnb">Airbnb</MenuItem>
                  <MenuItem value="Boutique Hotel">Boutique Hotel</MenuItem>
                  <MenuItem value="Motel / Budget Hotel">Motel / Budget Hotel</MenuItem>
                </TextField>
                <TextField
                  label="Room count"
                  type="number"
                  value={propertyForm.roomCount}
                  onChange={(event) => updatePropertyForm("roomCount", event.target.value)}
                  slotProps={{ htmlInput: { min: 1, max: 500 } }}
                  fullWidth
                  required
                />
                <div className="suggest-field">
                  <TextField
                    label="ZIP code"
                    value={propertyForm.zipCode}
                    onChange={(event) => {
                      handleZipCodeChange(event.target.value);
                      setIsZipMenuOpen(true);
                    }}
                    onFocus={() => setIsZipMenuOpen(true)}
                    onBlur={() => setTimeout(() => setIsZipMenuOpen(false), 120)}
                    required
                    error={Boolean(zipCodeError)}
                    helperText={zipCodeError || propertyForm.location || "Choose or enter a United States ZIP code."}
                    fullWidth
                  />
                  {isZipMenuOpen ? (
                    <div className="suggest-menu">
                      {zipCodeOptions
                        .filter((option) =>
                          `${option.zipCode} ${option.location}`.toLowerCase().includes(propertyForm.zipCode.toLowerCase()),
                        )
                        .map((option) => (
                          <button
                            key={option.zipCode}
                            type="button"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              handleZipCodeChange(option.zipCode);
                              setIsZipMenuOpen(false);
                            }}
                          >
                            <span>{option.zipCode}</span>
                            <small>{option.location}</small>
                          </button>
                        ))}
                    </div>
                  ) : null}
                </div>
                <div className="form-pair">
                  <TextField
                    label="Minimum guests"
                    type="number"
                    value={propertyForm.minGuests}
                    onChange={(event) => updatePropertyForm("minGuests", event.target.value)}
                    slotProps={{ htmlInput: { min: 1, max: 30 } }}
                    required
                  />
                  <TextField
                    label="Maximum guests"
                    type="number"
                    value={propertyForm.maxGuests}
                    onChange={(event) => updatePropertyForm("maxGuests", event.target.value)}
                    slotProps={{ htmlInput: { min: 1, max: 30 } }}
                    required
                  />
                </div>
                <div className="form-pair">
                  <TextField select label="Bathroom" value={propertyForm.bathroom} onChange={(event) => updatePropertyForm("bathroom", event.target.value)} required>
                    <MenuItem value="Private">Private</MenuItem>
                    <MenuItem value="Shared">Shared</MenuItem>
                  </TextField>
                  <div className="suggest-field">
                    <TextField
                      label="Pricing plan length"
                      value={propertyForm.planDays}
                      onChange={(event) => {
                        updatePropertyForm("planDays", event.target.value);
                        setIsPlanMenuOpen(true);
                      }}
                      onFocus={() => setIsPlanMenuOpen(true)}
                      onClick={() => setIsPlanMenuOpen(true)}
                      onBlur={() => setTimeout(() => setIsPlanMenuOpen(false), 120)}
                      helperText="Type number of days or choose a preset."
                      required
                      fullWidth
                    />
                    {isPlanMenuOpen ? (
                      <div className="suggest-menu">
                        {planLengthOptions.map((option) => (
                          <button
                            key={option}
                            type="button"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              updatePropertyForm("planDays", option);
                              setIsPlanMenuOpen(false);
                            }}
                          >
                            <span>{option}</span>
                            <small>{planLengthDays[option]} days</small>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </>
            ) : null}

            {propertyDialogMode === "optional" ? (
              <>
                {propertyForm.propertyType === "Airbnb" ? (
                  <a className="airbnb-import-button" href="https://www.airbnb.com/hosting/listings" target="_blank" rel="noreferrer">
                    Import from Airbnb
                  </a>
                ) : null}
                <TextField
                  select
                  label="Pricing control"
                  value={propertyForm.pricingConnection}
                  onChange={(event) => updatePropertyForm("pricingConnection", event.target.value)}
                  helperText="Manual is default. Choose a connected account if the agent should take over publishing price changes."
                  fullWidth
                >
                  <MenuItem value="manual">Manual pricing</MenuItem>
                  {externalAccounts.map((account) => (
                    <MenuItem value={account.id} key={account.id}>{account.provider}: {account.name}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Street address"
                  value={propertyForm.streetAddress}
                  onChange={(event) => updatePropertyForm("streetAddress", event.target.value)}
                  fullWidth
                />
                <div className="form-pair">
                  <TextField label="Number of beds" type="number" value={propertyForm.beds} onChange={(event) => updatePropertyForm("beds", event.target.value)} slotProps={{ htmlInput: { min: 0 } }} />
                  <TextField select label="Bed size" value={propertyForm.bedSize} onChange={(event) => updatePropertyForm("bedSize", event.target.value)}>
                    <MenuItem value="">Not specified</MenuItem>
                    <MenuItem value="Twin">Twin</MenuItem>
                    <MenuItem value="Full">Full</MenuItem>
                    <MenuItem value="Queen">Queen</MenuItem>
                    <MenuItem value="King">King</MenuItem>
                  </TextField>
                </div>
                <div className="amenity-grid">
                  <FormControlLabel control={<Checkbox checked={propertyForm.fridge} onChange={(event) => updatePropertyForm("fridge", event.target.checked)} />} label="Fridge" />
                  <FormControlLabel control={<Checkbox checked={propertyForm.washer} onChange={(event) => updatePropertyForm("washer", event.target.checked)} />} label="Washer" />
                  <FormControlLabel control={<Checkbox checked={propertyForm.dryer} onChange={(event) => updatePropertyForm("dryer", event.target.checked)} />} label="Dryer" />
                  <FormControlLabel control={<Checkbox checked={propertyForm.parking} onChange={(event) => updatePropertyForm("parking", event.target.checked)} />} label="Parking" />
                  <FormControlLabel control={<Checkbox checked={propertyForm.microwave} onChange={(event) => updatePropertyForm("microwave", event.target.checked)} />} label="Microwave" />
                </div>
                <div className="form-pair">
                  <TextField label="Minimum acceptable price" type="number" value={propertyForm.minPrice} onChange={(event) => updatePropertyForm("minPrice", event.target.value)} />
                  <TextField label="Maximum acceptable price" type="number" value={propertyForm.maxPrice} onChange={(event) => updatePropertyForm("maxPrice", event.target.value)} />
                </div>
                <TextField
                  label="Other room information"
                  value={propertyForm.additionalInfo}
                  onChange={(event) => updatePropertyForm("additionalInfo", event.target.value)}
                  multiline
                  minRows={3}
                  fullWidth
                />
              </>
            ) : null}
          </form>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsPropertyDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" type="submit" form="property-form">Save Property</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(propertyDeleteTarget)} onClose={() => setPropertyDeleteTarget(null)} fullWidth maxWidth="xs">
        <DialogTitle>Delete property?</DialogTitle>
        <DialogContent>
          <div className="delete-dialog-copy">
            <p>
              This will delete {propertyDeleteTarget?.name ? <strong>{propertyDeleteTarget.name}</strong> : "this property"} and its saved price records.
              If a pricing agent is currently running for it, the agent will be stopped first.
            </p>
            {propertyDeleteError ? <div className="form-error">{propertyDeleteError}</div> : null}
          </div>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPropertyDeleteTarget(null)} disabled={isDeletingProperty}>Cancel</Button>
          <Button color="error" variant="contained" onClick={handleDeleteProperty} disabled={isDeletingProperty}>
            {isDeletingProperty ? "Deleting..." : "Delete property"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={isExternalConnectionDialogOpen} onClose={() => setIsExternalConnectionDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add External Account</DialogTitle>
        <DialogContent>
          <div className="connection-dialog-list">
            <button
              type="button"
              onClick={() => {
                connectExternalAccount("Airbnb");
                setIsExternalConnectionDialogOpen(false);
              }}
            >
              <strong>Airbnb</strong>
              <span>Let the agent publish Airbnb nightly rate changes after approval.</span>
            </button>
            <button
              type="button"
              onClick={() => {
                connectExternalAccount("Hotel pricing system");
                setIsExternalConnectionDialogOpen(false);
              }}
            >
              <strong>Hotel pricing system</strong>
              <span>Connect a PMS, channel manager, or hotel rate publishing system.</span>
            </button>
          </div>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsExternalConnectionDialogOpen(false)}>Cancel</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={isChannelConnectionDialogOpen} onClose={() => setIsChannelConnectionDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add Channel</DialogTitle>
        <DialogContent>
          <div className="connection-dialog-list">
            {availableChannels.map((channel) => (
              <button
                type="button"
                key={channel.id}
                onClick={() => {
                  connectChannel(channel);
                  setIsChannelConnectionDialogOpen(false);
                }}
              >
                <strong>{channel.name}</strong>
                <span>{channel.support}</span>
                <small>{channel.detail}</small>
              </button>
            ))}
          </div>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsChannelConnectionDialogOpen(false)}>Cancel</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(selectedPricePoint)} onClose={closePricePointDialog} fullWidth maxWidth="md">
        <DialogTitle>
          {selectedPricePoint
            ? `${selectedPricePoint.property.name} - ${selectedPricePoint.point?.day || "Selected date"} - Revy $${Math.round(Number(selectedPricePoint.point?.agent || 0))}`
            : "Revy Price Detail"}
        </DialogTitle>
        {selectedPricePoint ? (
          <DialogContent>
            <div className="price-point-dialog">
              <section className="price-point-summary" aria-label="Selected price point">
                <article>
                  <span>Room</span>
                  <strong>{selectedPricePoint.property.name}</strong>
                </article>
                <article>
                  <span>Date</span>
                  <strong>{selectedPricePoint.point?.day || "Selected date"}</strong>
                </article>
                <article>
                  <span>Revy Suggested</span>
                  <strong>${Math.round(Number(selectedPricePoint.point?.agent || 0))}</strong>
                </article>
              </section>
              {pricePointError ? <div className="form-error">{pricePointError}</div> : null}
              {isPricePointHistoryLoading ? (
                <div className="empty-state">
                  <strong>Loading Revy history</strong>
                  <span>Finding saved conversations for this room.</span>
                </div>
              ) : (
                <RevyHistoryPanel
                  conversations={pricePointConversations}
                  emptyMessage="No saved Revy conversations for this room yet."
                />
              )}
            </div>
          </DialogContent>
        ) : null}
        <DialogActions>
          <Button onClick={closePricePointDialog} disabled={isStartingRevy}>Close</Button>
          <Button onClick={askRevyAboutPricePoint} disabled={!selectedPricePoint || isStartingRevy}>
            Ask Revy About This Price
          </Button>
          <Button variant="contained" onClick={runRevyForPricePoint} disabled={!selectedPricePoint || isStartingRevy}>
            {isStartingRevy ? "Starting..." : "Run Revy"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(selectedPendingTask)} onClose={() => setSelectedPendingTask(null)} fullWidth maxWidth="sm">
        <DialogTitle>Pending Price Task</DialogTitle>
        {selectedPendingTask ? (() => {
          const classification = pendingTaskClassification(selectedPendingTask);
          const priceDirection = pendingTaskPriceDirection(selectedPendingTask);
          return (
            <DialogContent>
              <div className="pending-task-detail">
                <div className="detail-grid">
                  <article><span>Property</span><strong>{selectedPendingTask.property}</strong></article>
                  <article><span>Price Date</span><strong>{selectedPendingTask.priceDate}</strong></article>
                  <article><span>Current Price</span><strong>{selectedPendingTask.currentPrice}</strong></article>
                  <article><span>Agent Suggested Price</span><strong>{selectedPendingTask.agentSuggestedPrice}</strong></article>
                  <article><span>Price Direction</span><strong>{priceDirection}</strong></article>
                  <article><span>Strategy Range</span><strong>{formatTaskStrategyRange(selectedPendingTask)}</strong></article>
                  <article><span>Agent Suggested At</span><strong>{selectedPendingTask.agentSuggestedAt}</strong></article>
                  <article><span>Change</span><strong>{selectedPendingTask.change}</strong></article>
                </div>

                <div className={`approval-reason-card ${classification.className}`}>
                  <h3>Agent Reasoning</h3>
                  <p>{selectedPendingTask.reason || selectedPendingTask.reviewReason || classification.description}</p>
                </div>

                <div className="form-pair">
                  <TextField
                    select
                    label="Task decision"
                    value={pendingTaskAction}
                    onChange={(event) => setPendingTaskAction(event.target.value)}
                    required
                  >
                    <MenuItem value="apply">Apply final price</MenuItem>
                    <MenuItem value="close">Close this task</MenuItem>
                  </TextField>
                  <TextField
                    label="Final price"
                    value={pendingFinalPrice}
                    onChange={(event) => setPendingFinalPrice(event.target.value)}
                    helperText="Only used when applying the price change."
                    disabled={pendingTaskAction === "close"}
                  />
                </div>

                <TextField
                  label="Notes for future agent reminders"
                  value={pendingFeedback}
                  onChange={(event) => setPendingFeedback(event.target.value)}
                  helperText="Optional. Tell the agent what to remember next time."
                  multiline
                  minRows={3}
                  fullWidth
                />
              </div>
            </DialogContent>
          );
        })() : null}
        <DialogActions>
          {selectedPendingTask ? (
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                askAgentAboutPendingTask(selectedPendingTask);
              }}
            >
              Ask Agent
            </Button>
          ) : null}
          <Button variant="contained" onClick={confirmPendingTask}>Confirm</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(selectedPriceLog)} onClose={() => setSelectedPriceLog(null)} fullWidth maxWidth="sm">
        <DialogTitle>Price Change Details</DialogTitle>
        {selectedPriceLog ? (
          <DialogContent>
            <div className="price-log-detail">
              <div className="detail-grid">
                <article><span>Property</span><strong>{selectedPriceLog.property}</strong></article>
                <article><span>Price Date</span><strong>{selectedPriceLog.priceDate}</strong></article>
                <article><span>Change Type</span><strong>{selectedPriceLog.type}</strong></article>
                <article><span>Agent Suggested At</span><strong>{selectedPriceLog.agentSuggestedAt}</strong></article>
                <article><span>Agent Suggested Price</span><strong>{selectedPriceLog.agentSuggestedPrice}</strong></article>
                <article><span>Modified At</span><strong>{selectedPriceLog.adjustedAt}</strong></article>
                <article><span>Old Price</span><strong>{selectedPriceLog.oldPrice}</strong></article>
                <article><span>Confirmed New Price</span><strong>{selectedPriceLog.newPrice}</strong></article>
              </div>
              <div>
                <h3>Agent Reason</h3>
                <p>{selectedPriceLog.reason}</p>
              </div>
              <div>
                <h3>Signals Used</h3>
                <ul>
                  {selectedPriceLog.agentSignals.map((signal) => (
                    <li key={signal}>{signal}</li>
                  ))}
                </ul>
              </div>
            </div>
          </DialogContent>
        ) : null}
        <DialogActions>
          <Button onClick={() => setSelectedPriceLog(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </main>
  );
}
