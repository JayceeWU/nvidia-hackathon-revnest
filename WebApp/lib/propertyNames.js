const AIRBNB_ROOM_RE = /\/rooms\/(\d+)/i;

function cleanText(value) {
  if (value === undefined || value === null) return "";
  return String(value).replace(/\s+/g, " ").trim();
}

function firstText(...values) {
  for (const value of values) {
    const text = cleanText(value);
    if (text) return text;
  }
  return "";
}

function airbnbRoomId(value) {
  const match = cleanText(value).match(AIRBNB_ROOM_RE);
  return match?.[1] || "";
}

function shortRoomSuffix(roomId) {
  const text = cleanText(roomId);
  if (!text) return "";
  return text.length > 4 ? text.slice(-4) : text;
}

function stripAirbnbTitleNoise(value) {
  let text = cleanText(value)
    .replace(/\s*[|]\s*Airbnb\s*$/i, "")
    .replace(/\s*[-]\s*Airbnb\s*$/i, "");

  const separators = [" - ", " | "];
  for (const separator of separators) {
    const parts = text.split(separator).map((part) => part.trim()).filter(Boolean);
    if (parts.length <= 1) continue;
    const rest = parts.slice(1).join(" ").toLowerCase();
    if (/\b(for rent|vacation rental|airbnb|united states|apartments?|homes?)\b/.test(rest)) {
      text = parts[0];
      break;
    }
  }

  return text.replace(/^airbnb\s*[:|-]\s*/i, "").trim();
}

function isPlaceholderValue(value) {
  const text = cleanText(value);
  if (!text) return true;
  if (/pending browser verification/i.test(text)) return true;
  if (/pending verification/i.test(text)) return true;
  if (/not specified/i.test(text)) return true;
  return false;
}

export function isPlaceholderAirbnbName(value, propertyId = "", roomId = "") {
  const text = cleanText(value);
  if (!text) return true;
  const lower = text.toLowerCase();
  const idText = cleanText(propertyId).toLowerCase();
  const roomText = cleanText(roomId);
  if (idText && lower === idText) return true;
  if (/^airbnb[-\s]+\d{6,}$/i.test(text)) return true;
  if (/^airbnb listing \d{1,6}$/i.test(text)) return true;
  if (/^airbnb stay(?:\s*-\s*listing \d{1,6})?$/i.test(text)) return true;
  if (roomText && text.includes(roomText) && roomText.length > 6) return true;
  return false;
}

function compactName(parts) {
  const output = [];
  const seen = new Set();
  for (const part of parts) {
    const text = cleanText(part);
    if (!text || isPlaceholderValue(text)) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    output.push(text);
    seen.add(key);
  }
  const joined = output.join(" - ");
  return joined.length > 96 ? `${joined.slice(0, 93).trim()}...` : joined;
}

export function humanReadableAirbnbPropertyName(input = {}) {
  const roomId = cleanText(input.roomId) || airbnbRoomId(input.airbnbUrl || input.myPlace || "");
  const currentName = cleanText(input.currentName || input.name);
  const listingTitle = stripAirbnbTitleNoise(
    firstText(input.listingTitle, input.listing_title, input.title, input.propertyTitle, input.property_title)
  );
  const location = firstText(
    input.neighborhood,
    input.city && input.state ? `${input.city}, ${input.state}` : "",
    input.city,
    input.location,
    input.market
  );
  const listingType = firstText(
    input.listingType,
    input.listing_type,
    input.roomType,
    input.room_type,
    input.spaceType,
    input.space_type,
    input.propertyCategory,
    input.property_category
  );
  const propertyId = cleanText(input.propertyId || input.id);

  if (currentName && !isPlaceholderAirbnbName(currentName, propertyId, roomId)) {
    return currentName;
  }

  const fromProfile = compactName([listingTitle, location, listingType]);
  if (fromProfile) return fromProfile;

  const suffix = shortRoomSuffix(roomId);
  if (location || listingType) {
    return compactName([location, listingType || "Airbnb Stay", suffix ? `Listing ${suffix}` : ""]);
  }

  return suffix ? `Airbnb Listing ${suffix}` : "Airbnb Stay";
}
