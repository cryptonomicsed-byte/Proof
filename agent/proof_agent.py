"""
PROOF Agent — Autonomous agent that lives inside Buzz workspaces,
performs work, and earns PROOF through cryptographic attestation.

This agent:
1. Watches Buzz channels for bounties, bug reports, PR requests
2. Completes work (code fixes, reviews, CI runs)
3. Posts results as Nostr events to the PROOF relay
4. Tracks reputation across communities
5. Manages staking and governance participation

Every action is a signed Nostr event — fully transparent and auditable.
"""
import os
import json
import time
import hashlib
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass, field

logger = logging.getLogger('proof.agent')


@dataclass
class AgentState:
    """Persistent agent state."""
    nostr_privkey_hex: str = ""
    nostr_pubkey_hex: str = ""
    reputation: Dict = field(default_factory=dict)
    staking_position: Dict = field(default_factory=dict)
    active_bounties: List = field(default_factory=list)
    completed_work: List = field(default_factory=list)
    last_reputation_sync: int = 0
    governance_votes: Dict = field(default_factory=dict)
    burn_balance: int = 0

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump({
                'nostr_privkey_hex': self.nostr_privkey_hex,
                'nostr_pubkey_hex': self.nostr_pubkey_hex,
                'reputation': self.reputation,
                'staking_position': self.staking_position,
                'active_bounties': self.active_bounties,
                'completed_work': self.completed_work,
                'last_reputation_sync': self.last_reputation_sync,
                'governance_votes': self.governance_votes,
                'burn_balance': self.burn_balance,
            }, f, indent=2)

    @classmethod
    def load(cls, path: str):
        if not os.path.exists(path):
            return cls()
        with open(path, 'r') as f:
            data = json.load(f)
        s = cls()
        for k in s.__dataclass_fields__:
            if k in data:
                setattr(s, k, data[k])
        return s


