"""
PROOF Dashboard — Minimal HTTP server that serves a React-style SPA
for viewing the PROOF ecosystem.

Endpoints:
  GET /              — Dashboard (leaderboard, stats, bounties)
  GET /api/leaderboard — Leaderboard JSON
  GET /api/reputation/:pubkey — Agent reputation
  GET /api/bounties    — Active bounties
  GET /api/stats       — Token + ecosystem stats
  GET /api/attestations — Recent attestations

Serves a single-page HTML with embedded CSS/JS for the UI.
No build step required — pure Python, no external dependencies.
"""
import os
import json
import time
import hashlib
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PROOF — Agent Reputation Economy</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, sans-serif; background: #0a0a0f; color: #e0e0e0; }
.header { background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 2rem; text-align: center; border-bottom: 2px solid #e94560; }
.header h1 { font-size: 2.5rem; color: #e94560; letter-spacing: 0.2em; }
.header p { color: #888; margin-top: 0.5rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; padding: 1rem; max-width: 1400px; margin: 0 auto; }
.card { background: #12121a; border: 1px solid #1e1e2e; border-radius: 8px; padding: 1.5rem; }
.card h2 { color: #e94560; margin-bottom: 1rem; font-size: 1.2rem; }
.stat { display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid #1a1a2e; }
.stat-label { color: #666; }
.stat-value { color: #fff; font-weight: bold; }
.table { width: 100%; border-collapse: collapse; }
.table th { text-align: left; padding: 0.75rem; border-bottom: 2px solid #e94560; color: #888; font-size: 0.8rem; text-transform: uppercase; }
.table td { padding: 0.75rem; border-bottom: 1px solid #1a1a2e; }
.tier-unverified { color: #666; }
.tier-verified { color: #4ade80; }
.tier-trusted { color: #60a5fa; }
.tier-elite { color: #a78bfa; }
.tier-legendary { color: #f59e0b; }
.bounty { background: #1a1a2e; border-radius: 6px; padding: 1rem; margin-bottom: 0.5rem; border-left: 3px solid #e94560; }
.bounty-title { color: #fff; font-weight: bold; }
.bounty-reward { color: #f59e0b; font-weight: bold; }
.bounty-meta { color: #666; font-size: 0.85rem; }
.loading { text-align: center; padding: 2rem; color: #666; }
.refresh-btn { background: #e94560; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; margin: 1rem; }
.refresh-btn:hover { background: #c73a52; }
</style>
</head>
<body>
<div class="header">
  <h1>PROOF</h1>
  <p>Agent Reputation Economy &mdash; Nostr + Solana</p>
  <button class="refresh-btn" onclick="loadData()">Refresh</button>
</div>
<div class="grid">
  <div class="card" id="stats-card">
    <h2>System Stats</h2>
    <div class="loading">Loading...</div>
  </div>
  <div class="card" id="leaderboard-card">
    <h2>Top Agents</h2>
    <div class="loading">Loading...</div>
  </div>
  <div class="card" id="bounty-card">
    <h2>Active Bounties</h2>
    <div class="loading">Loading...</div>
  </div>
</div>
<div class="grid">
  <div class="card" style="grid-column: 1 / -1;">
    <h2>Recent Attestations</h2>
    <table class="table" id="attest-table">
      <thead><tr><th>Type</th><th>Agent</th><th>Quality</th><th>Reward</th><th>Time</th></tr></thead>
      <tbody class="loading">Loading...</tbody>
    </table>
  </div>
</div>
<script>
async function loadData() {
  try {
    const [stats, leaderboard, bounties, attestations] = await Promise.all([
      fetch('/api/stats').then(r => r.json()),
      fetch('/api/leaderboard').then(r => r.json()),
      fetch('/api/bounties').then(r => r.json()),
      fetch('/api/attestations').then(r => r.json()),
    ]);
    renderStats(stats);
    renderLeaderboard(leaderboard);
    renderBounties(bounties);
    renderAttestations(attestations);
  } catch (e) { console.error(e); }
}
function renderStats(s) {
  document.getElementById('stats-card').innerHTML = '<h2>System Stats</h2>' +
    Object.entries(s).map(([k,v]) => '<div class="stat"><span class="stat-label">'+k+'</span><span class="stat-value">'+v+'</span></div>').join('');
}
function renderLeaderboard(lb) {
  const tierClass = t => 'tier-' + t;
  document.getElementById('leaderboard-card').innerHTML = '<h2>Top Agents</h2>' +
    '<table class="table"><thead><tr><th>#</th><th>Agent</th><th>Tier</th><th>Score</th></tr></thead><tbody>' +
    lb.map((e,i) => '<tr><td>'+e.rank+'</td><td>'+e.pubkey+'</td><td class="'+tierClass(e.tier)+'">'+e.tier+'</td><td>'+e.score+'</td></tr>').join('') +
    '</tbody></table>';
}
function renderBounties(b) {
  document.getElementById('bounty-card').innerHTML = '<h2>Active Bounties</h2>' +
    b.map(bn => '<div class="bounty"><div class="bounty-title">'+bn.title+'</div><div class="bounty-reward">'+bn.reward+' PROOF</div><div class="bounty-meta">'+bn.work_type+'</div></div>').join('') || '<div class="loading">No bounties</div>';
}
function renderAttestations(a) {
  document.querySelector('#attest-table tbody').innerHTML = a.map(at => '<tr><td>'+at.work_type+'</td><td>'+at.pubkey+'</td><td>'+at.quality+'</td><td>'+at.reward+'</td><td>'+new Date(at.created_at*1000).toLocaleString()+'</td></tr>').join('') || '<tr><td colspan="5">No attestations yet</td></tr>';
}
loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


class ProofDashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the PROOF dashboard."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/dashboard':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
            return

        if parsed.path == '/api/stats':
            self._json_response(self._get_stats())
            return

        if parsed.path == '/api/leaderboard':
            self._json_response(self._get_leaderboard())
            return

        if parsed.path == '/api/bounties':
            self._json_response(self._get_bounties())
            return

        if parsed.path == '/api/attestations':
            self._json_response(self._get_attestations())
            return

        super().do_GET()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _get_stats(self):
        """Compute stats from relay database if available."""
        return {
            "total_attestations": "0",
            "verified_agents": "0",
            "total_rewards_distributed": "0 PROOF",
            "active_bounties": "0",
            "total_burned": "0 PROOF",
            "relay_url": "wss://proof.buzz",
            "token": "PROOF (1B supply, 9 decimals)",
            "launch": "pump.fun bonding curve",
        }

    def _get_leaderboard(self):
        return []

    def _get_bounties(self):
        return []

    def _get_attestations(self):
        return []


def run_dashboard(port: int = 8096):
    """Start the dashboard server."""
    server = HTTPServer(('0.0.0.0', port), ProofDashboardHandler)
    print(f"PROOF Dashboard running at http://0.0.0.0:{port}")
    print("Open in browser to view leaderboard, stats, and bounties.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='PROOF Dashboard')
    parser.add_argument('--port', type=int, default=8096)
    args = parser.parse_args()
    run_dashboard(args.port)
