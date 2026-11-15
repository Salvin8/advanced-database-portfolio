# CAP & PACELC Theorem Analysis for Distributed Hospitality Systems

**Portfolio 5: Distributed and Cloud Database Exercise**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary

As Savannah Crest Hotels scales across six Nigerian metropolitan centres (Abuja, Lagos, Port Harcourt, Kano, Enugu, and Ibadan), operating across wide-area networks (WANs) exposes the database tier to network latency spikes, packet loss, and inter-city fibre cuts. 

In a distributed environment, the **CAP Theorem** (Brewer, 2000) and its extension, the **PACELC Theorem** (Abadi, 2012), dictate the fundamental trade-offs between consistency, availability, and latency. Rather than applying a single uniform policy across all business functions, Savannah Crest Hotels deploys a **hybrid, workload-segmented consistency model**:
- **Room Booking & Financial Settlement:** Prioritises **Consistency (CP / PC/EC)** to mathematically guarantee zero double bookings and zero financial drift.
- **Guest Reviews, Feedback, & Hotel Catalog Browsing:** Prioritises **Availability & Low Latency (AP / PA/EL)** to maintain fluid mobile customer experiences even during regional network partitions.

---

## 2. Theoretical Framework

### 2.1 The CAP Theorem
The CAP Theorem asserts that in any asynchronous network subject to partitions ($P$):
- **Consistency ($C$):** Every read receives the most recent write or an error.
- **Availability ($A$):** Every non-failing node returns a non-error response for every request (without guaranteeing it is the most recent write).
- **Partition Tolerance ($P$):** The system continues to operate despite an arbitrary number of messages being dropped or delayed by the network between nodes.

Because physical networks inevitably experience partitions ($P$ is non-negotiable in distributed real-world infrastructure), a system must trade off between $C$ and $A$ during a network partition:

$$\text{CAP Theorem:} \quad P \implies (C \oplus A)$$

```
                                [ PARTITION TOLERANCE (P) ]
                                      ▲             ▲
                                     /               \
                                    /                 \
                                   /                   \
                                  /  Savannah Crest     \
                                 /   Partition Boundary  \
                                /                         \
                               ▼                           ▼
[ CONSISTENCY (CP) ] ◄────────────────────────────────────────► [ AVAILABILITY (AP) ]
• Core Reservation Engine                                      • Guest Reviews & Ratings
• Financial Ledger & Invoicing                                 • Public Hotel Catalog & Amenities
• Room Double-Booking Exclusion                                • Marketing Promotional Campaigns
• Rejects writes if majority quorum lost                       • Accepts local writes; syncs later
```

### 2.2 The PACELC Theorem
The PACELC Theorem formalises system behavior both under failure and under steady-state operations:

$$\text{If } \mathbf{P} \text{ (Partition)}, \text{ choose between } \mathbf{A} \text{ and } \mathbf{C}; \quad \mathbf{E} \text{ (Else)}, \text{ choose between } \mathbf{L} \text{ (Latency) and } \mathbf{C} \text{ (Consistency)}.$$

| System Capability | PACELC Classification | Normal Operation (Else) | During Network Partition |
| :--- | :---: | :--- | :--- |
| **Room Inventory Allocation** | **PC / EC** | Synchronous WAL replication; verifies strict serializability before acknowledging commit. | Refuses bookings if the regional node cannot reach the primary cluster quorum; prevents double-booking. |
| **Payment Ledger Processing** | **PC / EC** | Two-phase commit or synchronous ledger write; zero tolerance for financial discrepancies. | Blocks transaction processing until authoritative settlement connection is re-established. |
| **Room Availability Search** | **PA / EL** | Serves reads from local Redis/read-replicas with sub-millisecond latency. | Continues serving cached room availability; marks results as "tentative" until checkout. |
| **Guest Reviews & Feedback** | **PA / EL** | Writes commit to local MongoDB replica without blocking on cross-region synchronization. | Buffers submitted reviews locally; merges via CRDT or timestamp ordering when WAN restores. |

---

## 3. Real-World Failure Scenario: Lagos–Abuja Fibre Severance

