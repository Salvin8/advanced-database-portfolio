// =============================================================================
// mongo_schema.js
// Savannah Crest Hotels: MongoDB 7.0 Document Validation Schema & Indexes
// Portfolio 4: NoSQL and Advanced Data Models
//
// Usage: mongosh -u mongo_admin -p changeme_mongo_2024 --authenticationDatabase admin \
//        localhost:27017/savannah_crest_nosql mongo_schema.js
// =============================================================================

const dbName = 'savannah_crest_nosql';
const db = db.getSiblingDB(dbName);

print(`Configuring database: ${dbName}...`);

// Drop existing collection to re-apply schema validation cleanly if necessary
// (Comment out in production to prevent data loss)
// db.guest_profiles.drop();

// -----------------------------------------------------------------------------
// 1. Create collection with strict JSON Schema Validation
// -----------------------------------------------------------------------------
db.createCollection("guest_profiles", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["guest_id", "first_name", "last_name", "email", "loyalty_tier", "bookings", "stats"],
      properties: {
        guest_id: {
          bsonType: "int",
          description: "Relational foreign key reference to PostgreSQL guest.guest_id"
        },
        first_name: {
          bsonType: "string",
          description: "Guest given name (required)"
        },
        last_name: {
          bsonType: "string",
          description: "Guest family name (required)"
        },
        email: {
          bsonType: "string",
          pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
          description: "Unique email address for contact and login"
        },
        phone: {
          bsonType: ["string", "null"],
          description: "Contact phone number"
        },
        nationality: {
          bsonType: ["string", "null"],
          description: "Guest nationality"
        },
        loyalty_tier: {
          enum: ["Bronze", "Silver", "Gold", "Platinum"],
          description: "Calculated guest tier based on lifetime spend"
        },
        bookings: {
          bsonType: "array",
          description: "Embedded list of historic and active bookings",
          items: {
            bsonType: "object",
            required: ["booking_ref", "hotel_name", "city", "check_in", "check_out", "room_type", "total_amount", "status"],
            properties: {
              booking_ref: { bsonType: "string" },
              hotel_name: { bsonType: "string" },
              city: { bsonType: "string" },
              check_in: { bsonType: "string" },
              check_out: { bsonType: "string" },
              room_type: { bsonType: "string" },
              room_number: { bsonType: ["string", "null"] },
              total_amount: { bsonType: "number", minimum: 0 },
              status: {
                enum: ["pending", "confirmed", "checked_in", "checked_out", "cancelled", "no_show"]
              },
              payments: {
                bsonType: "array",
                description: "Embedded payment records for this booking",
                items: {
                  bsonType: "object",
                  required: ["amount", "method", "status"],
                  properties: {
                    amount: { bsonType: "number", minimum: 0 },
                    method: {
                      enum: ["card", "bank_transfer", "mobile_money", "cash"]
                    },
                    status: {
                      enum: ["pending", "completed", "failed", "refunded"]
                    },
                    transaction_ref: { bsonType: ["string", "null"] },
                    date: { bsonType: ["date", "string", "null"] }
                  }
                }
              }
            }
          }
        },
        stats: {
          bsonType: "object",
          required: ["total_bookings", "total_spent", "avg_stay_nights"],
          properties: {
            total_bookings: { bsonType: "int", minimum: 0 },
            total_spent: { bsonType: "number", minimum: 0 },
            avg_stay_nights: { bsonType: "number", minimum: 0 },
            preferred_hotel: { bsonType: ["string", "null"] },
            preferred_room_type: { bsonType: ["string", "null"] },
            first_visit: { bsonType: ["string", "null"] },
            last_visit: { bsonType: ["string", "null"] }
          }
        },
        created_at: { bsonType: ["date", "string"] },
        updated_at: { bsonType: ["date", "string"] }
      }
    }
  },
  validationLevel: "moderate", // Enforce on insert and updates to valid documents
  validationAction: "error"     // Reject documents that fail validation
});

print("Collection 'guest_profiles' initialized with JSON Schema validation.");

// -----------------------------------------------------------------------------
// 2. Create Optimized Indexes
// -----------------------------------------------------------------------------
print("Creating secondary and compound indexes...");

// Unique index on guest_id
db.guest_profiles.createIndex({ "guest_id": 1 }, { unique: true, name: "idx_unique_guest_id" });

// Unique index on email address
db.guest_profiles.createIndex({ "email": 1 }, { unique: true, name: "idx_unique_email" });

// Multikey index for querying bookings by hotel
db.guest_profiles.createIndex({ "bookings.hotel_name": 1 }, { name: "idx_bookings_hotel_name" });

// Index for top spenders / loyalty queries
db.guest_profiles.createIndex({ "stats.total_spent": -1 }, { name: "idx_stats_total_spent_desc" });

// Compound index for demographic / segmentation queries
db.guest_profiles.createIndex({ "nationality": 1, "loyalty_tier": 1 }, { name: "idx_nationality_loyalty_tier" });

print("Indexes successfully created:");
printjson(db.guest_profiles.getIndexes());

