"""Propose same-page parent edges from adjacent genealogy bands."""


def extract_parent_candidates(document):
    people = document['candidates']
    relations, unresolved = [], []
    for child_index, child in enumerate(people):
        if child['band'] <= 1:
            unresolved.append({'child':child_index, 'reason':'upper_band_outside_page'})
            continue
        cx = (child['name_bbox'][0] + child['name_bbox'][2]) / 2
        above = [(i, p) for i,p in enumerate(people) if p['band'] == child['band']-1]
        aligned = [(i,p) for i,p in above if p['name_bbox'][0] <= cx <= p['name_bbox'][2]]
        right = [(i,p) for i,p in above if (p['name_bbox'][0]+p['name_bbox'][2])/2 > cx]
        if aligned:
            parent_index, parent = min(aligned, key=lambda pair: abs((pair[1]['name_bbox'][0]+pair[1]['name_bbox'][2])/2-cx))
            method = 'same_column'
        elif right:
            parent_index, parent = min(right, key=lambda pair: (pair[1]['name_bbox'][0]+pair[1]['name_bbox'][2])/2)
            method = 'first_to_right'
        else:
            unresolved.append({'child':child_index, 'reason':'no_parent_to_right_on_page'})
            continue
        relations.append({'parent':parent_index, 'child':child_index, 'method':method,
                          'needs_review':True,
                          'warnings':['missing_or_false_ocr_names_can_change_parent', 'page_boundary_not_checked'] +
                              (['female_marker_requires_review'] if child.get('marker') in ('女','女') or parent.get('marker') in ('女','女') else []),
                          'evidence':{'parent_bbox':parent['name_bbox'], 'child_bbox':child['name_bbox'],
                                      'parent_band':parent['band'], 'child_band':child['band']}})
    document['parent_candidates'] = {'relations':relations, 'unresolved':unresolved}
    return document
