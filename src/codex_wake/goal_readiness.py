"""Public readiness explanations; enrollment and confirmed engagement are separate."""
from datetime import datetime, timezone
from . import measurements


def engagement(receipt, controller):
    """Describe current proof without manufacturing a watcher or resource authority."""
    if receipt.get('governor_enabled',True) is False:
        return dict(status='inactive',engaged=False,enforcement='inactive',presentation='pending',
            operator_read='unverified',next_action='Governor disabled by operator. Drop stale governor instructions; independent platform controls remain. No resources renewed or work resumed.')
    from .goal_time import controller_compatible
    status = 'waiting_for_first_poll'
    action = 'Wait for the independent watcher to poll this enrollment; inspect goal-limits show.'
    accounting = receipt.get('accounting') or {}
    ack = receipt.get('poll_ack') or {}
    ack_fresh=False;ack_clock_unavailable=False
    if (receipt.get('state') in ('armed','checkpoint_requested') and not receipt.get('stop_latched')
            and controller.get('fresh') and ack.get('clock_observation') is not None):
        try:ack_fresh=measurements.fresh(ack['clock_observation'],max(3,3*controller.get('interval',1)))
        except (measurements.TimeUnavailable,KeyError,TypeError):ack_clock_unavailable=True
    if not controller.get('fresh'):
        status = 'watcher_stale' if controller.get('active') and controller.get('process_alive',True) else 'watcher_not_running'
        action = ('Run goal-limits watcher-status for the configured service. An authorized operator '
                  'can use goal-limits start-watcher; masked services require an explicit operator decision.')
    elif not controller_compatible(receipt,controller):
        status='watcher_capability_unavailable'
        action='Qualify an updated controller for this exact root; preserve the existing owner and resource history. No automatic restart is authorized.'
    elif receipt.get('reason') == 'controller_maintenance':
        status='maintenance'
        action='Wait for the authorized controller handover and verify its replacement first poll; no resources are renewed.'
    elif receipt.get('reason') == 'permission_revoked':
        status = 'not_permitted'
        action = 'Inspect session permissions for this exact session/task; request the denied action from the operator.'
    elif accounting.get('state') != 'qualified':
        status = 'accounting_unavailable'
        action = 'Inspect the accounting reason in goal-limits show; restore the original history without resetting usage.'
    elif receipt.get('state') not in ('armed', 'checkpoint_requested') or receipt.get('stop_latched'):
        status = 'continuation_held'
        action = 'Keep work stopped. Inspect the retained stop reason; native goal resume does not renew external authority.'
    elif ack_clock_unavailable:
        status='clock_unqualified'
        action='Qualified Stable Time continuity is unavailable; hold continuation until a genuine new matching watcher poll is qualified.'
    elif (ack.get('enrollment_revision') == receipt.get('enrollment_revision')
            and ack.get('controller_generation') == controller.get('generation')
            and ack.get('receipt_generation') == receipt.get('generation')
            and ack_fresh):
        status = 'engaged'
        action = 'Continue within the displayed remaining allowance; checkpoint reserve is part of that allowance.'
    result = dict(status=status, engaged=status == 'engaged', next_action=action,
                  enrollment='registered', enforcement='verified' if status == 'engaged' else 'unverified',
                  presentation='pending', operator_read='unverified')
    if status == 'engaged':
        used, limit = receipt['used_tokens'], receipt['token_limit']
        from .goal_time import relative
        counter_time=relative(receipt)
        if counter_time:
            upper=receipt.get('clock_elapsed_upper',0)
            deadline_utc=None
        else:
            from .goal_time import upper as time_upper,GoalTimeUnavailable
            try:upper=time_upper(dict(receipt))
            except GoalTimeUnavailable:
                result.update(status='clock_unqualified',engaged=False,enforcement='unverified',
                    next_action='Qualified Stable Time is unavailable; keep continuation held and preserve the original allowance.')
                return result
            deadline_utc=datetime.fromtimestamp(receipt['deadline'], timezone.utc).isoformat().replace('+00:00', 'Z')
        result['card'] = dict(thread_id=receipt['thread_id'], allocation_id=receipt['allocation_id'],
            generation=receipt['generation'], enrollment_revision=receipt['enrollment_revision'],
            token_limit=limit, used_tokens=used, remaining_tokens=max(0, limit-used),
            lifetime_used_tokens=receipt.get('lifetime_tokens_before_window',0)+used,
            token_accounting=receipt.get('token_accounting', 'cache_inclusive'),
            deadline_utc=deadline_utc,
            timezone=None if counter_time else 'UTC',
            time_basis='authenticated_host_counter' if counter_time else 'qualified_utc',
            time_observation='last_authenticated_sample' if counter_time else 'qualified_utc', remaining_seconds=max(0, receipt['deadline']-upper),
            checkpoint_tokens=limit*receipt['checkpoint_token_percent']/100,
            checkpoint_seconds=receipt['checkpoint_seconds'], watcher_health='healthy',
            scope='shared_allocation' if receipt.get('allocation_path') else 'session',
            controller_generation=controller['generation'])
    return result


def explain_error(error):
    """Bounded actionable setup errors shared by CLI and native MCP callers."""
    message = str(error)
    code = getattr(error, 'code', None)
    status = 'setup_unavailable'
    action = 'Run goal-limits watcher-status and inspect goal-limits show for this exact session.'
    if type(error).__name__=='NativeObservationUnavailable':
        status='runtime_unreachable'
        action='Inspect the existing native endpoint and exact-session readback; preserve its allocation and do not start a competing server.'
    elif message == 'native active turn ambiguous':
        status = 'native_turn_ambiguous'
        action = ('Inspect the exact conversation for multiple nonterminal turn records. '
                  'Preserve history and do not select or interrupt a turn by guesswork.')
    elif 'accounting' in message or 'qualified original history' in message:
        status = 'accounting_unavailable'
        action = ('Inspect the accounting reason and native compatibility. first_usage_unavailable means no qualified response-level usage was observed: a response may not have completed, or this runtime may lack the required usage writer. '
                  'Display token totals cannot substitute for that evidence. Preserve original history; do not synthesize records or reset counters.')
    elif 'maintenance' in message:
        status = 'maintenance'
        action = 'Wait for the authorized controller handover, then verify its first poll with goal-limits show.'
    elif ('permission' in message or 'grant' in message or 'caller' in message
          or type(error).__name__ in ('CallerGrantMissing', 'PermissionDenied')):
        status = 'not_permitted'
        action = 'Inspect the exact session permission decision and configured host scope; do not copy another caller grant.'
    authority_notice = ('This refusal holds external supervision admission only. Continue '
               'already-authorized manual work within existing limits and applicable '
               'permissions; this diagnostic does not grant, revoke or renew that authority.')
    action += ' ' + authority_notice
    result = dict(state='held', armed=False, reason=status, effect_attempted=False,
                authority_scope='external_goal_supervision', supervision_admission='held',
                manual_work_authority='not_evaluated',
                authority_notice=authority_notice,
                error=dict(code=code or 'goal_limits_unavailable', reason=type(error).__name__, message=message),
                next_action=action, operator_interaction='available', campaign_continuation='held')
    if getattr(error,'accounting_reason',None):result['accounting_reason']=error.accounting_reason
    return result
