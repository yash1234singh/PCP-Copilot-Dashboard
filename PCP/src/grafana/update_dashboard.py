import json

with open('provisioning/dashboards/json/pcp-auto-dashboard.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def update_query(query):
    if isinstance(query, str):
        # Replace product_type filter
        query = query.replace(
            '|> filter(fn: (r) => r["product_type"] == "${product_type}")',
            '|> filter(fn: (r) => "${product_type}" == "ANY" or r["product_type"] == "${product_type}")'
        )
        # Replace serialNumber filter
        query = query.replace(
            '|> filter(fn: (r) => r["serialNumber"] == "${serialNumber}")',
            '|> filter(fn: (r) => "${serialNumber}" == "ANY" or r["serialNumber"] == "${serialNumber}")'
        )
    return query

def process_panels(panels):
    for panel in panels:
        if 'targets' in panel:
            for target in panel['targets']:
                if 'query' in target:
                    target['query'] = update_query(target['query'])
        if 'panels' in panel:
            process_panels(panel['panels'])

process_panels(data['panels'])

with open('provisioning/dashboards/json/pcp-auto-dashboard.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print('Updated successfully')
