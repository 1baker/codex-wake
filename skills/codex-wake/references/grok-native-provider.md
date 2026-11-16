# Native Grok provider status

Grok inference and workers inside Codex are specified in [P233 / issue 628](https://github.com/CochranResearchGroup/codex-wake/issues/628). Implementation and integrated qualification remain pending; this routing does not establish provider readiness. Preserve current OpenAI defaults.

The separate Grok CLI-worker setup from issue 621 / draft PR 622 is superseded. Do not route this native-provider request through a separate Grok CLI, restart its retired owner, authenticate that old setup, or clear the independent browser Grok hold.
