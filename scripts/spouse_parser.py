"""Build separate, unreviewed person/marriage candidates from spouse scopes."""
import re


def parse_spouses(person):
    information = person['information']
    source_owner = information['owner_id']
    people, marriages, unresolved = [], [], []
    relative_context = False
    for scope in information['items']:
        if scope['kind'] != 'spouse_information':
            continue
        subject = scope['subject']
        marker = subject['marker_raw']
        # A concubine mentioned after a spouse's father/grandfather may belong
        # to that relative. Do not create an A-spouse edge from that mention.
        if relative_context and not marker.startswith('配'):
            unresolved.append({'reason':'relative_context', 'source':scope})
            continue
        relative = re.search(r'父|祖', scope['raw'])
        cutoff = scope['start'] + relative.start() if relative else scope['end']
        own, uncertain = [], []
        for item in scope['items']:
            if item['end'] <= cutoff:
                own.append(item)
            else:
                uncertain.append(dict(item, owner_id=None, reason='relative_context'))
        people.append({'id': subject['id'], 'designation_raw': subject['label'],
                       'personal_name': None, 'needs_review':True,
                       'information_items':own, 'unresolved_items':uncertain,
                       'source_owner_id':source_owner, 'source_refs':scope['source_refs']})
        marriages.append({'from':source_owner, 'to':subject['id'],
                          'relation_type':subject['relation_type'], 'wife_rank':None,
                          'marker_raw':marker, 'needs_review':True,
                          'source_refs':scope['source_refs']})
        relative_context = relative is not None
    return {'people':people, 'marriages':marriages, 'unresolved_scopes':unresolved}


def enrich_spouses(document):
    for person in document['candidates']:
        person['spouses'] = parse_spouses(person)
    document['spouse_parser_version'] = 1
    return document
