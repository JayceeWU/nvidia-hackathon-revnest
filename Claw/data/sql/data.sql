INSERT INTO account (id, email, password_hash, name, role, account_type) VALUES
  ('00000000-0000-0000-0000-000000000102', 'airbnb@revnest.ai', crypt('demo', gen_salt('bf')), 'Airbnb Host', 'host', 'airbnb'),
  ('00000000-0000-0000-0000-000000000103', 'hotel@revnest.ai', crypt('demo', gen_salt('bf')), 'Hotel Operator', 'host', 'hotel');

INSERT INTO external_account (id, account_id, data) VALUES
  (
    'hotel-pms-main',
    '00000000-0000-0000-0000-000000000103',
    $${
      "id": "hotel-pms-main",
      "name": "Hotel PMS Price Publisher",
      "provider": "Hotel pricing system",
      "accountId": "pms-dream-inn-95060",
      "status": "Connected",
      "connectedAt": "May 9, 2026 9:28 AM"
    }$$::jsonb
  );

INSERT INTO account_channel (id, account_id, data) VALUES
  (
    'discord',
    '00000000-0000-0000-0000-000000000103',
    $${
      "id": "discord",
      "name": "Discord",
      "accountId": "RevNest Ops Server",
      "status": "Connected",
      "connectedAt": "May 9, 2026 10:12 AM"
    }$$::jsonb
  );

