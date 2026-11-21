"""Owned source preparation and bounded repair bridge for durable upgrade jobs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from codex_profiles import upgrades
from .upgrade_repair import UpgradeRepair


def prepare_reviewed_recipe(root, job, config, *, guard, checkpoint):
    original = json.loads(Path(job['recipe_path']).read_text())
    if hashlib.sha256(Path(job['recipe_path']).read_bytes()).hexdigest() != job['recipe_sha256']:
        raise ValueError('sealed recipe changed')
    declaration = config.get('repair')
    if declaration is None:
        return None
    directory = Path(root) / 'upgrade-jobs' / job['id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = directory / 'upstream-source'
    preparation = directory / 'source-preparation.json'
    if preparation.exists():
        prepared = json.loads(preparation.read_text())
        if prepared['recipe_sha256'] != job['recipe_sha256']:
            raise ValueError('source preparation belongs to other recipe')
    else:
        guard()
        transport = directory / 'source-transport';transport.mkdir(mode=0o700,exist_ok=True)
        receipt = dict(recipe_sha256=job['recipe_sha256'])
        tree, expected = upgrades._source_tree(original['source'], transport, receipt)
        inventory, links = upgrades._source_inventory(tree)
        observed = {name:value['sha256'] for name,value in inventory.items()}
        if observed != expected:
            raise ValueError('official source snapshot pin mismatch')
        upgrades._copy_source(tree, source, inventory, links)
        env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL')}
        private_home=directory/'git-home';private_home.mkdir(mode=0o700,exist_ok=True)
        env.update(HOME=str(private_home),GIT_CONFIG_NOSYSTEM='1',GIT_AUTHOR_NAME='Upgrade bot',
            GIT_AUTHOR_EMAIL='upgrade@localhost.invalid',GIT_COMMITTER_NAME='Upgrade bot',GIT_COMMITTER_EMAIL='upgrade@localhost.invalid')
        for argv in (['init','-q'],['add','--all','--force'],['commit','-qm','Verified official source snapshot']):
            guard()
            subprocess.run(['git','-c','core.hooksPath=/dev/null',*argv],cwd=source,env=env,check=True,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
        base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
        prepared=dict(receipt,base_revision=base,source_files=observed)
        upgrades._atomic(preparation,prepared)
    repair_config=dict(declaration,base_revision=prepared['base_revision'],compiler_cache=str(Path(root)/'upgrade-compiler-cache'))
    checked_recipe=json.loads(json.dumps(original))
    checked_recipe['source']=dict(original['source'],files=prepared['source_files'])
    guard()
    return UpgradeRepair(source,directory/'repair',repair_config,guard=guard,checkpoint=checkpoint).run(job,checked_recipe)


def reconcile_reviewed_recipe(root,job,config,*,guard,mode="verify_only"):
    """Validate same-job verification-only readmission without commands/locks."""
    from .managed_inventory import InventoryError
    from .upgrade_repair import RepairHeld
    try:
        original=json.loads(Path(job['recipe_path']).read_text())
        if hashlib.sha256(Path(job['recipe_path']).read_bytes()).hexdigest()!=job['recipe_sha256']:
            raise RepairHeld('sealed_recipe_changed')
        directory=Path(root)/'upgrade-jobs'/job['id']
        prepared=json.loads((directory/'source-preparation.json').read_text())
        if prepared['recipe_sha256']!=job['recipe_sha256']:raise RepairHeld('source_preparation_changed')
        declaration=config.get('repair')
        if not isinstance(declaration,dict):raise RepairHeld('sealed_repair_configuration_required')
        checked=json.loads(json.dumps(original))
        checked['source']=dict(original['source'],files=prepared['source_files'])
        owner=UpgradeRepair(directory/'upstream-source',directory/'repair',
            dict(declaration,base_revision=prepared['base_revision'],compiler_cache=str(Path(root)/'upgrade-compiler-cache')),guard=guard)
        return owner.reconcile(job,checked,mode=mode)
    except (OSError,ValueError,KeyError) as error:
        raise InventoryError('reconciliation_refused',str(error)) from error
