import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { humanReadableAirbnbPropertyName } from "@/lib/propertyNames";

function parseMoney(value) {
  if (value === undefined || value === null || value === "") return null;
  const numeric = Number(String(value).replace(/[$,]/g, ""));
  return Number.isFinite(numeric) ? numeric : null;
}

function parsePriceRange(value) {
  if (typeof value !== "string") return {};
  const match = value.match(/\$?([0-9][0-9,.]*)\s*-\s*\$?([0-9][0-9,.]*)/);
  if (!match) return {};
  return { minPrice: parseMoney(match[1]), maxPrice: parseMoney(match[2]) };
}

function priceToCents(value) {
  return Math.round(Number(value) * 100);
}

function centsToPrice(cents) {
  const dollars = Number(cents) / 100;
  return Number.isInteger(dollars) ? dollars : Number(dollars.toFixed(2));
}

function formatPrice(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function parsePricingHorizon(property) {
  const directValue = property.pricingHorizon ?? property.pricing_horizon;
  const direct = Number(directValue);
  if (Number.isInteger(direct) && direct >= 1 && direct <= 730) return direct;

  const duration = String(property.planDuration || "").match(/\d+/)?.[0];
  const parsedDuration = Number(duration);
  if (Number.isInteger(parsedDuration) && parsedDuration >= 1 && parsedDuration <= 730) return parsedDuration;

  return null;
}

function resolvePropertyPricing(property) {
  const range = parsePriceRange(property.priceRange);
  const minPrice = parseMoney(property.minPrice ?? property.min_price ?? range.minPrice);
  const maxPrice = parseMoney(property.maxPrice ?? property.max_price ?? range.maxPrice);
  const pricingHorizon = parsePricingHorizon(property);

  if (minPrice === null || maxPrice === null || pricingHorizon === null) {
    return { error: "minPrice, maxPrice, and pricingHorizon are required" };
  }

  const minPriceCents = priceToCents(minPrice);
  const maxPriceCents = priceToCents(maxPrice);
  if (minPriceCents < 0 || maxPriceCents < minPriceCents) {
    return { error: "maxPrice must be greater than or equal to minPrice" };
  }

  return { minPriceCents, maxPriceCents, pricingHorizon };
}

function firstDefined(object, keys) {
  for (const key of keys) {
    if (object[key] !== undefined) return object[key];
  }
  return undefined;
}

function parseOptionalNonNegativeInteger(value, fieldName) {
  if (value === undefined || value === null || value === "") return { value: null };
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) return { error: `${fieldName} must be a non-negative integer` };
  return { value: parsed };
}

function normalizeOptionalText(value) {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  return text || null;
}

function resolveMyPlace(property) {
  return normalizeOptionalText(property.myPlace ?? property.my_place ?? property.airbnbUrl ?? null);
}

function isAirbnbProperty(property) {
  const propertyType = String(property.propertyType ?? property.property_type ?? "").toLowerCase();
  const myPlace = resolveMyPlace(property);
  return propertyType.includes("airbnb") || /airbnb\.[^/]+\/rooms\//i.test(myPlace || "");
}

function resolveProfileFields(property) {
  const roomCount = parseOptionalNonNegativeInteger(firstDefined(property, ["roomCount", "room_count"]), "roomCount");
  const capacity = parseOptionalNonNegativeInteger(firstDefined(property, ["capacity"]), "capacity");
  if (roomCount.error) return { error: roomCount.error };
  if (capacity.error) return { error: capacity.error };

  return {
    roomCount: roomCount.value,
    capacity: capacity.value,
    zipCode: normalizeOptionalText(firstDefined(property, ["zipCode", "zip_code"])),
    county: normalizeOptionalText(firstDefined(property, ["county"])),
    state: normalizeOptionalText(firstDefined(property, ["state"])),
    city: normalizeOptionalText(firstDefined(property, ["city"])),
    bed: normalizeOptionalText(firstDefined(property, ["bed", "beds"])),
    bath: normalizeOptionalText(firstDefined(property, ["bath", "bathroom"])),
    otherInfo: normalizeOptionalText(firstDefined(property, ["otherInfo", "other_info"])),
  };
}

function withProfileData(propertyData, profile) {
  const next = { ...propertyData };
  if (profile.roomCount !== null) next.roomCount = profile.roomCount;
  if (profile.capacity !== null) next.capacity = profile.capacity;
  if (profile.zipCode) next.zipCode = profile.zipCode;
  if (profile.county) next.county = profile.county;
  if (profile.state) next.state = profile.state;
  if (profile.city) next.city = profile.city;
  if (profile.bed) {
    next.bed = profile.bed;
    if (next.beds === undefined || next.beds === null || next.beds === "") next.beds = profile.bed;
  }
  if (profile.bath) {
    next.bath = profile.bath;
    if (next.bathroom === undefined || next.bathroom === null || next.bathroom === "") next.bathroom = profile.bath;
  }
  if (profile.otherInfo) next.otherInfo = profile.otherInfo;
  return next;
}

