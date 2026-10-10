"""Lazy compatibility entry for the script-owned live workflow harness."""

from importlib import import_module

__all__ = ['LIVE_COMBINATIONS', 'MAX_LIVE_CALLS', 'MAX_LIVE_TOKENS', 'MAX_LIVE_DURATION_SECONDS', 'LiveWorkflowBudget', 'DEFAULT_LIVE_WORKFLOW_BUDGET', 'live_workflow_budget_from_config', 'LiveWorkflowBudgetExceeded', 'acceptance_report_status', 'redact_workflow_record', 'run_bounded_live_workflow']


def __getattr__(name: str):
    return getattr(import_module("scripts.courseware_harness.live"), name)
