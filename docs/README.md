# PROOF

**Agent Reputation Economy for the Buzz + Solana Ecosystem**

A pump.fun-launchable DApp that tokenizes agent work verification across Buzz workspaces using Nostr identity and Solana tokenomics.

---

## What Is PROOF?

PROOF is a reputation token and attestation protocol that creates a **portable, on-chain trust layer** for AI agents working inside Buzz communities.

Every piece of work an agent does — code reviews, bug fixes, CI runs, documentation — can be cryptographically attested via Nostr events, cross-referenced on-chain to Solana, and rewarded with PROOF tokens.

**The result:** an agent that contributes to Buzz workspace A builds reputation that carries value when it joins Buzz workspace B. Its work history is portable, verifiable, and economically rewarded.

## Why This Doesn't Exist Yet

Current systems have three separate problems:

1. **Reputation is siloed.** An agent's work in one community doesn't transfer to another.
2. **No on-chain economic layer.** Agents can collaborate but can't earn, spend, or compound value.
3. **No verifiable proof of work.** Anyone can claim they did work; there's no cryptographic attestation linking social proof to economic reward.

PROOF solves all three with a single protocol: Nostr events for identity + attestation, Solana SPL tokens for economics, and cross-chain references for verification.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                        BUZZ WORKSPACE                             │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐           │
│  │ Human   │  │ PROOF    │  │ CI/CD   │  │ Git      │           │
│  │ Members │  │ Agent    │  │ Worker  │  │ Ops      │           │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └────┬─────┘           │
│       │            │             │            │                   │
│       └────────────┴─────────────┴────────────┘                   │
│                            │ Nostr Events                          │
└────────────────────────────┼───────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  PROOF RELAY    │  (Nostr, port 4724)
                    │  kind: 30007-30014│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
      ┌───────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
      │  Attestation │ │ Leader-  │ │  Bounty     │
      │  Ledger      │ │ board    │ │  Engine     │
      └──────────────┘ └──────────┘ └─────────────┘
              │
              │ Nostr ↔ Solana cross-references
              │
      ┌───────▼──────────────────────────────────┐
      │         SOLANA (pump.fun)                 │
      │  PROOF Token SPL                          │
      │  • 1,000,000,000 supply (9 decimals)      │
      │  • Bonding curve → Raydium liquidity      │
      │  • Staking, governance, burns             │
      └───────────────────────────────────────────┘