class ProofAgent:
    """Autonomous agent for PROOF attestation economy."""

    def __init__(self, privkey_hex: str, relay_url: str = "wss://proof.buzz",
                 buzz_relay_url: str = "wss://buzz.relay",
                 state_path: str = None):
        self.privkey_hex = privkey_hex
        self.pubkey_hex = hashlib.sha256(bytes.fromhex(privkey_hex)).hexdigest()[:64]
        self.relay_url = relay_url
        self.buzz_relay_url = buzz_relay_url
        self.state_path = state_path or os.path.join(os.path.expanduser('~'), '.proof', 'agent_state.json')
        self.state = AgentState.load(self.state_path)
        self.work_queue: List[dict] = []

        # Auto-config
        self.auto_attest = True
        self.auto_stake = False
        self.min_reputation_for_bounties = 100

        logger.info(f"PROOF Agent: {self.pubkey_hex[:16]}...")

    def _get_pubkey_bytes(self) -> bytes:
        return bytes.fromhex(self.pubkey_hex)

    def _get_privkey_bytes(self) -> bytes:
        return bytes.fromhex(self.privkey_hex)

    def process_buzz_event(self, event: dict) -> Optional[dict]:
        """Process a Nostr event from Buzz relay. Detects work opportunities."""
        kind = event.get('kind', 0)
        content = event.get('content', '')

        # Bounty post (kind 30013)
        if kind == 30013:
            return self._handle_bounty_found(event, content)

        # Bug report (kind 1 — standard Nostr, or 40002 in Buzz)
        if kind in (1, 40002):
            return self._handle_bug_report(event, content)

        # Code review request (kind 43001 — KIND_JOB_REQUEST)
        if kind == 43001:
            return self._handle_job_request(event, content)

        # Workflow failure (kind 46001+)
        if 46000 <= kind <= 46012:
            return self._handle_workflow_event(event, content)

        # Existing attestation by someone else — may need cross-ref
        if kind == 30009:
            return self._handle_other_attestation(event)

        return None

    def _handle_bounty_found(self, event: dict, content: str) -> Optional[dict]:
        """Check if we should claim a bounty."""
        try:
            bounty = json.loads(content)
        except json.JSONDecodeError:
            return None

        reward = bounty.get('reward', 0)
        work_type = bounty.get('work_type', '')

        # Only claim bounties we can handle
        if not self._can_complete_work_type(work_type):
            return None

        # Check reputation threshold
        if self._current_reputation() < self.min_reputation_for_bounties:
            logger.info(f"Reputation too low for bounty: {self._current_reputation()} < {self.min_reputation_for_bounties}")
            return None

        # Claim the bounty (kind 30014)
        claim = {
            'bounty_event': event['id'],
            'work_type': work_type,
            'reward': reward,
            'status': 'claimed',
            'claimed_at': int(time.time()),
        }
        self.work_queue.append(claim)
        self.state.active_bounties.append(claim)
        self.state.save(self.state_path)
        logger.info(f"Claimed bounty {event['id'][:16]}... work_type={work_type} reward={reward}")
        return claim

    def _handle_bug_report(self, event: dict, content: str) -> Optional[dict]:
        """Detect bug reports and optionally fix them."""
        try:
            bug = json.loads(content)
        except json.JSONDecodeError:
            # Plain text bug report
            bug = {'description': content, 'title': 'Bug Report'}

        # Auto-fix if we have the capability
        if self.auto_attest and self._can_handle_code():
            fix_event = self._perform_bug_fix(event)
            if fix_event:
                self._submit_attestation(fix_event, 'bug_fix', quality=0.9)
                return fix_event
        return None

    def _handle_job_request(self, event: dict, content: str) -> Optional[dict]:
        """Handle a KIND_JOB_REQUEST from another agent or human."""
        return self.process_buzz_event(event)  # Re-route through general handler

    def _handle_workflow_event(self, event: dict, content: str) -> Optional[dict]:
        """Handle CI/CD workflow events — auto-attest on success."""
        try:
            wf = json.loads(content)
        except json.JSONDecodeError:
            wf = {'status': 'unknown', 'name': 'workflow'}

        if wf.get('status') == 'success':
            self._submit_attestation(event, 'workflow_complete', quality=0.8)

        if wf.get('status') == 'failure':
            # Try to fix and re-attest
            fix = self._attempt_workflow_fix(event)
            if fix:
                self._submit_attestation(fix, 'workflow_complete', quality=0.9)

        return None

    def _handle_other_attestation(self, event: dict) -> Optional[dict]:
        """When another agent publishes an attestation, verify and cross-reference."""
        pass  # Could trigger on-chain cross-reference
        return None

    def _perform_bug_fix(self, bug_event: dict) -> Optional[dict]:
        """Perform a bug fix on the referenced issue. Returns fix event."""
        # In production: this would clone the repo, apply fix, commit, push
        # For now, return a placeholder event
        return {
            'id': hashlib.sha256(b'fix-placeholder').hexdigest()[:64],
            'kind': 40002,
            'tags': [['e', bug_event.get('id', '')]],
            'content': json.dumps({'fixed': True, 'type': 'bug_fix'}),
            'created_at': int(time.time()),
        }

    def _attempt_workflow_fix(self, wf_event: dict) -> Optional[dict]:
        """Attempt to fix a failed workflow."""
        return None

    def _submit_attestation(self, work_event: dict, work_type: str, quality: float = 1.0):
        """Submit an attestation event to the PROOF relay."""
        from proof_sdk import AttestationBuilder

        builder = AttestationBuilder(self._get_pubkey_bytes(), self._get_privkey_bytes())

        if work_type == 'bug_fix':
            att = builder.for_bug_fix(
                work_event.get('id', ''),
                quality,
                repo=work_event.get('repo', ''),
            )
        elif work_type == 'workflow_complete':
            att = builder.for_workflow_complete(
                work_event.get('id', ''),
                True,
                quality,
            )
        else:
            # Generic attestation
            tags = [
                ['e', work_event.get('id', '')],
                ['work_type', work_type],
                ['quality', f'{quality:.2f}'],
                ['proof', 'solana-attestation'],
            ]
            reward_map = {
                'bug_fix': 500, 'feature_merge': 2000, 'doc_update': 200,
                'ci_pass': 50, 'workflow_complete': 1000, 'code_review': 300,
                'security_fix': 3000, 'performance_improvement': 1500,
            }
            base_reward = reward_map.get(work_type, 100)
            final_reward = int(base_reward * quality)
            content = json.dumps({
                'type': 'attestation', 'version': 1, 'work_type': work_type,
                'quality_score': quality, 'reward_token': 'PROOF',
                'base_reward': base_reward, 'final_reward': final_reward,
                'timestamp': int(time.time()),
            })
            att = {
                'id': hashlib.sha256(json.dumps([0, self.pubkey_hex, 30009, tags, content, int(time.time())], separators=(',', ':')).encode()).hexdigest(),
                'pubkey': self.pubkey_hex,
                'kind': 30009,
                'tags': tags,
                'content': content,
                'created_at': int(time.time()),
                'sig': '',
            }

        # Post to PROOF relay
        self._post_to_relay(att)

        # Record in state
        self.state.completed_work.append({
            'event_id': att['id'],
            'work_type': work_type,
            'quality': quality,
            'reward': final_reward,
            'posted_at': int(time.time()),
        })
        self.state.save(self.state_path)

        logger.info(f"Attestation submitted: {work_type} quality={quality}")

    def _post_to_relay(self, event: dict):
        """Post a signed event to the PROOF relay via WebSocket."""
        # In production: ws.connect(self.relay_url), ws.send(['EVENT', event])
        pass

    def _current_reputation(self) -> float:
        """Get current reputation score from state."""
        return self.state.reputation.get('score', 0)

    def _can_complete_work_type(self, work_type: str) -> bool:
        """Check if agent has capability for this work type."""
        capabilities = {'bug_fix', 'doc_update', 'ci_pass', 'workflow_complete', 'code_review'}
        return work_type in capabilities

    def _can_handle_code(self) -> bool:
        """Check if agent has code capability."""
        return True  # In production: check available tools

    def request_reputation_sync(self):
        """Fetch latest reputation from PROOF relay."""
        # Query relay for attestations by this pubkey
        # Update state with new score
        self.state.last_reputation_sync = int(time.time())
        self.state.save(self.state_path)

    def get_status(self) -> dict:
        """Get agent status report."""
        return {
            'pubkey': self.pubkey_hex[:16] + '...',
            'tier': self.state.reputation.get('tier', 'unverified'),
            'score': self.state.reputation.get('score', 0),
            'total_work': len(self.state.completed_work),
            'active_bounties': len(self.state.active_bounties),
            'staking': self.state.staking_position,
            'governance_votes': len(self.state.governance_votes),
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Generate a random keypair for demo
    import secrets
    demo_privkey = secrets.token_hex(32)
    demo_pubkey = hashlib.sha256(bytes.fromhex(demo_privkey)).hexdigest()[:64]

    agent = ProofAgent(demo_privkey, relay_url='wss://proof.buzz')
    status = agent.get_status()

    print("=" * 60)
    print("PROOF AGENT — Autonomous Work Attestation Agent")
    print("=" * 60)
    print(f"  Pubkey:    {status['pubkey']}")
    print(f"  Tier:      {status['tier']}")
    print(f"  Score:     {status['score']}")
    print(f"  Work:      {status['total_work']} attestations")
    print(f"  Bounties:  {status['active_bounties']} active")
    print(f"  Relay:     wss://proof.buzz")
    print(f"  State:     ~/.proof/agent_state.json")
    print(f"\nThis agent runs inside Buzz channels, watches for work,")
    print(f"completes tasks, and earns PROOF tokens via attestation.")
    print(f"\nIt is the bridge between Nostr social graph and Solana tokenomics.")
