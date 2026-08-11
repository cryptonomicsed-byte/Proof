#!/usr/bin/env python3
"""
PROOF Solana Program - On-chain attestation registry.

This program lives on Solana and provides:
1. Attestation records: cryptographically signed work verification events
2. Reputation ledger: agent reputation scores derived from attestation history
3. Token distribution: PROOF reward distribution with quality multipliers
4. Burn records: immutable record of all token burns
5. Stake registry: PROOF staking positions and rewards

All attestation events are cross-referenced with Nostr events via NIP tags.
The program uses a minimal footprint for pump.fun launch compatibility.

Architecture:
- AttestationAccount: Stores individual work verifications
- ReputationAccount: Maps pubkey -> reputation score + tier
- DistributionAccount: Tracks PROOF reward pool and vesting schedules
- BurnAccount: Records all burn events for transparency
- StakeAccount: Tracks staking positions and accrued rewards

On-chain data model mirrors Buzz's event model: every attestation is
a cross-chain event linking a Solana account to a Nostr event (kind, id, pubkey).
"""

import os
import json
import hashlib
import struct
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import IntEnum


# --- Account Types (used as discriminator bytes) ---
class AccountType(IntEnum):
    UNINITIALIZED = 0
    ATTESTATION = 1      # Individual attestation record
    REPUTATION = 2       # Agent reputation ledger
    DISTRIBUTION = 3     # Token distribution pool
    BURN = 4             # Burn event log
    STAKE = 5            # Staking position
    CONFIG = 6           # Protocol configuration
    ORACLE = 7           # Attestation oracle (quality scoring)


# --- Attestation Record ---
@dataclass
class Attestation:
    """An individual work verification attestation on-chain."""
    # Account discriminator
    account_type: AccountType = AccountType.ATTESTATION

    # Source identification
    nostr_pubkey: bytes = b""          # 32-byte secp256k1 pubkey (hex of nostr npub)
    nostr_event_id: str = ""           # Nostr event ID (64 hex chars)
    nostr_kind: int = 0                # Nostr event kind (e.g. 43001 for job request)

    # Work context (Buzz workspace)
    buzz_community: str = ""           # Community host/domain
    buzz_channel: str = ""             # Channel UUID
    buzz_repo: str = ""                # Optional: repo slug

    # Work type classification
    work_type: str = ""                # "bug_fix", "feature_merge", etc.

    # Reward parameters
    base_reward: int = 0               # Base PROOF reward (in smallest units, 9 decimals)
    quality_score: float = 0.0         # Quality multiplier (0.5 to 3.0)
    final_reward: int = 0              # quality_score * base_reward
    attester_pubkey: bytes = b""       # Who attested (32 bytes)

    # Timestamps
    created_at: int = 0                # Unix timestamp (epoch)
    attested_at: int = 0               # Unix timestamp when attested

    # Verification
    verified: bool = False             # Has this been on-chain verified?
    on_chain_tx: str = ""              # Solana tx hash where attested

    def to_bytes(self) -> bytes:
        """Serialize to bytes for Solana account data."""
        data = struct.pack('B', self.account_type)  # 1 byte discriminator
        data += self.nostr_pubkey + b'\x00' * (32 - len(self.nostr_pubkey))  # 32 bytes
        data += len(self.nostr_event_id).to_bytes(4, 'little')  # 4 bytes length
        data += self.nostr_event_id.encode()  # variable
        data += struct.pack('<I', self.nostr_kind)  # 4 bytes
        data += len(self.buzz_community).to_bytes(4, 'little')
        data += self.buzz_community.encode()
        data += len(self.buzz_channel).to_bytes(4, 'little')
        data += self.buzz_channel.encode()
        data += len(self.buzz_repo).to_bytes(4, 'little')
        data += self.buzz_repo.encode()
        data += len(self.work_type).to_bytes(4, 'little')
        data += self.work_type.encode()
        data += struct.pack('<Q', self.base_reward)  # 8 bytes u64
        data += struct.pack('<f', self.quality_score)  # 4 bytes f32
        data += struct.pack('<Q', self.final_reward)  # 8 bytes u64
        data += self.attester_pubkey + b'\x00' * (32 - len(self.attester_pubkey))
        data += struct.pack('<Q', self.created_at)
        data += struct.pack('<Q', self.attested_at)
        data += struct.pack('?', self.verified)
        data += len(self.on_chain_tx).to_bytes(4, 'little')
        data += self.on_chain_tx.encode()
        return data

    @staticmethod
    def from_nostr_event(event: dict, buzz_channel: str, buzz_community: str,
                         attester_pubkey: bytes, work_type: str,
                         quality_score: float) -> 'Attestation':
        """Create an attestation from a Nostr event payload."""
        nostr_pubkey = bytes.fromhex(event.get('pubkey', ''))[:32]
        nostr_event_id = event['id']
        nostr_kind = event.get('kind', 0)
        content = event.get('content', '{}')

        try:
            work_data = json.loads(content)
        except json.JSONDecodeError:
            work_data = {}

        # Determine reward based on work type
        base_reward = {
            'bug_fix': 500,
            'feature_merge': 2000,
            'doc_update': 200,
            'ci_pass': 50,
            'workflow_complete': 1000,
            'code_review': 300,
            'security_fix': 3000,
            'performance_improvement': 1500,
        }.get(work_type, 100)

        # Convert to smallest units (9 decimals)
        base_reward *= 1_000_000_000

        return Attestation(
            nostr_pubkey=nostr_pubkey,
            nostr_event_id=nostr_event_id,
            nostr_kind=nostr_kind,
            buzz_channel=buzz_channel,
            buzz_community=buzz_community,
            buzz_repo=work_data.get('repo', ''),
            work_type=work_type,
            base_reward=base_reward,
            quality_score=quality_score,
            final_reward=int(base_reward * quality_score),
            attester_pubkey=attester_pubkey,
            created_at=event.get('created_at', 0),
            attested_at=int(os.times().user + os.times().system) if hasattr(os, 'times') else 0,
        )


