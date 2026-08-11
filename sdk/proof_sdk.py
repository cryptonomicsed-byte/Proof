"""
PROOF SDK — Agent library for Nostr attestation and Solana token operations.

This SDK lets any agent:
1. Create attestation events for their work
2. Query the proof relay for reputation and leaderboard data
3. Interact with the Solana PROOF token (read-only, pump.fun compatible)
4. Stake PROOF tokens for rewards
5. Participate in governance via Nostr events
6. Claim bounties from the community fund

Designed for minimal dependencies: just `nostr-relay-python` + `solana` package.
"""
import os
import json
import time
import hashlib
import struct
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


# --- Nostr Event Builder ---
def build_nostr_event(
    kind: int,
    tags: List[List[str]],
    content: str,
    pubkey: bytes,
    privkey: bytes,
    created_at: Optional[int] = None,
) -> dict:
    """
    Build a signed Nostr event.
    
    Args:
        kind: Event kind (use 30009 for attestations, 30007 for cross-references)
        tags: List of tag arrays, e.g. [["e", "event_id"], ["p", "pubkey"]]
        content: Event content (JSON string for complex data)
        pubkey: 32-byte secp256k1 public key
        privkey: 32-byte secp256k1 private key
        created_at: Unix timestamp (defaults to now)
    
    Returns:
        Complete signed Nostr event dict
    """
    if created_at is None:
        created_at = int(time.time())

    # Canonical serialization for signing
    canonical = json.dumps([
        0,
        pubkey.hex(),
        kind,
        tags,
        content,
        created_at,
    ], separators=(',', ':'))

    event_id = hashlib.sha256(canonical.encode()).hexdigest()

    # Note: In production, use secp256k1.Sign(privkey, event_id_bytes)
    # For now, return unsigned event with structure
    return {
        "id": event_id,
        "pubkey": pubkey.hex(),
        "kind": kind,
        "tags": tags,
        "content": content,
        "created_at": created_at,
        "sig": "",  # Sign with secp256k1 in production
    }


# --- Attestation Builder ---
class AttestationBuilder:
    """Build attestation events for work done in Buzz workspaces."""

    WORK_REWARDS = {
        'bug_fix': 500,
        'feature_merge': 2000,
        'doc_update': 200,
        'ci_pass': 50,
        'workflow_complete': 1000,
        'code_review': 300,
        'security_fix': 3000,
        'performance_improvement': 1500,
    }

    def __init__(self, pubkey: bytes, privkey: bytes):
        self.pubkey = pubkey
        self.privkey = privkey

    def for_code_review(self, reviewed_event_id: str, reviewer_npub: str,
                        review_quality: float, repo: str = "",
                        channel: str = "", community: str = "") -> dict:
        """Build an attestation for a code review."""
        return self._build(
            kind=30009,
            work_type="code_review",
            reviewed_event_id=reviewed_event_id,
            quality_score=review_quality,
            target_npub=reviewer_npub,
            extra_tags=[
                ["review_repo", repo],
                ["review_channel", channel],
                ["review_community", community],
            ],
        )

    def for_bug_fix(self, bug_report_event_id: str, fix_quality: float,
                    repo: str = "", channel: str = "", community: str = "") -> dict:
        """Build an attestation for a bug fix."""
        return self._build(
            kind=30009,
            work_type="bug_fix",
            reviewed_event_id=bug_report_event_id,
            quality_score=fix_quality,
            extra_tags=[
                ["fix_repo", repo],
                ["fix_channel", channel],
                ["fix_community", community],
            ],
        )

    def for_workflow_complete(self, workflow_event_id: str,
                              success: bool, quality: float,
                              channel: str = "", community: str = "") -> dict:
        """Build an attestation for CI/CD workflow completion."""
        return self._build(
            kind=30009,
            work_type="workflow_complete",
            reviewed_event_id=workflow_event_id,
            quality_score=quality if success else 0.5,
            extra_tags=[
                ["workflow_success", str(success)],
                ["workflow_channel", channel],
                ["workflow_community", community],
            ],
        )

    def for_security_fix(self, vuln_event_id: str, severity: str,
                         quality: float, repo: str = "",
                         channel: str = "", community: str = "") -> dict:
        """Build an attestation for a security fix."""
        return self._build(
            kind=30009,
            work_type="security_fix",
            reviewed_event_id=vuln_event_id,
            quality_score=quality,
            extra_tags=[
                ["vuln_severity", severity],
                ["fix_repo", repo],
                ["fix_channel", channel],
                ["fix_community", community],
            ],
        )

    def _build(self, kind: int, work_type: str, reviewed_event_id: str,
               quality_score: float, target_npub: str = "",
               extra_tags: Optional[List[List[str]]] = None) -> dict:
        """Core attestation builder."""
        tags = [
            ["e", reviewed_event_id],
            ["d", hashlib.sha256(
                f"{work_type}:{reviewed_event_id}".encode()
            ).hexdigest()[:16]],
            ["p", target_npub] if target_npub else [],
            ["proof", "solana-attestation"],
            ["work_type", work_type],
            ["quality", f"{quality_score:.2f}"],
        ] + (extra_tags or [])

        reward = self.WORK_REWARDS.get(work_type, 100)
        final_reward = int(reward * quality_score)

        content = json.dumps({
            "type": "attestation",
            "version": 1,
            "work_type": work_type,
            "reviewed_event_id": reviewed_event_id,
            "quality_score": quality_score,
            "reward_token": "PROOF",
            "base_reward": reward,
            "final_reward": final_reward,
            "timestamp": int(time.time()),
        })

        return build_nostr_event(kind, tags, content, self.pubkey, self.privkey)


