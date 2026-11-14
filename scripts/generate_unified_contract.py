"""Generate portable connector metadata from the canonical control contract."""
import argparse
import json
from pathlib import Path
import pprint
from codex_wake.controller_http import TOOLS
from codex_wake.unified_contract import canonical,metadata,tool_name

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    tools={}
    for name,(operation,schema) in TOOLS.items():
        tools.setdefault(operation,name)
        tools[canonical(operation)]=tool_name(canonical(operation))
    contract=metadata()
    generated='"""Generated portable names; no host execution-owner imports.\n\nRegenerate with scripts/generate_unified_contract.py.\n"""\nPUBLIC_MCP_TOOLS = '+pprint.pformat(tools,width=110,sort_dicts=True)+'\n'
    outputs={root/'src/codex_wake/unified_public.py':generated,
             root/'docs/agents/unified-control-contract.json':json.dumps(contract,sort_keys=True,indent=2)+'\n'}
    stale=[]
    for path,text in outputs.items():
        if path.exists() and path.read_text()==text:continue
        if args.check:stale.append(str(path.relative_to(root)))
        else:path.write_text(text)
    if stale:parser.exit(1,'Stale unified contract: '+', '.join(stale)+'\n')
    return 0
if __name__=='__main__':raise SystemExit(main())
