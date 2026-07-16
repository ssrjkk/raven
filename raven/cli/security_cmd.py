from __future__ import annotations

import click


@click.group(name="security")
def security_group():
    """Security audit and policy management"""


@security_group.command("audit")
@click.option("--deep", is_flag=True, help="Run deep audit (network, env file, dependencies)")
@click.option("--fix", is_flag=True, help="Auto-fix common issues")
def security_audit(deep: bool, fix: bool):
    """Run comprehensive security audit checks"""
    from raven.cli.doctor import _render_security_audit
    from raven.core.security.security_audit import SecurityAudit

    auditor = SecurityAudit()
    results = auditor.run_all(deep=deep)
    _render_security_audit(results, fix=fix)