To contextualise these theoretical concepts, consider a concrete failure scenario across the Savannah Crest Hotels infrastructure:

```
┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│     REGION 1: LAGOS CLUSTER     │               │     REGION 2: ABUJA CLUSTER     │
│  • Primary Database Node        │   WAN Cut     │  • Read-Replica / Regional App  │
│  • 3 Properties (VI, Bodija, PH)│  ─────────X─  │  • 3 Properties (Abuja, Kano,   │
│  • High-frequency booking API   │   Fibre Cut   │    Enugu)                       │
└────────────────┬────────────────┘               └────────────────┬────────────────┘
                 │                                                 │
                 ▼                                                 ▼
        [ Quorum Maintained ]                             [ Quorum Lost (Minority) ]
        • Lagos, Ibadan, PH remain                         • Abuja regional app isolated
          fully operational (CP)                             from master database
        • Writes accepted for local                        • Room reservations REJECTED
          properties                                       • Catalog browsing ALLOWED
```

### Operational Impact & System Behavior:
1. **At Time $T_0$:** A terrestrial fibre severance occurs along the Lagos-Ibadan-Abuja corridor, severing WAN communication between the primary database cluster in Lagos and the northern regional nodes in Abuja and Kano.
2. **Behavior on Core Reservation Engine (CP):**
   - The Abuja regional booking service attempts to confirm a booking for a Presidential Suite at Savannah Crest Abuja.
   - The regional service cannot contact the primary cluster in Lagos to acquire row-level locks and evaluate GiST interval exclusion constraints.
   - Under CP semantics, the transaction is **aborted with an explicit error**: `"Service Temporarily Unavailable: Unable to guarantee reservation uniqueness across network partition."`
   - **Business Justification:** A rejected reservation can be recovered via a follow-up customer service call; a double-booked Presidential Suite during the December festive peak costs millions of Naira in compensation, reputational damage, and VIP guest churn.
3. **Behavior on Guest Catalog & Information Services (AP):**
   - Guests using the mobile application in Abuja to browse restaurant menus, room photographs, and amenities experience **zero downtime**.
   - Redis read caches in Abuja continue serving local data with $\approx 1.5\text{ ms}$ latency, fulfilling the Availability guarantee.

---

## 4. Trade-Off Evaluation Matrix

| Architectural Choice | Advantages | Disadvantages & Risks | Applied Domain in Savannah Crest |
| :--- | :--- | :--- | :--- |
| **Strict CP (Consistent / Partition-Tolerant)** | Mathematically prevents double bookings, duplicate charges, and inventory ghost writes. | Reduces availability during WAN failures; regional front desks cannot confirm reservations offline. | Central Booking Engine, Payment Gateway, Room Inventory allocations. |
| **Strict AP (Available / Partition-Tolerant)** | 100% uptime for end-user reads and writes; resilient against domestic ISP instability. | Requires complex conflict-resolution algorithms (CRDTs, Last-Write-Wins); risk of business anomalies. | Guest reviews, room amenity updates, mobile app notification logs. |
| **Tunable Consistency (e.g. MongoDB `w: majority`, `readConcern: "majority"`)** | Allows fine-grained balance between write latency and replication durability per query. | Misconfiguration by developers can silently degrade consistency or introduce dirty reads. | Guest 360 dossiers, loyalty tier metrics calculation, customer CRM profiling. |

---

## 5. Architectural Recommendations for Savannah Crest Hotels

1. **Deploy Split-Brain Protected Quorum Clustering:** Use Raft-based consensus (Patroni for PostgreSQL, MongoDB Replica Sets) with a minimum of 3 voting nodes (e.g., 2 in Lagos, 1 in Abuja, with a lightweight tie-breaker witness node in AWS Cape Town / af-south-1).
2. **Asynchronous Read Offloading:** Route all read-only analytics, revenue management reporting, and guest history searches to local read-replicas (`read-only`), preserving primary node capacity strictly for CP reservation transactions.
3. **Circuit Breakers on Cross-Region Calls:** Implement application-level circuit breakers (e.g., using Python `tenacity` or `pybreaker`) with maximum 2-second timeouts to rapidly degrade gracefully during WAN disruptions rather than exhausting client connection pools.

