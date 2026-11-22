"""Validated persistent display preferences, independent of terminal ownership."""
import re

from .managed_inventory import InventoryError

DEFAULT_POLICY = dict(enabled=True, show_model=False, show_provider=False,
                      recover_namespace=False, ascii=True, render_mode='full', style_rules=[], compact=False, show_stale=True, preset="legacy")
_DIMENSIONS = frozenset(('harness', 'build', 'profile', 'model', 'inference_provider',
                         'execution_host', 'activity'))
_COLOURS = frozenset(('black', 'red', 'green', 'yellow', 'blue', 'magenta',
                      'cyan', 'white', 'default'))


STYLE_ATTRIBUTES = ('bold', 'dim', 'underscore', 'reverse')


def validate_style_override(style):
    if not isinstance(style, dict) or set(style) != {'foreground', 'background', 'attributes'}:
        raise InventoryError('invalid_argument', 'Specify foreground, background, and attributes.')
    for field in ('foreground', 'background'):
        colour = style[field]
        if not isinstance(colour, str) or not (colour in _COLOURS or re.fullmatch(
                r'#[0-9a-fA-F]{6}|colour(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])', colour)):
            raise InventoryError('invalid_argument', 'Unsupported override colour.')
    attributes = style['attributes']
    if (not isinstance(attributes, list) or len(attributes) > len(STYLE_ATTRIBUTES)
            or any(not isinstance(value, str) or value not in STYLE_ATTRIBUTES for value in attributes)
            or len(set(attributes)) != len(attributes)):
        raise InventoryError('invalid_argument', 'Unsupported or repeated tab style attributes.')
    return dict(foreground=style['foreground'], background=style['background'],
                attributes=list(attributes))


def validate_policy(policy):
    """Return independent, finite preferences; reject terminal-format injection."""
    if not isinstance(policy, dict) or set(policy) - set(DEFAULT_POLICY):
        raise InventoryError('invalid_argument', 'Unknown display policy field.')
    from .tab_format_presets import PRESETS, PALETTES
    preset=policy.get('preset')
    if preset is not None and (not isinstance(preset,str) or preset not in PRESETS):
        raise InventoryError('invalid_argument', 'Unknown tab preset; choose slate, dusk, graphite or legacy.')
    result = dict(compact=True, show_stale=False, render_mode='full',
                  show_model=False,show_provider=False,style_rules=[]) if preset in PALETTES else {}
    for key, value in policy.items():
        if key in ('enabled', 'show_model', 'show_provider', 'ascii', 'compact', 'show_stale', 'recover_namespace'):
            if type(value) is not bool:
                raise InventoryError('invalid_argument', key + ' must be boolean.')
        elif key == 'preset':
            pass
        elif key == 'render_mode':
            if value not in ('full', 'basic', 'plain'):
                raise InventoryError('invalid_argument', 'render_mode must be full, basic or plain.')
        else:
            if not isinstance(value, list) or len(value) > 32:
                raise InventoryError('invalid_argument', 'style_rules must be a list of at most 32 rules.')
            rules = []
            for rule in value:
                if not isinstance(rule, dict) or set(rule) != {'match', 'colour'}:
                    raise InventoryError('invalid_argument', 'A style rule requires match and colour.')
                match, colour = rule['match'], rule['colour']
                if not isinstance(match, dict) or not match or set(match) - _DIMENSIONS or any(
                    not isinstance(item, str) or not 1 <= len(item) <= 128
                    or any(ord(char) < 32 or ord(char) == 127 for char in item) for item in match.values()
                ):
                    raise InventoryError('invalid_argument', 'Style rules match bounded exact dimension names.')
                if not isinstance(colour, str) or not (colour in _COLOURS or
                    re.fullmatch(r'colour(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])', colour)):
                    raise InventoryError('invalid_argument', 'Unsupported style colour.')
                rules.append(dict(match=dict(match), colour=colour))
            value = rules
        result[key] = value
    return result


def effective_policy(state, workspace):
    """Workspace overrides cannot bypass a global opt-out."""
    global_policy = dict(DEFAULT_POLICY, **state.get('policy', {}))
    result = dict(global_policy, **state.get('workspace_policies', {}).get(workspace, {}))
    result['enabled'] = global_policy['enabled'] and result['enabled']
    return result