export async function POST(request) {
  const { accountId, property } = await request.json();

  if (!accountId || !property?.id) {
    return NextResponse.json({ error: "accountId and property.id are required" }, { status: 400 });
  }

  const pricing = resolvePropertyPricing(property);
  if (pricing.error) {
    return NextResponse.json({ error: pricing.error }, { status: 400 });
  }

  const { forecast = [], ...rawPropertyData } = property;
  const myPlace = resolveMyPlace(rawPropertyData);
  const profile = resolveProfileFields(rawPropertyData);
  if (profile.error) {
    return NextResponse.json({ error: profile.error }, { status: 400 });
  }
  const minPrice = centsToPrice(pricing.minPriceCents);
  const maxPrice = centsToPrice(pricing.maxPriceCents);
  let propertyData = withProfileData(
    {
      ...rawPropertyData,
      minPrice,
      maxPrice,
      pricingHorizon: pricing.pricingHorizon,
      planDuration: rawPropertyData.planDuration || `${pricing.pricingHorizon} days`,
      priceRange: rawPropertyData.priceRange || `$${formatPrice(minPrice)}-$${formatPrice(maxPrice)}`,
      ...(myPlace ? { myPlace } : {}),
    },
    profile
  );

  if (isAirbnbProperty(propertyData)) {
    propertyData = {
      ...propertyData,
      name: humanReadableAirbnbPropertyName({
        ...propertyData,
        propertyId: property.id,
        currentName: propertyData.name,
        airbnbUrl: propertyData.airbnbUrl || myPlace,
        myPlace,
      }),
      displayNameSource: propertyData.displayNameSource || "airbnb_human_readable",
    };
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const saveResult = await client.query(
      `
        INSERT INTO property (
          id, account_id, min_price_cents, max_price_cents, pricing_horizon, my_place,
          room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data
        )
        VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::jsonb)
        ON CONFLICT (id)
        DO UPDATE SET
          min_price_cents = EXCLUDED.min_price_cents,
          max_price_cents = EXCLUDED.max_price_cents,
          pricing_horizon = EXCLUDED.pricing_horizon,
          my_place = EXCLUDED.my_place,
          room_count = EXCLUDED.room_count,
          capacity = EXCLUDED.capacity,
          zip_code = EXCLUDED.zip_code,
          county = EXCLUDED.county,
          state = EXCLUDED.state,
          city = EXCLUDED.city,
          bed = EXCLUDED.bed,
          bath = EXCLUDED.bath,
          other_info = EXCLUDED.other_info,
          data = EXCLUDED.data,
          updated_at = now()
        WHERE property.account_id = EXCLUDED.account_id
      `,
      [
        property.id,
        accountId,
        pricing.minPriceCents,
        pricing.maxPriceCents,
        pricing.pricingHorizon,
        myPlace,
        profile.roomCount,
        profile.capacity,
        profile.zipCode,
        profile.county,
        profile.state,
        profile.city,
        profile.bed,
        profile.bath,
        profile.otherInfo,
        JSON.stringify(propertyData),
      ]
    );

    if (saveResult.rowCount === 0) {
      throw new Error("This property id already belongs to another account. Start a fresh add-property flow and try again.");
    }

    await client.query("DELETE FROM property_price WHERE property_id = $1", [property.id]);

    if (forecast.length > 0) {
      const values = [];
      const placeholders = forecast.map((point, index) => {
        values.push(property.id, `2026-05-${String(index + 10).padStart(2, "0")}`, priceToCents(point.fixed), priceToCents(point.agent));
        const offset = index * 4;
        return `($${offset + 1}, $${offset + 2}::date, $${offset + 3}, $${offset + 4})`;
      });

      await client.query(
        `
          INSERT INTO property_price (property_id, price_date, fixed_price_cents, agent_price_cents)
          VALUES ${placeholders.join(", ")}
        `,
        values
      );
    }

    await client.query("COMMIT");
    return NextResponse.json({ property: { ...propertyData, id: property.id, forecast } });
  } catch (error) {
    await client.query("ROLLBACK");
    const status = String(error.message || "").includes("already belongs to another account") ? 409 : 500;
    return NextResponse.json({ error: error.message || "Failed to save property" }, { status });
  } finally {
    client.release();
  }
}
