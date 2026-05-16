"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Step,
  StepLabel,
  Stepper,
  TextField,
} from "@mui/material";
import AgentRunPanels from "./AgentRunPanels";
import DashboardShell from "./DashboardShell";
import { ArrowRightIcon, StepIcon } from "./AgentIcons";
import { humanReadableAirbnbPropertyName } from "@/lib/propertyNames";

const SESSION_KEY = "revnestSession";
const DRAFT_KEY = "revnestWizardDraft";

const airbnbUrlPattern = /^https?:\/\/(?:www\.)?airbnb\.[^/]+\/rooms\/(\d+)/i;

const wizardSteps = [1, 2, 3, 4];

const wizardStepperSx = {
  "& .MuiStepConnector-line": {
    borderColor: "var(--line)",
    borderTopWidth: 2,
  },
  "& .MuiStepConnector-root.Mui-active .MuiStepConnector-line, & .MuiStepConnector-root.Mui-completed .MuiStepConnector-line": {
    borderColor: "var(--forest)",
  },
  "& .MuiStepIcon-root, & .MuiStepIcon-root.Mui-active, & .MuiStepIcon-root.Mui-completed": {
    color: "var(--forest)",
  },
  "& .MuiStepLabel-label, & .MuiStepLabel-label.Mui-active, & .MuiStepLabel-label.Mui-completed": {
    color: "var(--forest-dark)",
  },
};

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

const emptyManualForm = {
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

function stepForView(view) {
  if (view === "type") return 1;
  if (view === "source") return 2;
  if (view === "url" || view === "manual") return 3;
  return 4;
}

function parseStoredJson(key) {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveStoredJson(key, value) {
  window.localStorage.setItem(key, JSON.stringify(value));
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

function resolvePlanLength(value) {
  const normalizedValue = String(value || "").trim().toLowerCase();
  if (planLengthDays[normalizedValue]) return normalizedValue;
  const numericDays = Number(normalizedValue.replace(/[^0-9]/g, ""));
  if (!Number.isNaN(numericDays) && numericDays > 0) return `${Math.min(numericDays, 730)} days`;
  return "90 days";
}

function numericPlanDays(value) {
  const resolved = resolvePlanLength(value);
  if (planLengthDays[resolved]) return planLengthDays[resolved];
  const numericDays = Number(String(resolved).replace(/[^0-9]/g, ""));
  return Number.isNaN(numericDays) ? 90 : numericDays;
}

function priceToNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function buildForecast(basePrice) {
  const dynamicBase = Math.round(basePrice * 1.18);
  return [
    { day: "May 10", fixed: basePrice, agent: dynamicBase },
    { day: "May 11", fixed: basePrice, agent: dynamicBase + 8 },
    { day: "May 12", fixed: basePrice, agent: dynamicBase - 4 },
    { day: "May 13", fixed: basePrice, agent: dynamicBase + 14 },
    { day: "May 14", fixed: basePrice, agent: dynamicBase + 24 },
    { day: "May 15", fixed: basePrice, agent: dynamicBase + 32 },
    { day: "May 16", fixed: basePrice, agent: dynamicBase + 19 },
  ];
}

async function saveDraftProperty({ accountId, property }) {
  const response = await fetch("/api/properties", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accountId, property }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Failed to save property draft.");
  }
  return payload.property;
}

function WizardStepIcon({ active = false, completed = false, icon }) {
  return (
    <span className={`wizard-step-number${active ? " active" : ""}${completed ? " completed" : ""}`}>
      {icon}
    </span>
  );
}

function WizardProgress({ currentStep }) {
  return (
    <Stepper className="wizard-progress" activeStep={currentStep - 1} alternativeLabel aria-label="Add property progress" sx={wizardStepperSx}>
      {wizardSteps.map((step) => (
        <Step key={step} completed={step < currentStep}>
          <StepLabel aria-label={`Step ${step}`} slots={{ stepIcon: WizardStepIcon }}>
            <span className="wizard-progress-label">Step {step}</span>
          </StepLabel>
        </Step>
      ))}
    </Stepper>
  );
}

function WizardFrame({ view, session, children }) {
  const isRunView = view === "run";
  const pageClassName = view === "run" ? "wizard-page run-wizard-page" : `wizard-page ${view}-wizard-page`;

  return (
    <DashboardShell activeView="" activeAccount={session} email={session?.email}>
      <section className={pageClassName}>
        {!isRunView ? (
          <>
            <header className="wizard-header">
              <div>
                <h1>Add Property</h1>
                <p>Set up the property, choose the data source, then let the pricing agent run with a visible tool trace.</p>
              </div>
            </header>
            <WizardProgress currentStep={stepForView(view)} />
          </>
        ) : null}
        {children}
      </section>
    </DashboardShell>
  );
}

export default function AddPropertyWizard({ view, propertyId: initialPropertyId = "", runId: initialRunId = "" }) {
  const router = useRouter();
  const [session, setSession] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const storedSession = parseStoredJson(SESSION_KEY);
    if (!storedSession?.id || !storedSession.accountType) {
      window.localStorage.removeItem(SESSION_KEY);
      router.replace("/");
      return;
    }
    queueMicrotask(() => {
      setSession(storedSession);
      setLoaded(true);
    });
  }, [router]);

  if (!loaded || !session) {
    return (
      <main className="dashboard-shell">
        <section className="dashboard-main">
          <div className="panel">Loading setup…</div>
        </section>
      </main>
    );
  }

  if (view === "type") return <TypeStep session={session} />;
  if (view === "source") return <SourceStep session={session} />;
  if (view === "url") return <UrlStep session={session} />;
  if (view === "manual") return <ManualStep session={session} />;
  return <RunStep session={session} initialPropertyId={initialPropertyId} initialRunId={initialRunId} />;
}

