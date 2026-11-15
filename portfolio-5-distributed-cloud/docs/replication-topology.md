# High Availability & Replication Topology

**Portfolio 5: Distributed and Cloud Database Exercise**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary

In mission-critical enterprise hospitality management, database unavailability leads directly to lost booking revenue, stranded guests at front desks, and severe brand damage. To eliminate single points of failure (SPOF) and provide disaster resilience across Nigeria, Savannah Crest Hotels deploys a **Multi-Region Primary-Replica Replication Topology**.

This document details the replication architecture, physical streaming versus logical replication mechanisms, synchronous versus asynchronous durability trade-offs, and automated failover orchestration.

---

## 2. Multi-Region Replication Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SAVANNAH CREST REPLICATION TOPOLOGY                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [ REGION 1: LAGOS (Primary Commercial Hub) ]                               │
│  MainOne Datacenter (Tier III)                                              │
│                                                                             │
│     ┌────────────────────────┐      Synchronous WAL      ┌────────────────┐ │
│     │   Primary Master (RW)  │ ═════════════════════════►│ Local Standby  │ │
│     │   PostgreSQL 16 Node 1 │       (RTT < 1.0 ms)      │ Node 2 (Sync)  │ │
│     └───────────┬────────────┘      Zero Data Loss       └────────────────┘ │
│                 │                   (RPO = 0)                               │
│                 │                                                           │
│                 │ Asynchronous Streaming Replication                        │
│                 │ WAN Fibre Connection (RTT ≈ 18-25 ms)                     │
│                 ▼                                                           │
│                                                                             │
│  [ REGION 2: ABUJA (Federal Capital / DR Site) ]                            │
│  Galaxy Backbone Cloud Datacenter                                           │
│                                                                             │
│     ┌────────────────────────┐                           ┌────────────────┐ │
│     │   Disaster Recovery    │      Local WAL Stream     │ Read-Replica   │ │
│     │   Standby Node 3 (Async│ ─────────────────────────►│ Node 4 (BI &   │ │
│     └────────────────────────┘                           │ Reporting)     │ │
│                                                          └────────────────┘ │
│                                                                             │
│  [ TIE-BREAKER CONSENSUS QUORUM ]                                           │
│  AWS Cape Town (af-south-1) Witness / Raft Node                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Physical Streaming vs. Logical Replication

PostgreSQL supports two distinct replication paradigms. Savannah Crest Hotels utilizes both for complementary operational objectives:

| Dimension | Physical Streaming Replication | Logical Replication (`pgoutput`) |
| :--- | :--- | :--- |
| **Replication Level** | Byte-for-byte physical block changes streamed via Write-Ahead Log (WAL) records | Logical decoding of WAL into row-level DML events (`INSERT`, `UPDATE`, `DELETE`) |
| **Catalog & Schema** | Standby is an exact physical bitwise clone; schema changes replicate automatically | Flexible; allows replicating specific tables, subsets of columns, or transformations |
| **Target Database Version** | Must run identical major version and CPU architecture (PG 16 on x86_64) | Supports cross-version replication (e.g. PG 15 to PG 16) and heterogeneous targets |
| **Read/Write Capability** | Standby is strictly Read-Only (`Hot Standby`) | Subscriber database can accept independent local writes on non-replicated tables |
| **Use in Savannah Crest** | **High Availability & Disaster Recovery:** Sync and async standbys for automated failover | **Change Data Capture (CDC):** Streaming committed reservations to MongoDB `guest_profiles` |

---

## 4. Synchronous vs. Asynchronous Replication Analysis

The choice of replication mode directly balances **Durability (Recovery Point Objective - RPO)** against **Transaction Commit Latency**:

$$t_{\text{commit}} = t_{\text{local\_WAL}} + 2 \times \text{RTT}_{\text{network}} + t_{\text{standby\_flush}}$$

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   DURABILITY VS. LATENCY TRADE-OFF                          │
├─────────────────────┬───────────────────┬───────────────────┬───────────────┤
│ Mode                │ RPO (Data Loss)   │ RTO (Downtime)    │ Commit Impact │
├─────────────────────┼───────────────────┼───────────────────┼───────────────┤
│ Synchronous         │ 0 (Guaranteed     │ < 30 seconds      │ + 1.2 ms      │
│ (Lagos Node 1 -> 2) │ zero data loss)   │ (Local failover)  │ (Negligible)  │
├─────────────────────┼───────────────────┼───────────────────┼───────────────┤
│ Asynchronous        │ ~ 10-50 ms of WAL │ < 2 minutes       │ + 0.0 ms      │
│ (Lagos -> Abuja)    │ (Bounded delta)   │ (Cross-region DR) │ (Zero penalty)│
└─────────────────────┴───────────────────┴───────────────────┴───────────────┘
```

### 4.1 The Savannah Crest Two-Tier Strategy:
1. **Lagos Local Zone (Synchronous `remote_apply`):**
   - Node 1 (Primary) and Node 2 (Synchronous Standby) reside in the same metropolitan datacenter connected by redundant dark fibre ($\text{RTT} < 1\text{ ms}$).
   - `synchronous_commit = remote_apply`: A transaction is not acknowledged to the client until the WAL record has been flushed and applied to memory on Node 2.
   - **Result:** $\text{RPO} = 0$. If Node 1 experiences physical motherboard failure, Node 2 promotes immediately with zero committed transaction loss.
2. **Abuja Disaster Recovery Zone (Asynchronous):**
   - Node 3 in Abuja receives WAL stream asynchronously over the inter-city WAN ($\text{RTT} \approx 22\text{ ms}$).
   - Synchronous replication across $750\text{ km}$ would penalize every front-desk transaction by over $45\text{ ms}$. Asynchronous replication shields active booking throughput while maintaining a near-real-time disaster recovery mirror.

---

## 5. Automated Failover & Split-Brain Prevention

When the primary node becomes unresponsive, an automated failover system must promote a standby. However, improper failover can trigger a catastrophic **Split-Brain anomaly** where two nodes believe they are the authoritative primary, accepting conflicting writes.

### 5.1 Patroni & Raft Consensus Architecture
Savannah Crest Hotels deploys **Patroni** integrated with a distributed consensus store (etcd or Consul) implementing the Raft consensus algorithm:
1. **Health Checking:** Patroni daemons ping the primary node every 2 seconds.
2. **Leader Lease:** The primary holds a renewable leader lease in etcd (`ttl = 10s`).
3. **Consensus Promotion:**
   - If Node 1 crashes or becomes isolated, its lease expires.
   - Nodes 2, 3, and the AWS Cape Town witness participate in a Raft election.
   - A standby is eligible for promotion **only if it holds the most advanced WAL Log Sequence Number (LSN)**:
     $$\text{LSN}_{\text{standby}} \ge \text{LSN}_{\text{cluster\_majority}}$$
   - Node 2 is elected as new primary within 12 seconds ($\text{RTO} < 15\text{s}$).
4. **Fencing (STONITH):** When Node 1 recovers, Patroni forces it to re-initialize as a standby via `pg_rewind`, rewinding any un-replicated local WAL blocks and synchronizing with the new primary.

---

## 6. Read Scaling & "Read-Your-Own-Writes" Consistency

To prevent heavy reporting workloads (e.g., daily occupancy audits, financial reconciliation) from saturating the primary transaction engine, all read-only traffic is diverted to **Read Replicas** (Node 4 in Abuja).

### Handling Replication Lag & Causal Consistency:
Because replication to read replicas is asynchronous, replicas may lag behind the primary by 5 to 50 milliseconds:
- **The Problem:** A guest confirms a room booking on the website, is redirected to the confirmation screen, but the read replica has not yet received the new row, displaying an alarming `"Booking Not Found"` error.
- **The Mitigation (Session Sticky Routing / Causal Consistency):**
  - Upon writing a reservation, the API gateway records the committed transaction's WAL LSN into the guest's session token (`session.min_lsn = 0/1A45B20`).
  - Subsequent read requests check `pg_last_wal_replay_lsn()` on the replica.
  - If the replica's LSN is behind `session.min_lsn`, the request is either routed back to the primary or delayed by a few milliseconds until the replica catches up, guaranteeing **Read-Your-Own-Writes consistency**.

