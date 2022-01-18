import json
import re
from pprint import pprint
from netdev.netbox import nb

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


def diff_change(record):
    print(record['object_repr'])
    for key, prechange_value in record['prechange_data'].items():
        if key == 'last_updated':
            continue
        postchange_value = record['postchange_data'][key]
        if prechange_value != postchange_value:
            print(f"{key}: changed from {prechange_value} to {postchange_value}")
    print('-'*80)


def get_endpoint(record):
    """Discerns an API endpoint from record data"""
    data = record.get('prechange_data') or record.get('postchange_data')
    if data.get('cid'):
        return 'circuits.circuit'
    elif data.get('airflow'):
        return 'dcim.device'
    elif data.get('termination_a_id'):
        return 'dcim.cable'
    elif data.get('wireless_link'):
        return 'dcim.interface'
    else:
        msg = f"Can't determine API endpoint for record {record['object_repr']}\n{pprint(record)}"
        raise ValueError(msg)

def get_api_call(record):
    endpoint = get_endpoint(record)
    print(endpoint)

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

    #get_endpoint(data)
    if data['action'] == 'create':
        pass
    elif data['action'] == 'update':
        #diff_change(data)
        pass
    elif data['action'] == 'delete':
        pass

    if data['user_name'] != 'ordialer':
        diff_change(data)