function TypeStep({ session }) {
  const router = useRouter();
  const [selection, setSelection] = useState("airbnb");

  return (
    <WizardFrame view="type" session={session}>
      <section className="wizard-card-grid">
        <button type="button" className={selection === "airbnb" ? "wizard-choice selected" : "wizard-choice"} onClick={() => setSelection("airbnb")}>
          <StepIcon name="occupancy" width={22} height={22} />
          <strong>Airbnb</strong>
          <span>Import a listing or enter details manually, then run the Airbnb pricing agent.</span>
        </button>
        <button type="button" className={selection === "hotel" ? "wizard-choice selected" : "wizard-choice"} onClick={() => setSelection("hotel")}>
          <StepIcon name="competitor" width={22} height={22} />
          <strong>Hotel</strong>
          <span>Hotel onboarding is coming soon. This path is visible for the future product flow.</span>
          <em>Coming soon</em>
        </button>
      </section>
      <div className="wizard-actions">
        <button type="button" className="secondary-button compact-button" onClick={() => router.push("/")}>Back</button>
        <button
          type="button"
          className="primary-action"
          disabled={selection !== "airbnb"}
          onClick={() => router.push("/properties/new/airbnb/source")}
        >
          Next
          <ArrowRightIcon width={14} height={14} />
        </button>
      </div>
    </WizardFrame>
  );
}

function SourceStep({ session }) {
  const router = useRouter();
  const [source, setSource] = useState("url");

  return (
    <WizardFrame view="source" session={session}>
      <section className="wizard-card-grid">
        <button type="button" className={source === "url" ? "wizard-choice selected" : "wizard-choice"} onClick={() => setSource("url")}>
          <StepIcon name="sparkle" width={22} height={22} />
          <strong>Import from URL</strong>
          <span>Use an Airbnb listing URL, price guardrails, and host notes to start the agent.</span>
        </button>
        <button type="button" className={source === "manual" ? "wizard-choice selected" : "wizard-choice"} onClick={() => setSource("manual")}>
          <StepIcon name="save" width={22} height={22} />
          <strong>Manual input</strong>
          <span>Enter the room and pricing setup yourself before the agent runs.</span>
        </button>
      </section>
      <div className="wizard-actions">
        <button type="button" className="secondary-button compact-button" onClick={() => router.push("/properties/new")}>Back</button>
        <button type="button" className="primary-action" onClick={() => router.push(`/properties/new/airbnb/${source}`)}>
          Next
          <ArrowRightIcon width={14} height={14} />
        </button>
      </div>
    </WizardFrame>
  );
}

