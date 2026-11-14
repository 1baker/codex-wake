"""Declared function output types, shared by pure and native function owners."""
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from .managed_inventory import InventoryError


TYPES=('boolean','string','integer','number','object','array','null')


def output_schema(function):
    schema=function.get('output','boolean')
    if isinstance(schema,str):schema={'type':schema}
    if not isinstance(schema,dict):raise InventoryError('invalid_function_output','typed output declaration required')
    def references(value):
        if isinstance(value,dict):return any(key in ('$ref','$dynamicRef') or references(item) for key,item in value.items())
        return isinstance(value,list) and any(references(item) for item in value)
    if schema.get('type') not in TYPES or references(schema):
        raise InventoryError('invalid_function_output','bounded local JSON output schema with one supported type required')
    try:Draft202012Validator.check_schema(schema)
    except SchemaError:raise InventoryError('invalid_function_output','valid local output schema required') from None
    return schema


def typed_outcome(outcome,schema):
    status=outcome.get('status')
    if status not in ('known','unknown','error','timeout'):
        return dict(outcome,type=schema['type'],status='error',value=None,reason='function_result_status')
    if status=='known' and not Draft202012Validator(schema).is_valid(outcome.get('value')):
        return dict(outcome,type=schema['type'],status='error',value=None,
            reason='semantic_boolean_type' if schema['type']=='boolean' else 'function_output_type')
    return dict(outcome,type=schema['type'])
