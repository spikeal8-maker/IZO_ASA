"""Install fail-closed stateful egress policy in this container's namespace only."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

READY = Path('/tmp/shadow-network-ready')
MARKER = 'STATEFUL_EGRESS_NONROOT'
RULES = '''table inet izo_shadow {
    chain output {
        type filter hook output priority filter; policy drop;
        oifname "lo" accept
        ct state established,related accept
        counter drop
    }
}
'''


def nft(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(['nft', *args], input=input_text, text=True,
                            capture_output=True, timeout=5, check=False)
    if result.returncode:
        raise RuntimeError('SHADOW_KERNEL_POLICY_COMMAND_FAILED')
    return result.stdout


def validate_policy(text: str) -> None:
    # Stateless output excludes changing counters. Require the exact canonical
    # table, hook, default deny and rule order, including no extra accept rules.
    if ' '.join(text.split()) != ' '.join(RULES.split()):
        raise RuntimeError('SHADOW_KERNEL_POLICY_MISMATCH')


def policy_state() -> dict:
    validate_policy(nft('-s', 'list', 'table', 'inet', 'izo_shadow'))
    data = json.loads(nft('-j', 'list', 'table', 'inet', 'izo_shadow'))
    counters = [expr['counter']['packets'] for item in data['nftables']
                for expr in item.get('rule', {}).get('expr', []) if 'counter' in expr]
    if len(counters) != 1:
        raise RuntimeError('SHADOW_KERNEL_POLICY_COUNTER_MISSING')
    return {'policy': 'VERIFIED', 'blockedPackets': counters[0]}


def check() -> dict:
    state = policy_state()
    status = Path('/proc/1/status').read_text()
    uid = next(row for row in status.splitlines() if row.startswith('Uid:')).split()[1:]
    if READY.read_text() != MARKER or any(value == '0' for value in uid):
        raise RuntimeError('SHADOW_GUARD_NOT_READY')
    if 'CapEff:\t0000000000000000' not in status:
        raise RuntimeError('SHADOW_GUARD_CAPABILITIES_REMAIN')
    if Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip() != '1':
        raise RuntimeError('SHADOW_IPV6_ENABLED')
    return state


def main() -> None:
    READY.unlink(missing_ok=True)
    # nft applies the entire batch atomically. Any install/readback failure exits
    # before readiness; neither dependent application can start.
    nft('-f', '-', input_text=RULES)
    policy_state()
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
    status = Path('/proc/self/status').read_text()
    if 'CapEff:\t0000000000000000' not in status or os.getuid() == 0:
        raise RuntimeError('SHADOW_PRIVILEGE_DROP_FAILED')
    # Only PID 1 reaps adopted exec/health descendants; --check retains normal waits.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    READY.write_text(MARKER)
    print('SHADOW_NETWORK_READY uid=10001 capabilities=0 statefulEgress=deny', flush=True)
    while True:
        time.sleep(60)


if __name__ == '__main__':
    if sys.argv[1:] == ['--check']:
        print(json.dumps(check()))
    else:
        main()