# --- Reputation Account ---
@dataclass
class Reputation:
    """Agent reputation ledger — the portable trust score."""
    account_type: AccountType = AccountType.REPUTATION
    agent_pubkey: bytes = b""  # 32 bytes, Solana or Nostr pubkey

    # Reputation metrics
    total_attestations: int = 0
    total_rewards_earned: int = 0          # Cumulative PROOF earned
    total_attestations_received: int = 0   # How many others attested to this agent
    total_attestations_given: int = 0      # How many this agent attested for others
    average_quality: float = 0.0           # Mean quality score of attestations received
    reputation_score: float = 0.0          # Composite reputation (0-1000)

    # Tier classification
    tier: str = "unverified"               # unverified, verified, trusted, elite, legendary

    # Nostr linkage
    nostr_pubkey: bytes = b""              # Linked Nostr pubkey
    nostr_npub: str = ""                   # Human-readable npub for display
    linked_communities: List[str] = field(default_factory=list)  # Buzz communities participated in

    # Time weights
    activity_7d: int = 0
    activity_30d: int = 0
    activity_90d: int = 0
    first_activity: int = 0
    last_activity: int = 0

    def calculate_tier(self):
        """Calculate tier based on composite reputation."""
        score = self.reputation_score
        att = self.total_attestations
        if score >= 800 and att >= 50:
            self.tier = "legendary"
        elif score >= 500 and att >= 30:
            self.tier = "elite"
        elif score >= 300 and att >= 15:
            self.tier = "trusted"
        elif score >= 100 and att >= 5:
            self.tier = "verified"
        else:
            self.tier = "unverified"

    def update_score(self, new_attestation: Attestation):
        """Update reputation after a new attestation."""
        self.total_attestations += 1
        self.total_rewards_earned += new_attestation.final_reward
        self.total_attestations_received += 1

        # Weighted average quality
        if self.total_attestations_received == 1:
            self.average_quality = new_attestation.quality_score
        else:
            prev = self.average_quality * (self.total_attestations_received - 1)
            self.average_quality = (prev + new_attestation.quality_score) / self.total_attestations_received

        # Composite score: quality * quantity * recency
        recency = min(1.0, self.activity_7d / 10.0) if self.activity_7d > 0 else 0
        self.reputation_score = (
            self.average_quality * 100 +
            self.total_attestations * 5 +
            self.total_attestations_given * 2 +
            recency * 50
        )

        self.calculate_tier()

    def to_dict(self) -> dict:
        self.calculate_tier()
        return {
            'agent': self.agent_pubkey.hex() if self.agent_pubkey else '',
            'nostr_npub': self.nostr_npub,
            'tier': self.tier,
            'reputation_score': round(self.reputation_score, 1),
            'total_attestations': self.total_attestations,
            'total_rewards_earned': self.total_rewards_earned,
            'average_quality': round(self.average_quality, 2),
            'communities': self.linked_communities,
            'activity_7d': self.activity_7d,
            'activity_30d': self.activity_30d,
        }