INSERT INTO property (id, account_id, min_price_cents, max_price_cents, pricing_horizon, room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data) VALUES
  (
    'dream-inn-standard-king',
    '00000000-0000-0000-0000-000000000103',
    14000,
    70000,
    3,
    16,
    2,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '1 King',
    'Private',
    'Standard Dream Inn Santa Cruz oceanfront inventory with beach access, restaurant, pool, and baseline RMS history for a lower-tier king room.',
    $${
            "id": "dream-inn-standard-king",
            "name": "Standard King",
            "propertyType": "Hotel Room Type",
            "roomType": "Standard King",
            "roomCount": 16,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-2 guests",
            "bathroom": "Private",
            "beds": "1 bed",
            "bedSize": "King",
            "amenities": [
                  "Oceanfront",
                  "Beach access",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 323,
            "agentAdr": 323,
            "adr": "$323",
            "revpar": "$233",
            "occupancy": "72%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 140,
            "maxPrice": 700,
            "priceRange": "$140-$700",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 2,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "1 King",
            "bath": "Private",
            "otherInfo": "Standard Dream Inn Santa Cruz oceanfront inventory with beach access, restaurant, pool, and baseline RMS history for a lower-tier king room."
      }$$::jsonb
  ),
  (
    'dream-inn-standard-two-queen',
    '00000000-0000-0000-0000-000000000103',
    16000,
    75000,
    3,
    20,
    4,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '2 Two Queen',
    'Private',
    'Standard Dream Inn Santa Cruz oceanfront inventory with beach access, restaurant, pool, and family-friendly two-queen configuration.',
    $${
            "id": "dream-inn-standard-two-queen",
            "name": "Standard Two Queen",
            "propertyType": "Hotel Room Type",
            "roomType": "Standard Two Queen",
            "roomCount": 20,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-4 guests",
            "bathroom": "Private",
            "beds": "2 beds",
            "bedSize": "Two Queen",
            "amenities": [
                  "Oceanfront",
                  "Beach access",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 350,
            "agentAdr": 350,
            "adr": "$350",
            "revpar": "$256",
            "occupancy": "73%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 160,
            "maxPrice": 750,
            "priceRange": "$160-$750",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 4,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "2 Two Queen",
            "bath": "Private",
            "otherInfo": "Standard Dream Inn Santa Cruz oceanfront inventory with beach access, restaurant, pool, and family-friendly two-queen configuration."
      }$$::jsonb
  ),
  (
    'dream-inn-ocean-view-king',
    '00000000-0000-0000-0000-000000000103',
    18000,
    90000,
    3,
    38,
    2,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '1 King',
    'Private',
    'Ocean-view Dream Inn Santa Cruz room type with beach access, restaurant, pool, and broad king inventory supported by RMS demand history.',
    $${
            "id": "dream-inn-ocean-view-king",
            "name": "Ocean View King",
            "propertyType": "Hotel Room Type",
            "roomType": "Ocean View King",
            "roomCount": 38,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-2 guests",
            "bathroom": "Private",
            "beds": "1 bed",
            "bedSize": "King",
            "amenities": [
                  "Ocean view",
                  "Beach access",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 419,
            "agentAdr": 419,
            "adr": "$419",
            "revpar": "$289",
            "occupancy": "69%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 180,
            "maxPrice": 900,
            "priceRange": "$180-$900",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 2,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "1 King",
            "bath": "Private",
            "otherInfo": "Ocean-view Dream Inn Santa Cruz room type with beach access, restaurant, pool, and broad king inventory supported by RMS demand history."
      }$$::jsonb
  ),
  (
    'dream-inn-ocean-view-two-queen',
    '00000000-0000-0000-0000-000000000103',
    20000,
    95000,
    3,
    42,
    4,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '2 Two Queen',
    'Private',
    'Ocean-view Dream Inn Santa Cruz room type with beach access, restaurant, pool, and the largest two-queen inventory for family or group demand.',
    $${
            "id": "dream-inn-ocean-view-two-queen",
            "name": "Ocean View Two Queen",
            "propertyType": "Hotel Room Type",
            "roomType": "Ocean View Two Queen",
            "roomCount": 42,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-4 guests",
            "bathroom": "Private",
            "beds": "2 beds",
            "bedSize": "Two Queen",
            "amenities": [
                  "Ocean view",
                  "Beach access",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 460,
            "agentAdr": 460,
            "adr": "$460",
            "revpar": "$327",
            "occupancy": "71%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 200,
            "maxPrice": 950,
            "priceRange": "$200-$950",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 4,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "2 Two Queen",
            "bath": "Private",
            "otherInfo": "Ocean-view Dream Inn Santa Cruz room type with beach access, restaurant, pool, and the largest two-queen inventory for family or group demand."
      }$$::jsonb
  ),
  (
    'dream-inn-beachfront-king',
    '00000000-0000-0000-0000-000000000103',
    23000,
    110000,
    3,
    20,
    2,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '1 King',
    'Private',
    'Beachfront Dream Inn Santa Cruz king room with direct oceanfront positioning, beach access, restaurant, pool, and premium leisure appeal.',
    $${
            "id": "dream-inn-beachfront-king",
            "name": "Beachfront King",
            "propertyType": "Hotel Room Type",
            "roomType": "Beachfront King",
            "roomCount": 20,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-2 guests",
            "bathroom": "Private",
            "beds": "1 bed",
            "bedSize": "King",
            "amenities": [
                  "Beachfront",
                  "Ocean view",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 529,
            "agentAdr": 529,
            "adr": "$529",
            "revpar": "$365",
            "occupancy": "69%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 230,
            "maxPrice": 1100,
            "priceRange": "$230-$1100",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 2,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "1 King",
            "bath": "Private",
            "otherInfo": "Beachfront Dream Inn Santa Cruz king room with direct oceanfront positioning, beach access, restaurant, pool, and premium leisure appeal."
      }$$::jsonb
  ),
  (
    'dream-inn-beachfront-two-queen',
    '00000000-0000-0000-0000-000000000103',
    25000,
    115000,
    3,
    16,
    4,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '2 Two Queen',
    'Private',
    'Beachfront Dream Inn Santa Cruz two-queen room with direct oceanfront positioning, beach access, restaurant, pool, and strong family appeal.',
    $${
            "id": "dream-inn-beachfront-two-queen",
            "name": "Beachfront Two Queen",
            "propertyType": "Hotel Room Type",
            "roomType": "Beachfront Two Queen",
            "roomCount": 16,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-4 guests",
            "bathroom": "Private",
            "beds": "2 beds",
            "bedSize": "Two Queen",
            "amenities": [
                  "Beachfront",
                  "Ocean view",
                  "Restaurant",
                  "Pool"
            ],
            "fixedPrice": 569,
            "agentAdr": 569,
            "adr": "$569",
            "revpar": "$398",
            "occupancy": "70%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 250,
            "maxPrice": 1150,
            "priceRange": "$250-$1150",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 4,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "2 Two Queen",
            "bath": "Private",
            "otherInfo": "Beachfront Dream Inn Santa Cruz two-queen room with direct oceanfront positioning, beach access, restaurant, pool, and strong family appeal."
      }$$::jsonb
  ),
  (
    'dream-inn-premium-ocean-view-king',
    '00000000-0000-0000-0000-000000000103',
    28000,
    125000,
    3,
    5,
    2,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '1 King',
    'Private',
    'Limited premium ocean-view Dream Inn Santa Cruz king inventory with elevated view tier, beach access, restaurant, and pool amenities.',
    $${
            "id": "dream-inn-premium-ocean-view-king",
            "name": "Premium Ocean View King",
            "propertyType": "Hotel Room Type",
            "roomType": "Premium Ocean View King",
            "roomCount": 5,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-2 guests",
            "bathroom": "Private",
            "beds": "1 bed",
            "bedSize": "King",
            "amenities": [
                  "Premium view",
                  "Ocean view",
                  "Beach access",
                  "Restaurant"
            ],
            "fixedPrice": 631,
            "agentAdr": 631,
            "adr": "$631",
            "revpar": "$423",
            "occupancy": "67%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 280,
            "maxPrice": 1250,
            "priceRange": "$280-$1250",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 2,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "1 King",
            "bath": "Private",
            "otherInfo": "Limited premium ocean-view Dream Inn Santa Cruz king inventory with elevated view tier, beach access, restaurant, and pool amenities."
      }$$::jsonb
  ),
  (
    'dream-inn-premium-ocean-view-two-queen',
    '00000000-0000-0000-0000-000000000103',
    31000,
    130000,
    3,
    3,
    4,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '2 Two Queen',
    'Private',
    'Very limited premium ocean-view Dream Inn Santa Cruz two-queen inventory with elevated view tier, beach access, restaurant, and pool amenities.',
    $${
            "id": "dream-inn-premium-ocean-view-two-queen",
            "name": "Premium Ocean View Two Queen",
            "propertyType": "Hotel Room Type",
            "roomType": "Premium Ocean View Two Queen",
            "roomCount": 3,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-4 guests",
            "bathroom": "Private",
            "beds": "2 beds",
            "bedSize": "Two Queen",
            "amenities": [
                  "Premium view",
                  "Ocean view",
                  "Beach access",
                  "Restaurant"
            ],
            "fixedPrice": 670,
            "agentAdr": 670,
            "adr": "$670",
            "revpar": "$449",
            "occupancy": "67%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 310,
            "maxPrice": 1300,
            "priceRange": "$310-$1300",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 4,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "2 Two Queen",
            "bath": "Private",
            "otherInfo": "Very limited premium ocean-view Dream Inn Santa Cruz two-queen inventory with elevated view tier, beach access, restaurant, and pool amenities."
      }$$::jsonb
  ),
  (
    'dream-inn-beachfront-suite',
    '00000000-0000-0000-0000-000000000103',
    42000,
    190000,
    3,
    5,
    4,
    '95060',
    'Santa Cruz County',
    'CA',
    'Santa Cruz',
    '2 King + Queen Sleeper Sofa',
    'Private',
    'Beachfront Dream Inn Santa Cruz suite product with oceanfront positioning, suite layout, beach access, restaurant, pool, and highest ADR tier.',
    $${
            "id": "dream-inn-beachfront-suite",
            "name": "Beachfront Suite",
            "propertyType": "Hotel Room Type",
            "roomType": "Beachfront Suite",
            "roomCount": 5,
            "zipCode": "95060",
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": "1-4 guests",
            "bathroom": "Private",
            "beds": "2 beds",
            "bedSize": "King + Queen Sleeper Sofa",
            "amenities": [
                  "Beachfront",
                  "Suite",
                  "Ocean view",
                  "Restaurant"
            ],
            "fixedPrice": 923,
            "agentAdr": 923,
            "adr": "$923",
            "revpar": "$600",
            "occupancy": "65%",
            "revparLift": "Baseline from RMS history",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": 420,
            "maxPrice": 1900,
            "priceRange": "$420-$1900",
            "pricingConnection": "hotel-pms-main",
            "source": "dream_inn_santa_cruz_rms_room_level_2024-06-06_to_2026-05-15.csv",
            "capacity": 4,
            "county": "Santa Cruz County",
            "state": "CA",
            "city": "Santa Cruz",
            "bed": "2 King + Queen Sleeper Sofa",
            "bath": "Private",
            "otherInfo": "Beachfront Dream Inn Santa Cruz suite product with oceanfront positioning, suite layout, beach access, restaurant, pool, and highest ADR tier."
      }$$::jsonb
  );

INSERT INTO pricing_record (id, account_id, record_type, data) VALUES
  (
    'task-dream-inn-001',
    '00000000-0000-0000-0000-000000000103',
    'pending_task',
    $${
      "id": "task-dream-inn-001",
      "property": "Ocean View Two Queen",
      "priceDate": "May 17, 2026",
      "type": "Increase",
      "currentPrice": "$460",
      "agentSuggestedPrice": "$515",
      "change": "+12%",
      "agentSuggestedAt": "May 9, 2026 12:39 PM",
      "reason": "Dream Inn RMS history shows strong four-guest ocean-view demand, so Revy recommends a guarded short-horizon lift.",
      "action": "Review 3-day guardrail update",
      "status": "Needs approval"
    }$$::jsonb
  ),
  (
    'task-dream-inn-002',
    '00000000-0000-0000-0000-000000000103',
    'pending_task',
    $${
      "id": "task-dream-inn-002",
      "property": "Beachfront Suite",
      "priceDate": "May 18, 2026",
      "type": "Increase",
      "currentPrice": "$923",
      "agentSuggestedPrice": "$1040",
      "change": "+13%",
      "agentSuggestedAt": "May 9, 2026 12:52 PM",
      "reason": "The suite inventory is limited and historical beachfront suite rates support a higher protected ceiling.",
      "action": "Accept guarded rate",
      "status": "Needs approval"
    }$$::jsonb
  ),
  (
    'task-dream-inn-003',
    '00000000-0000-0000-0000-000000000103',
    'pending_task',
    $${
      "id": "task-dream-inn-003",
      "property": "Standard King",
      "priceDate": "May 19, 2026",
      "type": "Decrease",
      "currentPrice": "$323",
      "agentSuggestedPrice": "$305",
      "change": "-6%",
      "agentSuggestedAt": "May 9, 2026 1:06 PM",
      "reason": "Standard King has the broadest guardrail headroom and can use a small weekday discount without crossing the saved floor.",
      "action": "Review discount",
      "status": "Waiting"
    }$$::jsonb
  ),
  (
    'log-dream-inn-001',
    '00000000-0000-0000-0000-000000000103',
    'price_log',
    $${
      "id": "log-dream-inn-001",
      "property": "Beachfront King",
      "priceDate": "May 15, 2026",
      "type": "Increase",
      "oldPrice": "$529",
      "newPrice": "$585",
      "agentSuggestedPrice": "$585",
      "change": "+11%",
      "agentSuggestedAt": "May 8, 2026 3:52 PM",
      "adjustedAt": "May 8, 2026 4:05 PM",
      "reason": "Beachfront King historical highs supported a controlled near-term lift inside the $230-$1100 guardrail.",
      "agentSignals": ["Beachfront room history", "3-day pricing horizon", "Guardrails preserved"]
    }$$::jsonb
  ),
  (
    'log-dream-inn-002',
    '00000000-0000-0000-0000-000000000103',
    'price_log',
    $${
      "id": "log-dream-inn-002",
      "property": "Premium Ocean View Two Queen",
      "priceDate": "May 14, 2026",
      "type": "Increase",
      "oldPrice": "$670",
      "newPrice": "$735",
      "agentSuggestedPrice": "$735",
      "change": "+10%",
      "agentSuggestedAt": "May 8, 2026 2:18 PM",
      "adjustedAt": "May 8, 2026 2:31 PM",
      "reason": "Only three rooms exist in this type, so scarcity supports premium pricing while staying below the rounded historical cap.",
      "agentSignals": ["Limited room count", "Ocean-view premium", "Max guardrail preserved"]
    }$$::jsonb
  ),
  (
    'log-dream-inn-003',
    '00000000-0000-0000-0000-000000000103',
    'price_log',
    $${
      "id": "log-dream-inn-003",
      "property": "Standard Two Queen",
      "priceDate": "May 13, 2026",
      "type": "Decrease",
      "oldPrice": "$350",
      "newPrice": "$335",
      "agentSuggestedPrice": "$335",
      "change": "-4%",
      "agentSuggestedAt": "May 7, 2026 4:22 PM",
      "adjustedAt": "May 7, 2026 4:34 PM",
      "reason": "Revy trimmed the lower-tier two-queen rate for a soft weekday while keeping the $160 floor intact.",
      "agentSignals": ["Weekday demand", "Room-type history", "Minimum guardrail preserved"]
    }$$::jsonb
  );


INSERT INTO hotel_home_dashboard (id, account_id, data) VALUES
  (
    'home',
    '00000000-0000-0000-0000-000000000103',
    $${
      "demandSignals": {
        "weather": {
          "location": "Santa Cruz, CA",
          "summary": "Partly cloudy, mild",
          "high_f": 68,
          "low_f": 55,
          "precip_pct": 12,
          "trend": "neutral",
          "impactTrend": "flat",
          "footnote": "No major impact",
          "days": [
            {"day": "Fri", "high": 67, "conditions": "partly cloudy"},
            {"day": "Sat", "high": 69, "conditions": "sunny"},
            {"day": "Sun", "high": 68, "conditions": "partly cloudy"}
          ]
        },
        "events": {
          "location": "Santa Cruz",
          "upcoming_count": 4,
          "headline": "Increasing Demand",
          "trend": "up",
          "footnote": "Pushes price up",
          "next": []
        },
        "competitor": {
          "location": "Santa Cruz, CA",
          "median_rate": 238,
          "delta_pct": 3,
          "sample_size": 5,
          "trend": "up"
        },
        "occupancy": {
          "portfolio_rate": 0.81,
          "delta_vs_last_month_pct": 4,
          "booked_room_nights": 84,
          "available_room_nights": 104,
          "trend": "up"
        }
      }
    }$$::jsonb
  );

INSERT INTO revy_state (account_id, data, updated_at) VALUES
  (
    '00000000-0000-0000-0000-000000000102',
    $${
      "status": "thinking",
      "model": "nemotron3:33b",
      "headline": "Reviewing the first Airbnb listing setup path and waiting for a property to price.",
      "updatedAt": "May 15, 2026 7:20 PM",
      "events": [
        {"timestamp": "2026-05-15T19:18:00.000Z", "stage": "context", "tool": "agent-browser", "status": "completed", "message": "Loaded account context for Airbnb Host."},
        {"timestamp": "2026-05-15T19:18:20.000Z", "stage": "guardrail_review", "tool": "guardrail_review.py", "status": "completed", "message": "Waiting for property guardrails before pricing."},
        {"timestamp": "2026-05-15T19:19:02.000Z", "stage": "pricing_decision", "tool": "pricing decision", "status": "info", "message": "Ready to evaluate the first listing after it is added."}
      ],
      "messages": [
        {"role": "agent", "text": "I am ready to price the first Airbnb listing once it is added.", "at": "May 15, 2026 7:20 PM"}
      ]
    }$$::jsonb,
    '2026-05-15T19:20:00Z'
  ),
  (
    '00000000-0000-0000-0000-000000000103',
    $${
      "status": "thinking",
      "model": "nemotron3:33b",
      "headline": "Comparing Dream Inn Santa Cruz room-type guardrails for the next 3 days.",
      "updatedAt": "May 15, 2026 7:21 PM",
      "events": [
        {"timestamp": "2026-05-15T19:17:00.000Z", "stage": "context", "tool": "agent-browser", "status": "completed", "message": "Loaded nine Dream Inn Santa Cruz room types and active PMS connection."},
        {"timestamp": "2026-05-15T19:17:26.000Z", "stage": "market_data_parallel", "tool": "parallel market data", "status": "completed", "message": "Merged local demand, room inventory, and RMS history signals."},
        {"timestamp": "2026-05-15T19:17:44.000Z", "stage": "hotel_history", "tool": "dream_inn RMS", "status": "completed", "message": "Summarized historical room-type price ranges without time-series output."},
        {"timestamp": "2026-05-15T19:18:31.000Z", "stage": "pricing_decision", "tool": "pricing decision", "status": "info", "message": "Preparing guarded 3-day recommendations for pending approval."}
      ],
      "messages": [
        {"role": "agent", "text": "I am using Dream Inn room-level history to keep the next 3-day recommendations inside each room type's saved guardrails.", "at": "May 15, 2026 7:21 PM"}
      ]
    }$$::jsonb,
    '2026-05-15T19:21:00Z'
  );

INSERT INTO revy_conversation (id, account_id, property_id, title, final_message_at, data) VALUES
  (
    'airbnb-revy-001',
    '00000000-0000-0000-0000-000000000102',
    NULL,
    'Airbnb onboarding readiness',
    '2026-05-15T18:42:00Z',
    $${
      "summary": "Revy explained what it will inspect once the first Airbnb URL is added.",
      "messages": [
        {"role": "user", "text": "What will you need before pricing my first listing?", "at": "May 15, 2026 6:38 PM"},
        {"role": "agent", "text": "I need the listing URL, min and max guardrails, the pricing horizon, and any host notes that should influence risk tolerance.", "at": "May 15, 2026 6:42 PM"}
      ]
    }$$::jsonb
  ),
  (
    'hotel-revy-001',
    '00000000-0000-0000-0000-000000000103',
    'dream-inn-ocean-view-two-queen',
    'Ocean-view two-queen guardrails',
    '2026-05-15T18:55:00Z',
    $${
      "summary": "Revy reviewed Dream Inn two-queen room history and explained the rounded $200-$950 guardrail.",
      "messages": [
        {"role": "user", "text": "Why is Ocean View Two Queen getting a higher recommendation?", "at": "May 15, 2026 6:49 PM"},
        {"role": "agent", "text": "This room type has the largest inventory and strong four-guest demand, so a moderate increase still sits comfortably inside the saved 3-day guardrail.", "at": "May 15, 2026 6:55 PM"}
      ]
    }$$::jsonb
  ),
  (
    'hotel-revy-002',
    '00000000-0000-0000-0000-000000000103',
    'dream-inn-standard-king',
    'Standard King weekday floor',
    '2026-05-14T21:10:00Z',
    $${
      "summary": "Revy explained a small weekday discount for Standard King while preserving the $140 floor.",
      "messages": [
        {"role": "user", "text": "Is the Standard King discount too aggressive?", "at": "May 14, 2026 9:02 PM"},
        {"role": "agent", "text": "No. The change is small compared with the historical range, and the rounded minimum guardrail remains intact.", "at": "May 14, 2026 9:10 PM"}
      ]
    }$$::jsonb
  ),
  (
    'hotel-revy-003',
    '00000000-0000-0000-0000-000000000103',
    'dream-inn-beachfront-suite',
    'Beachfront Suite ceiling',
    '2026-05-13T16:35:00Z',
    $${
      "summary": "Revy confirmed that Beachfront Suite recommendations should remain approval-based inside the $420-$1900 guardrail.",
      "messages": [
        {"role": "user", "text": "Can the suite move above $1000 for the next few days?", "at": "May 13, 2026 4:28 PM"},
        {"role": "agent", "text": "Yes, but I will keep the update pending for approval. The room type has only five rooms and historical suite rates support the higher ceiling.", "at": "May 13, 2026 4:35 PM"}
      ]
    }$$::jsonb
  ),
  (
    'hotel-revy-004',
    '00000000-0000-0000-0000-000000000103',
    'dream-inn-premium-ocean-view-two-queen',
    'Premium two-queen scarcity',
    '2026-05-12T18:20:00Z',
    $${
      "summary": "Revy explained how the three-room premium two-queen type supports a higher guarded ADR.",
      "messages": [
        {"role": "user", "text": "Why does Premium Ocean View Two Queen have the highest two-queen cap?", "at": "May 12, 2026 6:12 PM"},
        {"role": "agent", "text": "There are only three rooms in that type, and historical premium ocean-view rates justify a higher max while still protecting conversion with a 3-day horizon.", "at": "May 12, 2026 6:20 PM"}
      ]
    }$$::jsonb
  ),
  (
    'hotel-revy-005',
    '00000000-0000-0000-0000-000000000103',
    'dream-inn-beachfront-king',
    'Beachfront King short-horizon lift',
    '2026-05-11T15:45:00Z',
    $${
      "summary": "Revy reviewed Beachfront King demand and kept the recommendation inside the $230-$1100 guardrail.",
      "messages": [
        {"role": "user", "text": "Can Beachfront King move up without hurting conversion?", "at": "May 11, 2026 3:37 PM"},
        {"role": "agent", "text": "Yes, because the proposed change is modest relative to its historical range and uses a short 3-day horizon.", "at": "May 11, 2026 3:45 PM"}
      ]
    }$$::jsonb
  );
