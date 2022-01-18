import json
import re
from pprint import pprint


CHANGE_LOG_PATH = '/Users/decoupca/Downloads/recovered-items.sql'

with open(CHANGE_LOG_PATH) as fh:
    items = fh.read().splitlines()


def cleanup_value(value):
    if value == '\\N':
        return None
    elif re.match(r'^\d+$', value):
        return int(value)
    else:
        return value


def parse_change_json(data):
    if '{' in data:
        return json.loads(data)
    else:
        return {}


def parse_change_record(record):
    change_id, change_time, user_name, request_id, action, changed_object_id, related_object_id, object_repr, postchange_data, changed_object_type_id, related_object_type_id, user_id, prechange_data = item.split('\t')
    return {
        'change_id': cleanup_value(change_id),
        'change_time': cleanup_value(change_time),
        'user_name': cleanup_value(user_name),
        'request_id': cleanup_value(request_id),
        'action': cleanup_value(action),
        'changed_object_id': cleanup_value(changed_object_id),
        'related_object_id': cleanup_value(related_object_id),
        'object_repr': cleanup_value(object_repr),
        'postchange_data': parse_change_json(postchange_data),
        'changed_object_type_id': cleanup_value(changed_object_type_id),
        'related_object_type_id': cleanup_value(related_object_type_id),
        'user_id': cleanup_value(user_id),
        'prechange_data': parse_change_json(prechange_data),
    }

for item in items:
    try:
        data = parse_change_record(item)
    except:
        import ipdb; ipdb.set_trace()

    pprint(data)
    break
    if action == 'create':
        pass
    elif action == 'update':
        pass
    elif action == 'delete':
        pass

