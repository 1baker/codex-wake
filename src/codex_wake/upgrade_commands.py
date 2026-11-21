"""CLI/API/MCP contract for host-approved durable upgrade jobs."""
import json


def tool_specs():
    text = dict(type='string', minLength=1, maxLength=200)
    specs = {}
    for verb in ('status','list','show','enable','disable','start','advance','cancel','poll','discovery','rollback','reconcile','cache_cleanup'):
        properties = {'expected_target': {'type':'object', 'minProperties':1}}
        if verb in ('show','advance','cancel','rollback','reconcile'):properties['job_id']=text
        if verb=='reconcile':properties['mode']={'type':'string','enum':['verify_only','verify_review_only','qualification_only','promotion_observe']}
        if verb=='rollback':properties['operation_id']=text
        if verb=='start':
            properties.update(recipe=text,expected_recipe_sha256=text,upstream_version=text)
        specs['wake_upgrades_'+verb]=('controller-upgrades','upgrades.'+verb,
            'Inspect or drive bounded opt-in upgrades within a host-approved scope; no daemon replacement or grant renewal.',
            properties,[k for k in properties if k not in ('expected_recipe_sha256','upstream_version')],verb in ('status','list','show','discovery'))
    return specs


def protected_execute(operation, arguments, root):
    from .flow_commands import protected_execute as shared
    return shared(operation, arguments, root)


def register_parser(subparsers):
    parser=subparsers.add_parser('upgrades',help='inspect and control bounded autonomous build upgrades')
    verbs=parser.add_subparsers(dest='upgrade_verb',required=True)
    for spec in tool_specs().values():
        verbs.add_parser(spec[1].split('.')[1]).add_argument('--arguments',type=json.loads,required=spec[1]!='upgrades.disable')


def command(args,root):
    if args.upgrade_verb=='disable' and args.arguments is None:
        from .upgrade_jobs import UpgradeJobs
        result=UpgradeJobs(root).disable_local()
    else:
        result=protected_execute('upgrades.'+args.upgrade_verb,args.arguments,root)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='completed' else 2
