"""Stable commands; modules are loaded after installation paths are configured."""
import argparse
import runpy
import sys

COMMANDS = {
    ('agent','run'): 'agent.cli_worker',
    ('history','watch'): 'agent.history_watch',
    ('history','sync'): 'agent.history_client',
    ('devices',): 'devices.e2ee_admin',
    ('service','install'): 'ops.install_cli_service',
    ('deploy',): 'ops.release_vm',
    ('provision',): 'ops.deploy_vm',
    ('client',): 'agent.web_client',
}


def main():
    args=sys.argv[1:]
    for prefix,module in COMMANDS.items():
        if tuple(args[:len(prefix)])==prefix:
            rest=args[len(prefix):]
            if prefix==('history','sync'):rest=['sync',*rest]
            sys.argv=['codex-workspace '+' '.join(prefix),*rest]
            runpy.run_module('codex_workspace.'+module,run_name='__main__')
            return 0
    parser=argparse.ArgumentParser(description=__doc__,epilog='Commands: '+', '.join(' '.join(p) for p in COMMANDS))
    parser.parse_args(args)
    parser.print_help()
    return 0