function UrlStep({ session }) {
  const router = useRouter();
  const [form, setForm] = useState({
    airbnbUrl: "https://www.airbnb.com/rooms/1386388491046164092?photo_id=2119296775&source_impression_id=p3_1778635269_P3AqwMDcxp41Ckqm&previous_page_section_name=1000",
    minPrice: "300",
    maxPrice: "700",
    pricingHorizon: "2",
    supplementalInfo: "",
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    const match = form.airbnbUrl.trim().match(airbnbUrlPattern);
    const minPrice = priceToNumber(form.minPrice);
    const maxPrice = priceToNumber(form.maxPrice);
    const pricingHorizon = Number(form.pricingHorizon);

    if (!match) {
      setError("Enter a valid Airbnb room URL, for example https://www.airbnb.com/rooms/123456789.");
      return;
    }
    if (!minPrice || !maxPrice || maxPrice <= minPrice) {
      setError("Enter a valid min and max price. Max price must be higher than min price.");
      return;
    }
    if (!Number.isInteger(pricingHorizon) || pricingHorizon < 1 || pricingHorizon > 730) {
      setError("Pricing horizon must be a whole number between 1 and 730 days.");
      return;
    }

    const roomId = match[1];
    const propertyId = `airbnb-${roomId}`;
    const propertyName = humanReadableAirbnbPropertyName({
      airbnbUrl: form.airbnbUrl,
      propertyId,
      roomId,
    });
    const property = {
      id: propertyId,
      name: propertyName,
      displayNameSource: "airbnb_url_fallback",
      propertyType: "Airbnb",
      roomCount: 1,
      zipCode: "",
      location: "Pending browser verification",
      streetAddress: "Pending browser verification",
      guests: "Pending verification",
      bathroom: "Pending verification",
      beds: "Pending verification",
      bedSize: "Pending verification",
      amenities: [],
      fixedPrice: null,
      agentAdr: null,
      occupancy: "Pending",
      revparLift: "Pending",
      planDuration: `${pricingHorizon} days`,
      priceRange: `$${minPrice}-$${maxPrice}`,
      pricingConnection: "manual",
      additionalInfo: form.supplementalInfo.trim(),
      importFromAirbnb: true,
      status: "draft",
      onboardingSource: "airbnb_url",
      airbnbUrl: form.airbnbUrl.trim(),
      myPlace: form.airbnbUrl.trim(),
      minPrice,
      maxPrice,
      pricingHorizon,
      supplementalInfo: form.supplementalInfo.trim(),
      forecast: [],
    };

    setSaving(true);
    try {
      await saveDraftProperty({ accountId: session.id, property });
      saveStoredJson(DRAFT_KEY, {
        accountId: session.id,
        propertyId,
        propertyType: "airbnb",
        myPlace: property.myPlace,
        minPrice,
        maxPrice,
        pricingHorizon,
        supplementalInfo: property.supplementalInfo,
      });
      router.push(`/properties/new/airbnb/run?propertyId=${encodeURIComponent(propertyId)}`);
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <WizardFrame view="url" session={session}>
      <form className="wizard-form url-import-form panel" id="airbnb-url-form" onSubmit={submit}>
        <div className="url-import-row">
          <TextField label="Airbnb URL" value={form.airbnbUrl} onChange={(event) => update("airbnbUrl", event.target.value)} fullWidth required />
          <TextField label="Pricing horizon" type="number" value={form.pricingHorizon} onChange={(event) => update("pricingHorizon", event.target.value)} helperText="Nights to price." required />
        </div>
        <div className="form-pair url-price-row">
          <TextField label="Minimum price" type="number" value={form.minPrice} onChange={(event) => update("minPrice", event.target.value)} required />
          <TextField label="Maximum price" type="number" value={form.maxPrice} onChange={(event) => update("maxPrice", event.target.value)} required />
        </div>
        <TextField
          label="Supplemental information"
          value={form.supplementalInfo}
          onChange={(event) => update("supplementalInfo", event.target.value)}
          multiline
          rows={4}
          helperText="Optional host notes for the agent."
          fullWidth
        />
        {error ? <div className="form-error">{error}</div> : null}
      </form>
      <div className="wizard-actions url-import-actions">
        <button type="button" className="secondary-button compact-button" onClick={() => router.push("/properties/new/airbnb/source")}>Back</button>
        <button type="submit" className="primary-action" form="airbnb-url-form" disabled={saving}>
          {saving ? "Saving…" : "Next"}
          <ArrowRightIcon width={14} height={14} />
        </button>
      </div>
    </WizardFrame>
  );
}

function ManualStep({ session }) {
  const router = useRouter();
  const [form, setForm] = useState(emptyManualForm);
  const [zipCodeError, setZipCodeError] = useState("");
  const [isZipMenuOpen, setIsZipMenuOpen] = useState(false);
  const [isPlanMenuOpen, setIsPlanMenuOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
    setError("");
  }

  function handleZipCodeChange(value) {
    const option = zipCodeOptions.find((zipOption) => zipOption.zipCode === value);
    setForm((current) => ({ ...current, zipCode: value, location: option?.location ?? "" }));
    setZipCodeError("");
  }

  async function submit(event) {
    event.preventDefault();
    if (!usZipPattern.test(form.zipCode.trim())) {
      setZipCodeError("Enter a valid United States ZIP code, for example 95060.");
      return;
    }

    const minPrice = priceToNumber(form.minPrice);
    const maxPrice = priceToNumber(form.maxPrice);
    const pricingHorizon = numericPlanDays(form.planDays);
    if (!minPrice || !maxPrice || maxPrice <= minPrice) {
      setError("Enter a valid min and max price. Max price must be higher than min price.");
      return;
    }

    const amenities = [
      form.fridge ? "Fridge" : null,
      form.washer ? "Washer" : null,
      form.dryer ? "Dryer" : null,
      form.parking ? "Parking" : null,
      form.microwave ? "Microwave" : null,
    ].filter(Boolean);
    const basePrice = minPrice;
    const resolvedLocation = zipCodeOptions.find((zipOption) => zipOption.zipCode === form.zipCode.trim())?.location ?? "United States ZIP area";
    const generatedName = `${resolvedLocation} Airbnb Stay ${form.roomCount || 1}`;
    const propertyId = `airbnb-manual-${Date.now()}`;
    const property = {
      id: propertyId,
      name: form.name.trim() || generatedName,
      propertyType: "Airbnb",
      roomCount: Number(form.roomCount || 1),
      zipCode: form.zipCode.trim(),
      location: resolvedLocation,
      streetAddress: form.streetAddress.trim() || "Not specified",
      guests: `${form.minGuests}-${form.maxGuests} guests`,
      bathroom: form.bathroom,
      beds: form.beds ? `${form.beds} beds` : "Not specified",
      bedSize: form.bedSize || "Not specified",
      amenities,
      fixedPrice: basePrice,
      agentAdr: Math.round(basePrice * 1.18),
      occupancy: "76%",
      revparLift: "Pending",
      planDuration: resolvePlanLength(form.planDays),
      priceRange: `$${minPrice}-$${maxPrice}`,
      pricingConnection: form.pricingConnection,
      additionalInfo: form.additionalInfo.trim() || "Not specified",
      importFromAirbnb: false,
      status: "draft",
      onboardingSource: "airbnb_manual",
      minPrice,
      maxPrice,
      pricingHorizon,
      manualFacts: form,
      forecast: buildForecast(basePrice),
    };

    setSaving(true);
    try {
      await saveDraftProperty({ accountId: session.id, property });
      saveStoredJson(DRAFT_KEY, {
        accountId: session.id,
        propertyId,
        propertyType: "airbnb",
        minPrice,
        maxPrice,
        pricingHorizon,
      });
      router.push(`/properties/new/airbnb/run?propertyId=${encodeURIComponent(propertyId)}`);
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <WizardFrame view="manual" session={session}>
      <form className="property-form wizard-form panel" onSubmit={submit}>
        <TextField label="Property name" value={form.name} onChange={(event) => update("name", event.target.value)} fullWidth />
        <TextField select label="Property type" value={form.propertyType} onChange={(event) => update("propertyType", event.target.value)} fullWidth required>
          <MenuItem value="Airbnb">Airbnb</MenuItem>
        </TextField>
        <TextField label="Room count" type="number" value={form.roomCount} onChange={(event) => update("roomCount", event.target.value)} slotProps={{ htmlInput: { min: 1, max: 500 } }} fullWidth required />
        <div className="suggest-field">
          <TextField
            label="ZIP code"
            value={form.zipCode}
            onChange={(event) => {
              handleZipCodeChange(event.target.value);
              setIsZipMenuOpen(true);
            }}
            onFocus={() => setIsZipMenuOpen(true)}
            onBlur={() => setTimeout(() => setIsZipMenuOpen(false), 120)}
            required
            error={Boolean(zipCodeError)}
            helperText={zipCodeError || form.location || "Choose or enter a United States ZIP code."}
            fullWidth
          />
          {isZipMenuOpen ? (
            <div className="suggest-menu">
              {zipCodeOptions
                .filter((option) => `${option.zipCode} ${option.location}`.toLowerCase().includes(form.zipCode.toLowerCase()))
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
          <TextField label="Minimum guests" type="number" value={form.minGuests} onChange={(event) => update("minGuests", event.target.value)} slotProps={{ htmlInput: { min: 1, max: 30 } }} required />
          <TextField label="Maximum guests" type="number" value={form.maxGuests} onChange={(event) => update("maxGuests", event.target.value)} slotProps={{ htmlInput: { min: 1, max: 30 } }} required />
        </div>
        <div className="form-pair">
          <TextField select label="Bathroom" value={form.bathroom} onChange={(event) => update("bathroom", event.target.value)} required>
            <MenuItem value="Private">Private</MenuItem>
            <MenuItem value="Shared">Shared</MenuItem>
          </TextField>
          <div className="suggest-field">
            <TextField
              label="Pricing plan length"
              value={form.planDays}
              onChange={(event) => {
                update("planDays", event.target.value);
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
                      update("planDays", option);
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
        <TextField label="Street address" value={form.streetAddress} onChange={(event) => update("streetAddress", event.target.value)} />
        <div className="form-pair">
          <TextField label="Number of beds" type="number" value={form.beds} onChange={(event) => update("beds", event.target.value)} slotProps={{ htmlInput: { min: 0 } }} />
          <TextField select label="Bed size" value={form.bedSize} onChange={(event) => update("bedSize", event.target.value)}>
            <MenuItem value="">Not specified</MenuItem>
            <MenuItem value="Twin">Twin</MenuItem>
            <MenuItem value="Full">Full</MenuItem>
            <MenuItem value="Queen">Queen</MenuItem>
            <MenuItem value="King">King</MenuItem>
          </TextField>
        </div>
        <div className="amenity-grid">
          <FormControlLabel control={<Checkbox checked={form.fridge} onChange={(event) => update("fridge", event.target.checked)} />} label="Fridge" />
          <FormControlLabel control={<Checkbox checked={form.washer} onChange={(event) => update("washer", event.target.checked)} />} label="Washer" />
          <FormControlLabel control={<Checkbox checked={form.dryer} onChange={(event) => update("dryer", event.target.checked)} />} label="Dryer" />
          <FormControlLabel control={<Checkbox checked={form.parking} onChange={(event) => update("parking", event.target.checked)} />} label="Parking" />
          <FormControlLabel control={<Checkbox checked={form.microwave} onChange={(event) => update("microwave", event.target.checked)} />} label="Microwave" />
        </div>
        <div className="form-pair">
          <TextField label="Minimum acceptable price" type="number" value={form.minPrice} onChange={(event) => update("minPrice", event.target.value)} required />
          <TextField label="Maximum acceptable price" type="number" value={form.maxPrice} onChange={(event) => update("maxPrice", event.target.value)} required />
        </div>
        <TextField label="Additional information" value={form.additionalInfo} onChange={(event) => update("additionalInfo", event.target.value)} multiline rows={4} />
        {error ? <div className="form-error">{error}</div> : null}
        <div className="wizard-actions">
          <button type="button" className="secondary-button compact-button" onClick={() => router.push("/properties/new/airbnb/source")}>Back</button>
          <button type="submit" className="primary-action" disabled={saving}>
            {saving ? "Saving…" : "Save draft and run agent"}
            <ArrowRightIcon width={14} height={14} />
          </button>
        </div>
      </form>
    </WizardFrame>
  );
}

function RunStep({ session, initialPropertyId, initialRunId = "" }) {
  const router = useRouter();
  const [propertyId] = useState(initialPropertyId);
  const [draft, setDraft] = useState(null);
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  const [stopOpen, setStopOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const startedRef = useRef(false);
  const activatedRef = useRef(false);
  const latestRunIdRef = useRef(initialRunId);
  const canStopRun = Boolean(run?.runId) && !["completed", "failed", "stopped"].includes(run?.status);

  useEffect(() => {
    const storedDraft = parseStoredJson(DRAFT_KEY);
    if (storedDraft?.propertyId && (!propertyId || storedDraft.propertyId === propertyId)) {
      queueMicrotask(() => {
        setDraft(storedDraft);
      });
      return;
    }

    if (propertyId && initialRunId) {
      queueMicrotask(() => {
        setDraft({
          accountId: session.id,
          propertyId,
          runId: initialRunId,
        });
      });
      return;
    }

    if (propertyId) {
      let cancelled = false;
      async function loadExistingRun() {
        try {
          const response = await fetch(`/api/agent-runs?propertyId=${encodeURIComponent(propertyId)}`);
          const payload = await readJsonResponse(response, "No active agent run was found for this property.");
          if (cancelled) return;
          latestRunIdRef.current = payload.runId;
          setDraft({
            accountId: session.id,
            propertyId,
            runId: payload.runId,
          });
        } catch (loadError) {
          if (!cancelled) setError(loadError.message);
        }
      }
      loadExistingRun();
      return () => {
        cancelled = true;
      };
    }

    queueMicrotask(() => {
      setError("No property draft was found. Go back and save the property details again.");
    });
    return undefined;
  }, [initialRunId, propertyId, session.id]);

  useEffect(() => {
    if (!draft || startedRef.current) return;
    if (draft.runId) {
      startedRef.current = true;
      latestRunIdRef.current = draft.runId;
      queueMicrotask(() => {
        setRun({
          runId: draft.runId,
          propertyId: draft.propertyId,
          status: "running",
        });
      });
      return;
    }
    startedRef.current = true;
    async function startRun() {
      try {
        const response = await fetch("/api/agent-runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        const payload = await readJsonResponse(response, "Failed to start agent run.");
        latestRunIdRef.current = payload.runId;
        setRun(payload);
        saveStoredJson(DRAFT_KEY, { ...draft, runId: payload.runId });
      } catch (runError) {
        setError(runError.message);
      }
    }
    startRun();
  }, [draft]);

  useEffect(() => {
    if (!run?.runId) return undefined;
    let cancelled = false;
    async function poll() {
      try {
        const response = await fetch(`/api/agent-runs/${encodeURIComponent(run.runId)}`);
        const payload = await readJsonResponse(response, "Failed to load agent progress.");
        if (cancelled) return;
        if (payload.runId) {
          latestRunIdRef.current = payload.runId;
        }
        setRun((current) => {
          const next = { ...current, ...payload };
          if (current?.status === "stopped") {
            next.status = "stopped";
          } else if (payload.status === "unknown" && current?.status === "running") {
            next.status = "running";
          }
          return next;
        });
        setEvents(payload.events || []);
      } catch (pollError) {
        if (!cancelled) setError(pollError.message);
      }
    }
    poll();
    const interval = window.setInterval(poll, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [run?.runId]);

  useEffect(() => {
    if (run?.status !== "completed" || !draft?.propertyId || activatedRef.current) return;
    activatedRef.current = true;
    fetch(`/api/properties/${encodeURIComponent(draft.propertyId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        accountId: session.id,
        data: {
          status: "active",
          activatedAt: new Date().toISOString(),
          activeAgentRunId: null,
          lastAgentRunId: latestRunIdRef.current || null,
          agentRunStatus: "completed",
        },
      }),
    })
      .then((response) => {
        if (!response.ok) throw new Error("Failed to activate property after agent run.");
        window.localStorage.removeItem(DRAFT_KEY);
      })
      .catch((activateError) => {
        setError(activateError.message);
      });
  }, [draft?.propertyId, run?.status, session.id]);

  async function stopRun(deleteDraft) {
    if (!run?.runId) return;
    setStopping(true);
    try {
      const stopResponse = await fetch(`/api/agent-runs/${encodeURIComponent(run.runId)}/stop`, { method: "POST" });
      const stoppedRun = await readJsonResponse(stopResponse, "Failed to stop agent run.");
      if (deleteDraft && draft?.propertyId) {
        await fetch(`/api/properties/${encodeURIComponent(draft.propertyId)}?accountId=${encodeURIComponent(session.id)}`, { method: "DELETE" });
        window.localStorage.removeItem(DRAFT_KEY);
        router.push("/");
        return;
      }
      if (draft?.propertyId) {
        await fetch(`/api/properties/${encodeURIComponent(draft.propertyId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            accountId: session.id,
            data: {
              activeAgentRunId: null,
              lastAgentRunId: run.runId,
              agentRunStatus: "stopped",
            },
          }),
        });
      }
      setRun((current) => ({ ...current, ...stoppedRun, status: "stopped" }));
      setStopOpen(false);
    } catch (stopError) {
      setError(stopError.message);
    } finally {
      setStopping(false);
    }
  }

  function goNext() {
    router.push("/");
  }

  return (
    <WizardFrame view="run" session={session}>
      <section className="agent-run-page">
        <header className="agent-run-header">
          <div>
            <h2 className="agent-thinking-title">
              <span className="agent-thinking-icon">
                <Image className="revy-avatar-image" src="/Revy.png" alt="" width={34} height={34} />
              </span>
              <span>Revy is thinking</span>
              <span className="agent-thinking-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            </h2>
          </div>
        </header>

        {error ? <div className="form-error">{error}</div> : null}

        <AgentRunPanels events={events} />

        {canStopRun ? (
          <button
            type="button"
            className="agent-run-floating-action is-stop"
            aria-label="Stop thinking"
            title="Stop thinking"
            disabled={!run?.runId}
            onClick={() => setStopOpen(true)}
          >
            <span>Stop Thinking</span>
          </button>
        ) : null}

        {run?.status === "completed" ? (
          <button
            type="button"
            className="agent-run-floating-action is-next"
            aria-label="Next"
            onClick={goNext}
          >
            <span>Next</span>
            <ArrowRightIcon width={16} height={16} />
          </button>
        ) : null}
      </section>

      <Dialog open={stopOpen} onClose={() => setStopOpen(false)}>
        <DialogTitle>Stop the agent?</DialogTitle>
        <DialogContent>
          The current agent process will be interrupted. You can keep the draft property or delete it and return to Overview.
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStopOpen(false)} disabled={stopping}>Cancel</Button>
          <Button onClick={() => stopRun(false)} disabled={stopping}>Stop and keep draft</Button>
          <Button color="error" variant="contained" onClick={() => stopRun(true)} disabled={stopping}>Stop and delete draft</Button>
        </DialogActions>
      </Dialog>
    </WizardFrame>
  );
}