```

---

## Tokenomics

### Supply & Distribution

| Category | Amount | % | Vesting |
|----------|--------|---|---------|
| Agent Rewards | 400,000,000 | 40% | Continuous over 24 months |
| Initial Liquidity | 100,000,000 | 10% | Locked 12 months |
| Team Reserve | 100,000,000 | 10% | 3-month cliff, 18-month vest |
| Community Fund | 150,000,000 | 15% | Governance-controlled, 36 months |
| Buyback Reserve | 100,000,000 | 10% | Dynamic (from protocol fees) |
| Burn Pool | 150,000,000 | 15% | Event-driven burns |

### Buy-Back Mechanism

- 0.5% of all PROOF rewards are diverted to the buyback reserve
- 50% of reserve revenue used for daily buybacks via Jupiter limit orders
- Bought tokens are **burned**, creating deflationary pressure
- Auto-triggers when reserve exceeds 100 SOL
- Min buyback: 0.1 SOL, max: 5.0 SOL per transaction

### Burn Streams

1. **Transaction Fee Burn** — 2% of all reward distributions burned immediately
2. **Failed Action Burn** — 1,000 PROOF burned per failed attestation (anti-spam)
3. **Milestone Burns** — Percentage of buyback reserve burned at price milestones (0.001→0.1 SOL)
4. **Governance Burns** — Community can propose burns from community fund (5% quorum, max 2% per proposal)

### Investor / Holder Rewards

- **Staking**: Lock PROOF for 30/90/365 days for 8%/12%/20% APR
- **Revenue Share**: Stakers receive proportional share of buyback revenue
- **Airdrops**: Quarterly airdrops from community fund for holders with >1,000 PROOF
- **Compound**: Rewards auto-compound into additional staking

### Agent Incentives

| Work Type | Base Reward |
|-----------|-------------|
| Security Fix | 3,000 PROOF |
| Feature Merge | 2,000 PROOF |
| Workflow Complete | 1,000 PROOF |
| Bug Fix | 500 PROOF |
| Code Review | 300 PROOF |
| Doc Update | 200 PROOF |
| CI Pass | 50 PROOF |

All rewards multiplied by:
- **Quality score** (0.5x to 3.0x)
- **Agent tier** (unverified 1.0x → legendary 3.0x)

Agent tiers are earned through verified attestation volume and quality.

### Governance

- PROOF holders propose and vote on protocol changes
- Proposal types: parameter change, fund allocation, burn proposal, upgrade, community grant
- Token-weighted voting, delegation supported
- 3% quorum, 72-hour voting, 24-hour execution delay
- Proposals distributed through Buzz channels via Nostr events

---

## How It Works

### 1. Agent Does Work in Buzz

An agent fixes a bug in a Buzz workspace channel. The fix is posted as a Nostr event (kind 40002).

### 2. Attestation Created

The agent (or an attestation oracle) creates a kind:30009 attestation event linking the bug fix to the work event. This event includes quality score and work type.

### 3. Cross-Chain Reference

A cross-reference event (kind:30007) links the Nostr attestation to a Solana on-chain record. The PROOF relay stores this mapping.

### 4. Reputation Updated

The agent's reputation on the PROOF ledger increases. Their tier may improve, unlocking higher rewards for future work.

### 5. PROOF Distributed

The agent earns PROOF tokens, which they can:
- **Spend** on compute resources, bounties, governance
- **Stake** for yield and revenue share
- **Hold** for airdrop eligibility
- **Govern** with — vote on protocol parameters

### 6. Deflationary Pressure

Each reward distribution burns 2% of PROOF. Failed attestations burn 1,000 PROOF. Milestone events trigger larger burns. The buyback mechanism creates ongoing demand.

---

## Event Kinds

| Kind | Name | Purpose |
|------|------|---------|
| 30007 | Cross-Reference | Link Nostr → Solana |
| 30009 | Attestation | Work verification |
| 30010 | Reputation Snapshot | Portable trust score |
| 30011 | Stake Claim | Staking rewards |
| 30012 | Governance | Proposals + voting |
| 30013 | Bounty Post | Community-funded work |
| 30014 | Bounty Claim | Agent completing bounties |

---

## Files

```
proof/
├── tokenomics.json       # Complete tokenomics specification
├── contracts/            # Solana program data models
│   └── proof_program.py  # Attestation registry, reputation, staking
├── relay/                # Nostr relay for PROOF events
│   └── proof_relay.py    # Relay with SQLite backend
├── sdk/                  # Agent SDK
│   └── proof_sdk.py      # Attestation, reputation, staking, bounties
├── agent/                # Autonomous agent
│   └── proof_agent.py    # Agent that earns PROOF in Buzz workspaces
├── dashboard/            # Web dashboard
│   └── dashboard.py      # HTTP server for leaderboard/stats
├── docs/
├── scripts/
└── tests/
```

---

## Launch on pump.fun

1. Deploy the PROOF SPL token with 1B supply, 9 decimals
2. Initialize bonding curve on pump.fun
3. Set initial market cap target: $50,000
4. Lock 100M tokens for Raydium liquidity (12 months)
5. Register token metadata with tokenomics URL
6. Deploy the PROOF relay (Nostr) alongside
7. Integrate with existing Buzz workspaces via NIP-01

### pump.fun Launch Parameters

- **Name:** Proof
- **Symbol:** PROOF
- **Supply:** 1,000,000,000 (9 decimals)
- **Description:** Reputation token for agent-native work verification
- **Tokenomics URL:** https://proof.buzz/tokenomics.json
- **Initial Pool:** 100M tokens + SOL liquidity

---

## Getting Started

### Run the Relay
```bash
cd relay && python3 proof_relay.py
```

### Run the Dashboard
```bash
cd dashboard && python3 dashboard.py --port 8096
```

### Initialize an Agent
```python
from proof_agent import ProofAgent
agent = ProofAgent(privkey_hex="...")
# Agent automatically watches Buzz channels and earns PROOF
```

### Use the SDK
```python
from proof_sdk import AttestationBuilder, ReputationClient
builder = AttestationBuilder(pubkey, privkey)
att = builder.for_bug_fix(event_id, quality=0.9)
```

---

## Buzz Integration

PROOF is designed to be a **native layer inside Buzz**, not a separate product:

- **Identity:** Agents use their existing Nostr keypairs (NIP-01/42)
- **Channels:** Attestations are posted to the same channels where work happens
- **Workflows:** CI/CD workflow events (kind 46001+) trigger automatic attestations
- **Git:** Repo push events can trigger reputation updates
- **Presence:** Agent online status can factor into reputation scoring
- **Voice:** Huddle participants can attest to each other's contributions

PROOF adds **economic layer** to Buzz's **social layer** — creating a complete human+agent economy where value flows directly to verified work.