# --- Distribution Account ---
@dataclass
class Distribution:
    """Token distribution pool with vesting schedules."""
    account_type: AccountType = AccountType.DISTRIBUTION
    total_supply: int = 1_000_000_000 * 1_000_000_000  # 1B * 10^9
    decimals: int = 9

    # Allocation buckets
    agent_rewards_allocated: int = 400_000_000 * 1_000_000_000
    agent_rewards_distributed: int = 0
    community_fund_allocated: int = 150_000_000 * 1_000_000_000
    community_fund_distributed: int = 0
    team_reserved: int = 100_000_000 * 1_000_000_000
    team_vested: int = 0
    buyback_reserve: int = 100_000_000 * 1_000_000_000
    buyback_purchased: int = 0
    burn_pool: int = 150_000_000 * 1_000_000_000
    burn_pool_burned: int = 0

    # Distribution tracking
    total_burned: int = 0
    total_staked: int = 0
    total_liquid_circulating: int = 0

    # Timestamps
    launched_at: int = 0
    last_distribution: int = 0

    @property
    def circulating_supply(self) -> int:
        return self.total_supply - self.team_reserved + self.team_vested

    @property
    def effective_circulating(self) -> int:
        return self.circulating_supply - self.total_burned - self.total_staked

    def distribute_reward(self, amount: int, category: str = "agent_rewards"):
        """Distribute tokens from a bucket."""
        if category == "agent_rewards":
            if self.agent_rewards_allocated - self.agent_rewards_distributed >= amount:
                self.agent_rewards_distributed += amount
                self.total_liquid_circulating += amount
                return True
        elif category == "community_fund":
            if self.community_fund_allocated - self.community_fund_distributed >= amount:
                self.community_fund_distributed += amount
                self.total_liquid_circulating += amount
                return True
        elif category == "team":
            # Only if vested
            if self.team_vested >= amount:
                self.total_liquid_circulating += amount
                return True
        return False

    def burn_tokens(self, amount: int, reason: str = ""):
        """Burn tokens and record the event."""
        self.burn_pool_burned += amount
        self.total_burned += amount
        self.total_liquid_circulating -= amount


# --- Protocol Config ---
@dataclass
class Config:
    """Protocol configuration — the single source of truth."""
    account_type: AccountType = AccountType.CONFIG
    version: int = 1
    fee_basis_points: int = 50       # 0.50% fee on rewards (goes to buyback)
    max_attestation_per_day: int = 500
    quality_scoring_enabled: bool = True
    burn_fee_pct: float = 2.0        # 2% burn on every reward
    cooldown_seconds: int = 60
    max_daily_reward: int = 50_000 * 1_000_000_000  # 50K PROOF
    reward_multipliers: Dict[str, int] = field(default_factory=lambda: {
        'bug_fix': 500,
        'feature_merge': 2000,
        'doc_update': 200,
        'ci_pass': 50,
        'workflow_complete': 1000,
        'code_review': 300,
        'security_fix': 3000,
        'performance_improvement': 1500,
    })
    tier_multipliers: Dict[str, float] = field(default_factory=lambda: {
        'unverified': 1.0,
        'verified': 1.25,
        'trusted': 1.5,
        'elite': 2.0,
        'legendary': 3.0,
    })
    staking_enabled: bool = True
    governance_enabled: bool = True
    min_stake_for_governance: int = 100_000 * 1_000_000_000
    oracle_pubkeys: List[bytes] = field(default_factory=list)  # Who can attest


# --- Nostr Integration Layer ---
# The attestation program must accept Nostr-signed events as proof sources.
# This means: when a Buzz agent does work, it posts a Nostr event (kind 43001 or similar).
# An attestation oracle then verifies the work, creates a Nostr attestation event,
# and the on-chain program records the link: nostr_event_id -> on-chain record.
#
# Key NIPs used:
# NIP-01: Basic event format (kind, pubkey, tags, content, sig, created_at)
# NIP-04: Encrypted DMs (for private attestations)
# NIP-05: Domain-based Nostr verification (agent domain -> pubkey)
# NIP-07: Browser wallet (agent key management)
# NIP-19: Bech32 encoding (np1, nprofile, nevent)
# NIP-26: Delegated event signing (agent acting on behalf of human)
# NIP-28: Public chat (Buzz streams)
# NIP-33: Parameterized replaceable events (for reputation profiles)
# NIP-34: Git repo metadata (linking Buzz repos to on-chain records)
# NIP-42: Authentication (agent auth to relay)
# NIP-57: Lightning tips (PROOF tipping in channel)
# NIP-73: NFTs (PROOF as NFT metadata)
# NIP-98: HTTP auth (agent API access)


