// =============================================================================
// mongo_queries.js
// Savannah Crest Hotels: MongoDB 7.0 Operational Queries & Aggregations
// Portfolio 4: NoSQL and Advanced Data Models
//
// Can be executed directly in mongosh or MongoDB Compass:
// mongosh "mongodb://mongo_admin:changeme_mongo_2024@localhost:27017/savannah_crest_nosql?authSource=admin" mongo_queries.js
// =============================================================================

const dbName = 'savannah_crest_nosql';
const db = db.getSiblingDB(dbName);

print(`\n==================================================================`);
print(`Savannah Crest Hotels - MongoDB Queries & Aggregations Suite`);
print(`==================================================================\n`);

// -----------------------------------------------------------------------------
// 1. FILTERED FIND QUERIES
// -----------------------------------------------------------------------------

// Q1: Find Nigerian Platinum Loyalty Tier Guests
print(`--- Q1: Nigerian Platinum Guests ---`);
const q1 = db.guest_profiles.find(
  { nationality: "Nigerian", loyalty_tier: "Platinum" },
  { _id: 0, first_name: 1, last_name: 1, email: 1, "stats.total_spent": 1 }
).limit(5);
printjson(q1.toArray());

// Q2: Multikey Search: Find guests with historic stays in Kano
print(`\n--- Q2: Guests who stayed in Kano ---`);
const q2 = db.guest_profiles.find(
  { "bookings.city": "Kano" },
  { _id: 0, first_name: 1, last_name: 1, loyalty_tier: 1, "stats.total_bookings": 1 }
).limit(5);
printjson(q2.toArray());

// Q3: Top Spenders Chain-Wide
print(`\n--- Q3: Top 5 Highest Spenders ---`);
const q3 = db.guest_profiles.find(
  {},
  {
    _id: 0,
    guest_id: 1,
    first_name: 1,
    last_name: 1,
    loyalty_tier: 1,
    "stats.total_spent": 1,
    "stats.preferred_hotel": 1
  }
).sort({ "stats.total_spent": -1 }).limit(5);
printjson(q3.toArray());

// -----------------------------------------------------------------------------
// 2. AGGREGATION PIPELINES
// -----------------------------------------------------------------------------

// Pipeline 1: Financial Analytics by City
print(`\n--- Aggregation 1: Revenue by Hotel City ---`);
const pipe1 = [
  { $unwind: "$bookings" },
  { $match: { "bookings.status": { $ne: "cancelled" } } },
  {
    $group: {
      _id: "$bookings.city",
      total_bookings: { $sum: 1 },
      total_revenue: { $sum: "$bookings.total_amount" },
      avg_booking_value: { $avg: "$bookings.total_amount" }
    }
  },
  { $sort: { total_revenue: -1 } }
];
printjson(db.guest_profiles.aggregate(pipe1).toArray());

// Pipeline 2: Room Type Popularity & Revenue Yield
print(`\n--- Aggregation 2: Room Type Popularity ---`);
const pipe2 = [
  { $unwind: "$bookings" },
  {
    $group: {
      _id: "$bookings.room_type",
      booking_count: { $sum: 1 },
      total_revenue: { $sum: "$bookings.total_amount" },
      avg_price_per_booking: { $avg: "$bookings.total_amount" }
    }
  },
  { $sort: { total_revenue: -1 } }
];
printjson(db.guest_profiles.aggregate(pipe2).toArray());

// Pipeline 3: Loyalty Tier Value Distribution
print(`\n--- Aggregation 3: Loyalty Tier Distribution ---`);
const pipe3 = [
  {
    $group: {
      _id: "$loyalty_tier",
      guest_count: { $sum: 1 },
      tier_total_spend: { $sum: "$stats.total_spent" },
      avg_spend_per_guest: { $avg: "$stats.total_spent" },
      avg_bookings_per_guest: { $avg: "$stats.total_bookings" }
    }
  },
  { $sort: { tier_total_spend: -1 } }
];
printjson(db.guest_profiles.aggregate(pipe3).toArray());

// Pipeline 4: Historical Yearly Trends
print(`\n--- Aggregation 4: Yearly Booking & Cancellation Trends ---`);
const pipe4 = [
  { $unwind: "$bookings" },
  {
    $project: {
      year: { $substr: ["$bookings.check_in", 0, 4] },
      amount: "$bookings.total_amount",
      status: "$bookings.status"
    }
  },
  {
    $group: {
      _id: "$year",
      total_bookings: { $sum: 1 },
      total_revenue: { $sum: "$amount" },
      cancellations: {
        $sum: { $cond: [{ $eq: ["$status", "cancelled"] }, 1, 0] }
      }
    }
  },
  { $sort: { _id: 1 } }
];
printjson(db.guest_profiles.aggregate(pipe4).toArray());

// Pipeline 5: Multi-level Payment Method Analysis
print(`\n--- Aggregation 5: Payment Method Settlement & Failure Rates ---`);
const pipe5 = [
  { $unwind: "$bookings" },
  { $unwind: "$bookings.payments" },
  {
    $group: {
      _id: "$bookings.payments.method",
      transaction_count: { $sum: 1 },
      total_settled: {
        $sum: {
          $cond: [
            { $eq: ["$bookings.payments.status", "completed"] },
            "$bookings.payments.amount",
            0
          ]
        }
      },
      failed_count: {
        $sum: {
          $cond: [
            { $eq: ["$bookings.payments.status", "failed"] },
            1,
            0
          ]
        }
      }
    }
  },
  { $sort: { transaction_count: -1 } }
];
printjson(db.guest_profiles.aggregate(pipe5).toArray());

