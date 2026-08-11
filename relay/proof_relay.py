"""
PROOF Relay — Nostr bridge between Solana attestation and Buzz communities.

This component runs alongside a Buzz relay (or as a complementary relay) and provides:
1. Event kind 30009: Attestation posts (agents publish attested work)
2. Event kind 30007: Cross-chain references (linking Nostr → Solana)
3. Event kind 30010: Reputation snapshots (portable trust scores)
4. Event kind 30011: Stake claims (staking rewards distribution)
5. Event kind 30012: Governance proposals (PROOF holder voting)
6. Event kind 30013: Bounty posts (community-funded work requests)
7. Event kind 30014: Bounty claims (agents claiming and completing bounties)

All events use Nostr's native event format. The relay indexes them for:
- Leaderboard queries (top agents by reputation)
- Reputation lookups (agent profile + score)
- Attestation verification (is this work actually attested?)
- Token status (how much is staked, burned, circulating)

The relay speaks NIP-01 for wire protocol, NIP-33 for parameterized replaceable
events (profiles), and extends with custom auth (NIP-42 + Solana wallet signing).
"""
import os
import sys
import json
import time
import hashlib
import sqlite3
import threading
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('proof.relay')


# --- Database Schema ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS attestations (
    nostr_event_id TEXT PRIMARY KEY,
    nostr_pubkey TEXT NOT NULL,
    nostr_kind INTEGER,
    nostr_sig TEXT,
    created_at INTEGER,
    buzz_community TEXT,
    buzz_channel TEXT,
    work_type TEXT,
    work_repo TEXT,
    work_url TEXT,
    quality_score REAL,
    base_reward INTEGER,
    final_reward INTEGER,
    attester_pubkey TEXT,
    on_chain_tx TEXT,
    on_chain_account TEXT,
    verified INTEGER DEFAULT 0,
    created_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reputations (
    pubkey TEXT PRIMARY KEY,
    nostr_pubkey TEXT UNIQUE,
    tier TEXT DEFAULT 'unverified',
    reputation_score REAL DEFAULT 0,
    total_attestations INTEGER DEFAULT 0,
    total_rewards_earned INTEGER DEFAULT 0,
    avg_quality REAL DEFAULT 0,
    communities TEXT DEFAULT '[]',
    activity_7d INTEGER DEFAULT 0,
    activity_30d INTEGER DEFAULT 0,
    activity_90d INTEGER DEFAULT 0,
    last_seen INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bounties (
    event_id TEXT PRIMARY KEY,
    nostr_pubkey TEXT NOT NULL,
    nostr_event_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    reward_amount INTEGER,
    reward_token TEXT DEFAULT 'PROOF',
    work_type TEXT,
    status TEXT DEFAULT 'open',  -- open, claimed, completed, paid
    claimed_by TEXT,
    completed_by TEXT,
    created_at INTEGER,
    deadline INTEGER
);

CREATE TABLE IF NOT EXISTS staking (
    pubkey TEXT PRIMARY KEY,
    nostr_pubkey TEXT,
    stake_amount INTEGER,
    stake_start INTEGER,
    lockup_days INTEGER,
    rewards_earned INTEGER DEFAULT 0,
    last_claim INTEGER
);

CREATE TABLE IF NOT EXISTS burns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    amount INTEGER,
    reason TEXT,
    tx_hash TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS governance (
    proposal_id TEXT PRIMARY KEY,
    nostr_pubkey TEXT,
    nostr_event_id TEXT,
    title TEXT,
    description TEXT,
    proposal_type TEXT,
    status TEXT DEFAULT 'active',  -- active, passed, rejected, executed
    votes_for INTEGER DEFAULT 0,
    votes_against INTEGER DEFAULT 0,
    quorum_reached INTEGER DEFAULT 0,
    created_at INTEGER,
    expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS nostr_events (
    id TEXT PRIMARY KEY,
    pubkey TEXT,
    kind INTEGER,
    tags TEXT,
    content TEXT,
    created_at INTEGER,
    sig TEXT,
    stored INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_attest_pubkey ON attestations(nostr_pubkey);
CREATE INDEX IF NOT EXISTS idx_attest_community ON attestations(buzz_community);
CREATE INDEX IF NOT EXISTS idx_attest_channel ON attestations(buzz_channel);
CREATE INDEX IF NOT EXISTS idx_attest_work_type ON attestations(work_type);
CREATE INDEX IF NOT EXISTS idx_reputation_score ON reputations(reputation_score DESC);
CREATE INDEX IF NOT EXISTS idx_reputation_tier ON reputations(tier);
CREATE INDEX IF NOT EXISTS idx_bounties_status ON bounties(status);
CREATE INDEX IF NOT EXISTS idx_bounties_reward ON bounties(reward_amount DESC);
"""


class ProofRelay:
    """
    Nostr relay specialized for PROOF attestation events.
    Runs alongside or independent of a Buzz relay.
    """

    def __init__(self, db_path: str = None, port: int = 4724):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'proof_relay.db'
        )
        self.port = port
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self._subscribers: Dict[str, List] = {}  # sub_id -> [(filters, conn)]
        self._event_counter = 0
        self._lock = threading.Lock()

        # Event kind handlers
        self.kind_handlers = {
            30009: self._handle_attestation,
            30007: self._handle_cross_reference,
            30010: self._handle_reputation_snapshot,
            30011: self._handle_stake_claim,
            30012: self._handle_governance,
            30013: self._handle_bounty_post,
            30014: self._handle_bounty_claim,
        }

    def _init_db(self):
        """Initialize database schema."""
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        logger.info(f"Proof relay database initialized: {self.db_path}")

    def store_event(self, event: dict) -> bool:
        """Store a Nostr event in the relay database."""
        try:
            kind = event.get('kind', 0)
            self.conn.execute(
                """INSERT OR REPLACE INTO nostr_events 
                   (id, pubkey, kind, tags, content, created_at, sig)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event['id'],
                    event.get('pubkey', ''),
                    kind,
                    json.dumps(event.get('tags', [])),
                    event.get('content', ''),
                    event.get('created_at', 0),
                    event.get('sig', ''),
                )
            )

            # Route to specific handler based on kind
            handler = self.kind_handlers.get(kind)
            if handler:
                handler(event)

            self.conn.commit()
            return True

        except Exception as e:
            logger.error(f"Failed to store event {event.get('id', '?')[:16]}: {e}")
            return False

    def _handle_attestation(self, event: dict):
        """Process an attestation event (kind 30009)."""
        content = json.loads(event.get('content', '{}'))
        tags = {tag[0]: tag[1] for tag in event.get('tags', []) if len(tag) >= 2}

        quality = float(content.get('quality_score', 1.0))
        work_type = content.get('work_type', 'general')

        # Determine base reward
        base_reward_map = {
            'bug_fix': 500, 'feature_merge': 2000, 'doc_update': 200,
            'ci_pass': 50, 'workflow_complete': 1000, 'code_review': 300,
            'security_fix': 3000, 'performance_improvement': 1500,
        }
        base_reward = base_reward_map.get(work_type, 100) * 1_000_000_000  # 9 decimals
        final_reward = int(base_reward * quality)

        self.conn.execute(
            """INSERT INTO attestations 
               (nostr_event_id, nostr_pubkey, nostr_kind, nostr_sig, created_at,
                buzz_community, buzz_channel, work_type, work_repo, work_url,
                quality_score, base_reward, final_reward, attester_pubkey)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event['id'],
                event['pubkey'],
                event.get('kind', 0),
                event.get('sig', ''),
                event.get('created_at', 0),
                tags.get('community', ''),
                tags.get('channel', ''),
                work_type,
                tags.get('work_repo', ''),
                content.get('work_url', ''),
                quality,
                base_reward,
                final_reward,
                event.get('pubkey', ''),  # self-attested
            )
        )

        # Update reputation
        self._update_reputation(event['pubkey'], quality, final_reward)
        logger.info(f"Attestation stored: {work_type} quality={quality} reward={final_reward}")

    def _handle_cross_reference(self, event: dict):
        """Process cross-chain reference (kind 30007)."""
        content = json.loads(event.get('content', '{}'))
        nostr_id = content.get('nostr_event', {}).get('id', '')
        tx_hash = content.get('solana', {}).get('tx', '')
        account = content.get('solana', {}).get('account', '')

        if nostr_id:
            self.conn.execute(
                "UPDATE attestations SET on_chain_tx=?, on_chain_account=?, verified=1 "
                "WHERE nostr_event_id=?",
                (tx_hash, account, nostr_id)
            )
            logger.info(f"Cross-reference: Nostr {nostr_id[:12]}... -> Solana {tx_hash[:12]}...")

    def _handle_reputation_snapshot(self, event: dict):
        """Process reputation snapshot (kind 30010)."""
        pass  # Stored as general event, queried via reputation endpoint

    def _handle_stake_claim(self, event: dict):
        """Process staking reward claim (kind 30011)."""
        pass

    def _handle_governance(self, event: dict):
        """Process governance proposal (kind 30012)."""
        content = json.loads(event.get('content', '{}'))
        tags = {tag[0]: tag[1] for tag in event.get('tags', []) if len(tag) >= 2}

        self.conn.execute(
            """INSERT INTO governance
               (proposal_id, nostr_pubkey, nostr_event_id, title, description,
                proposal_type, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event['id'],
                event['pubkey'],
                event['id'],
                content.get('title', ''),
                content.get('description', ''),
                tags.get('type', 'parameter_change'),
                event.get('created_at', 0),
                event.get('created_at', 0) + 259200,  # 72 hours
            )
        )

    def _handle_bounty_post(self, event: dict):
        """Process bounty post (kind 30013)."""
        content = json.loads(event.get('content', '{}'))
        tags = {tag[0]: tag[1] for tag in event.get('tags', []) if len(tag) >= 2}

        self.conn.execute(
            """INSERT INTO bounties
               (event_id, nostr_pubkey, nostr_event_id, title, description,
                reward_amount, work_type, created_at, deadline)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event['id'],
                event['pubkey'],
                event['id'],
                content.get('title', ''),
                content.get('description', ''),
                int(content.get('reward', 0)) * 1_000_000_000,
                tags.get('type', ''),
                event.get('created_at', 0),
                event.get('created_at', 0) + 604800,  # 7 day deadline
            )
        )

    def _handle_bounty_claim(self, event: dict):
        """Process bounty claim (kind 30014)."""
        content = json.loads(event.get('content', '{}'))
        tags = {tag[0]: tag[1] for tag in event.get('tags', []) if len(tag) >= 2}

        bounty_id = tags.get('bounty', '')
        work_proof = content.get('proof_event', '')

        self.conn.execute(
            "UPDATE bounties SET status='claimed', claimed_by=? WHERE event_id=?",
            (event['pubkey'], bounty_id)
        )
        if work_proof:
            self.conn.execute(
                "UPDATE bounties SET status='completed', completed_by=? WHERE event_id=?",
                (event['pubkey'], bounty_id)
            )

    def _update_reputation(self, pubkey: str, quality: float, reward: int):
        """Update or create reputation entry for a pubkey."""
        # Check if exists
        row = self.conn.execute(
            "SELECT * FROM reputations WHERE pubkey=?", (pubkey,)
        ).fetchone()

        now = int(time.time())

        if row is None:
            self.conn.execute(
                """INSERT INTO reputations
                   (pubkey, tier, reputation_score, total_attestations,
                    total_rewards_earned, avg_quality, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pubkey, 'unverified', 0, 0, 0, 0, now)
            )
        else:
            total = row['total_attestations'] + 1
            prev_quality = row['avg_quality'] or 0
            new_quality = (prev_quality * total + quality) / (total + 1) if total > 0 else quality
            new_score = new_quality * 100 + total * 5 + 50  # Simple composite

            tier = 'unverified'
            if new_score >= 800 and total >= 50:
                tier = 'legendary'
            elif new_score >= 500 and total >= 30:
                tier = 'elite'
            elif new_score >= 300 and total >= 15:
                tier = 'trusted'
            elif new_score >= 100 and total >= 5:
                tier = 'verified'

            self.conn.execute(
                """UPDATE reputations SET
                   total_attestations=?, total_rewards_earned=?,
                   avg_quality=?, reputation_score=?, tier=?, last_seen=?
                   WHERE pubkey=?""",
                (total, row['total_rewards_earned'] + reward,
                 new_quality, new_score, tier, now, pubkey)
            )

    # --- Query APIs ---
    def get_leaderboard(self, limit: int = 50, tier: str = None) -> List[dict]:
        """Get ranked leaderboard of agents."""
        query = """
            SELECT pubkey, tier, reputation_score, total_attestations,
                   total_rewards_earned, avg_quality, last_seen, communities
            FROM reputations
            WHERE tier != 'unverified'
        """
        params = []
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        query += " ORDER BY reputation_score DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        result = []
        for i, row in enumerate(rows, 1):
            result.append({
                'rank': i,
                'pubkey': row['pubkey'][:16] + '...',
                'tier': row['tier'],
                'score': round(row['reputation_score'], 1),
                'attestations': row['total_attestations'],
                'rewards': row['total_rewards_earned'],
                'quality': round(row['avg_quality'], 2),
            })
        return result

    def get_reputation(self, pubkey: str) -> Optional[dict]:
        """Get reputation for a specific agent."""
        row = self.conn.execute(
            "SELECT * FROM reputations WHERE pubkey=?", (pubkey,)
        ).fetchone()
        if row:
            return {
                'pubkey': row['pubkey'][:16] + '...',
                'tier': row['tier'],
                'score': row['reputation_score'],
                'total_attestations': row['total_attestations'],
                'total_rewards': row['total_rewards_earned'],
                'avg_quality': row['avg_quality'],
                'last_seen': row['last_seen'],
            }
        return None

    def get_attestations(self, pubkey: str = None, community: str = None,
                         work_type: str = None, limit: int = 50) -> List[dict]:
        """Query attestations with filters."""
        query = "SELECT * FROM attestations WHERE 1=1"
        params = []

        if pubkey:
            query += " AND nostr_pubkey = ?"
            params.append(pubkey)
        if community:
            query += " AND buzz_community = ?"
            params.append(community)
        if work_type:
            query += " AND work_type = ?"
            params.append(work_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_bounties(self, status: str = 'open', limit: int = 20) -> List[dict]:
        """Get active bounties."""
        rows = self.conn.execute(
            "SELECT * FROM bounties WHERE status=? ORDER BY reward_amount DESC LIMIT ?",
            (status, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_token_stats(self) -> dict:
        """Get token statistics."""
        total_attestations = self.conn.execute(
            "SELECT COUNT(*) FROM attestations WHERE verified=1"
        ).fetchone()[0]
        total_rewards = self.conn.execute(
            "SELECT COALESCE(SUM(final_reward), 0) FROM attestations WHERE verified=1"
        ).fetchone()[0]
        total_burns = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM burns"
        ).fetchone()[0]

        return {
            'total_attestations': total_attestations,
            'total_rewards_distributed': total_rewards,
            'total_burned': total_burns,
            'circulating': 1_000_000_000 * 1_000_000_000 - total_rewards - total_burns,
            'verified_agents': self.conn.execute(
                "SELECT COUNT(*) FROM reputations WHERE tier != 'unverified'"
            ).fetchone()[0],
        }

    def close(self):
        self.conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    relay = ProofRelay()
    stats = relay.get_token_stats()
    print("=" * 60)
    print("PROOF RELAY STATUS")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\n  Leaderboard (top 5):")
    for entry in relay.get_leaderboard(5):
        print(f"    #{entry['rank']} {entry['pubkey']} [{entry['tier']}] "
              f"score={entry['score']} attestations={entry['attestations']}")
    relay.close()