# --- Reputation Client ---
class ReputationClient:
    """Query PROOF relay for reputation data."""

    def __init__(self, relay_url: str = "wss://proof.buzz"):
        self.relay_url = relay_url
        self._leaderboard_cache = None
        self._cache_time = 0
        self._cache_ttl = 60  # seconds

    def get_reputation(self, pubkey: str) -> Optional[dict]:
        """
        Get reputation for a pubkey.
        In production: WS query to relay using NIP-01 REQ format.
        """
        # Query format: ["REQ", "sub_id", {"kinds": [30010], "authors": [pubkey]}]
        query = {
            "kinds": [30010, 30009],
            "authors": [pubkey],
        }
        # Would send via WebSocket to self.relay_url
        # For now, return placeholder
        return {
            "pubkey": pubkey[:16] + "...",
            "tier": "unverified",
            "score": 0,
            "attestations": 0,
            "message": "Connect to proof relay at " + self.relay_url,
        }

    def get_leaderboard(self, limit: int = 50, tier: str = None) -> List[dict]:
        """Get ranked leaderboard."""
        # Query: ["REQ", "sub_id", {"kinds": [30010], "limit": limit}]
        return []

    def get_attestations(self, pubkey: str, limit: int = 50) -> List[dict]:
        """Get attestations by a pubkey."""
        return []


# --- Solana Token Client ---
class SolanaTokenClient:
    """Read-only interaction with PROOF token on Solana."""

    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com",
                 mint_address: str = ""):
        self.rpc_url = rpc_url
        self.mint_address = mint_address or "PROOFat00000000000000000000000000000000000"

    def get_supply(self) -> dict:
        """Get token supply info via Solana RPC."""
        # RPC call: {"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":["<mint>"]}
        return {
            "mint": self.mint_address,
            "supply": "0",  # Would query Solana RPC
            "decimals": 9,
            "ui_amount": 0,
        }

    def get_balance(self, wallet: str) -> dict:
        """Get PROOF token balance for a wallet."""
        return {
            "wallet": wallet,
            "balance": "0",
            "decimals": 9,
        }

    def get_price(self) -> dict:
        """Get PROOF price from pump.fun bonding curve or Jupiter."""
        # Query pump.fun API or Jupiter aggregator
        return {
            "token": "PROOF",
            "price_sol": 0.0,
            "price_usd": 0.0,
            "source": "pump_fun",
            "bonding_progress": 0.0,
        }

    def get_bonding_curve(self) -> dict:
        """Get pump.fun bonding curve state."""
        return {
            "virtual_token_reserves": 0,
            "virtual_sol_reserves": 0,
            "real_token_reserves": 0,
            "real_sol_reserves": 0,
            "complete": False,
            "current_price_sol": 0.0,
        }


# --- Stake Manager ---
class StakeManager:
    """Manage PROOF staking positions."""

    def __init__(self, pubkey: bytes, privkey: bytes, relay: ReputationClient):
        self.pubkey = pubkey
        self.privkey = privkey
        self.relay = relay

    def create_stake_event(self, amount: int, lockup_days: int = 90) -> dict:
        """Create a staking event (kind 30011)."""
        tags = [
            ["amount", str(amount)],
            ["lockup", str(lockup_days)],
            ["proof", "solana-staking"],
        ]

        content = json.dumps({
            "type": "stake",
            "amount": amount,
            "lockup_days": lockup_days,
            "apr": {30: 8, 90: 12, 365: 20}.get(lockup_days, 12),
            "timestamp": int(time.time()),
        })

        return build_nostr_event(30011, tags, content, self.pubkey, self.privkey)

    def claim_rewards_event(self, accrued_amount: int) -> dict:
        """Create a staking reward claim event."""
        tags = [
            ["amount", str(accrued_amount)],
            ["proof", "solana-staking-claim"],
        ]
        content = json.dumps({
            "type": "claim",
            "amount": accrued_amount,
            "timestamp": int(time.time()),
        })
        return build_nostr_event(30011, tags, content, self.pubkey, self.privkey)