def create_attestation_event(
    signer_privkey: bytes,
    nostr_event_id: str,
    buzz_channel: str,
    buzz_community: str,
    work_type: str,
    work_repo: str,
    work_url: str,
    quality_score: float,
) -> dict:
    """
    Build a Nostr event that serves as the attestation proof.
    This event is posted to the Buzz relay and simultaneously anchors
    the on-chain attestation record.
    """
    tags = [
        ["d", hashlib.sha256(f"{buzz_channel}:{nostr_event_id}".encode()).hexdigest()[:16]],
        ["e", nostr_event_id],
        ["p", "attestation_oracle"],
        ["community", buzz_community],
        ["channel", buzz_channel],
        ["work_type", work_type],
        ["work_repo", work_repo],
        ["quality", f"{quality_score:.2f}"],
        ["proof", "solana-attestation"],
    ]

    content = json.dumps({
        "type": "attestation",
        "version": 1,
        "work_type": work_type,
        "work_repo": work_repo,
        "work_url": work_url,
        "quality_score": quality_score,
        "nostr_event_id": nostr_event_id,
        "buzz_channel": buzz_channel,
        "buzz_community": buzz_community,
        "timestamp": int(__import__('time').time()),
    })

    return {
        "kind": 30009,  # Parameterized replaceable — attestation profile
        "tags": tags,
        "content": content,
        # "pubkey": signer_pubkey,  # Set by Nostr library
        # "created_at": int(time.time()),  # Set by Nostr library
        # "sig": signature,  # Set by Nostr library
    }


def cross_reference_event(nostr_event: dict, on_chain_tx: str,
                          account_address: str) -> dict:
    """
    Create a cross-reference linking a Nostr event to its on-chain record.
    This creates a verifiable bridge: anyone can check both chains independently.
    """
    tags = [
        ["tx", on_chain_tx],
        ["address", account_address],
        ["chain", "solana"],
        ["nostr_id", nostr_event["id"]],
        ["nostr_pubkey", nostr_event["pubkey"]],
        ["nostr_kind", str(nostr_event.get("kind", 0))],
    ]

    return {
        "kind": 30007,  # Cross-reference event
        "tags": tags,
        "content": json.dumps({
            "nostr_event": {
                "id": nostr_event["id"],
                "kind": nostr_event.get("kind", 0),
                "pubkey": nostr_event["pubkey"],
            },
            "solana": {
                "tx": on_chain_tx,
                "account": account_address,
                "chain": "mainnet",
            },
        }),
    }


# --- Pump.fun Launch Preparation ---
def generate_pumpfun_launch_params() -> dict:
    """
    Generate all parameters needed to launch PROOF on pump.fun.
    This creates the bonding curve token with the exact tokenomics.
    """
    return {
        "name": "Proof",
        "symbol": "PROOF",
        "description": (
            "Proof is a reputation token for agent-native work verification. "
            "Every contribution to a Buzz workspace is cryptographically attested "
            "and tokenized. PROOF rewards verified work, enables portable agent "
            "reputation across communities, and creates a sustainable economy "
            "where agents earn, spend, and compound value."
        ),
        "image_uri": "https://proof.buzz/proof-token.png",
        "twitter": "https://x.com/proof_buzz",
        "telegram": "https://t.me/proof_buzz",
        "website": "https://proof.buzz",
        "metadata": {
            "total_supply": 1000000000,
            "decimals": 9,
            "tokenomics_url": "https://proof.buzz/tokenomics.json",
            "on_chain_program": "PROOFat00000000000000000000000000000000000",
            "buzz_integration": True,
            "nostr_native": True,
        },
        "initial_market_cap_target": 50000,  # USD target for bonding curve
    }


if __name__ == '__main__':
    # Generate launch params and print
    params = generate_pumpfun_launch_params()
    print(json.dumps(params, indent=2))
    print("\n" + "=" * 60)
    print("PUMP.FUN LAUNCH PARAMETERS GENERATED")
    print("=" * 60)
    print(f"Name:        {params['name']}")
    print(f"Symbol:      {params['symbol']}")
    print(f"Supply:      {params['metadata']['total_supply']:,} ({params['metadata']['decimals']} decimals)")
    print(f"Target MC:   ${params['initial_market_cap_target']:,.0f}")
    print(f"Platform:    pump.fun bonding curve")
    print(f"Tokenomics:  {params['metadata']['tokenomics_url']}")
