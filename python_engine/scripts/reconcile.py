# python_engine/scripts/reconcile.py
"""Simple reconciliation script: fetch positions from gateway and print differences vs local snapshot (if any).
This is a dry-run utility; does not modify exchange state.
"""
import argparse
from python_engine.engine import MockGateway


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gateway', choices=['mock'], default='mock')
    args = parser.parse_args()

    if args.gateway == 'mock':
        gw = MockGateway(account_equity=1000.0)
    else:
        raise SystemExit('unsupported')

    exch_positions = gw.fetch_positions()
    print('exchange_positions:', exch_positions)
    # Local snapshot: for now empty; extend to read from DB
    local_positions = {}
    print('local_positions:', local_positions)
    # compare
    if exch_positions != local_positions:
        print('reconcile: differences found')
    else:
        print('reconcile: ok')

if __name__ == '__main__':
    main()