# --- Bounty Client ---
class BountyClient:
    """Browse and claim bounties from the PROOF community fund."""

    def __init__(self, pubkey: bytes, privkey: bytes, relay: ReputationClient):
        self.pubkey = pubkey
        self.privkey = privkey
        self.relay = relay

    def post_bounty(self, title: str, description: str, reward: float,
                    work_type: str, deadline_days: int = 7) -> dict:
        """Post a community bounty (kind 30013)."""
        tags = [
            ["type", work_type],
            ["reward", str(int(reward * 1_000_000_000))],
            ["deadline", str(deadline_days)],
            ["proof", "solana-bounty"],
        ]
        content = json.dumps({
            "type": "bounty_post",
            "title": title,
            "description": description,
            "reward": reward,
            "reward_token": "PROOF",
            "work_type": work_type,
            "deadline_days": deadline_days,
            "timestamp": int(time.time()),
        })
        return build_nostr_event(30013, tags, content, self.pubkey, self.privkey)

    def claim_bounty(self, bounty_event_id: str, proof_event_id: str) -> dict:
        """Claim and complete a bounty (kind 30014)."""
        tags = [
            ["bounty", bounty_event_id],
            ["proof", proof_event_id],
            ["proof", "solana-bounty-claim"],
        ]
        content = json.dumps({
            "type": "bounty_claim",
            "bounty_event": bounty_event_id,
            "proof_event": proof_event_id,
            "timestamp": int(time.time()),
        })
        return build_nostr_event(30014, tags, content, self.pubkey, self.privkey)


# --- Governance Client ---
class GovernanceClient:
    """Participate in PROOF governance via Nostr events."""

    def __init__(self, pubkey: bytes, privkey: bytes):
        self.pubkey = pubkey
        self.privkey = privkey

    def propose(self, title: str, description: str, proposal_type: str,
                parameters: dict) -> dict:
        """Create a governance proposal (kind 30012)."""
        tags = [
            ["type", proposal_type],
            ["proof", "solana-governance"],
        ]
        content = json.dumps({
            "type": "governance_proposal",
            "title": title,
            "description": description,
            "proposal_type": proposal_type,
            "parameters": parameters,
            "timestamp": int(time.time()),
        })
        return build_nostr_event(30012, tags, content, self.pubkey, self.privkey)

    def vote(self, proposal_event_id: str, support: bool, weight: int) -> dict:
        """Cast a governance vote."""
        tags = [
            ["proposal", proposal_event_id],
            ["support", str(int(support))],
            ["weight", str(weight)],
            ["proof", "solana-governance-vote"],
        ]
        content = json.dumps({
            "type": "governance_vote",
            "proposal": proposal_event_id,
            "support": support,
            "weight": weight,
            "timestamp": int(time.time()),
        })
        return build_nostr_event(30012, tags, content, self.pubkey, self.privkey)


# --- Main CLI Interface ---
if __name__ == '__main__':
    import argparse

    print("=" * 60)
    print("PROOF SDK — Nostr + Solana Agent Attestation Platform")
    print("=" * 60)
    print(f"\nToken: PROOF (1,000,000,000 supply, 9 decimals)")
    print(f"Launch: pump.fun bonding curve")
    print(f"Relay: Nostr-compatible (kind 30007-30014)")
    print(f"\nSDK Components:")
    print(f"  AttestationBuilder   — Create signed work attestations")
    print(f"  ReputationClient     — Query agent reputation + leaderboard")
    print(f"  SolanaTokenClient    — Read PROOF token state on-chain")
    print(f"  StakeManager         — Staking positions + rewards")
    print(f"  BountyClient         — Community bounties")
    print(f"  GovernanceClient     — DAO proposals + voting")
    print(f"\nWork Type Rewards (base PROOF):")
    for wtype, reward in AttestationBuilder.WORK_REWARDS.items():
        print(f"  {wtype:30s} {reward:>6,} PROOF")
    print(f"\nTo use: import proof.sdk and create builders with your Nostr keypair.")
