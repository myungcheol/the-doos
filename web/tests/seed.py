"""Synthetic web fixtures. Requires an explicitly isolated *_test database."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from database.store import PostgresStore
from review.data_model import person_local_key

url = os.environ['JOKBO_TEST_DATABASE_URL']
root = Path(os.environ.get('JOKBO_WEB_TEST_ROOT', '/tmp/jokbo-web-fixture'))
root.mkdir(parents=True, exist_ok=True)
store = PostgresStore(url, root / 'assets')
with store.connection() as conn:
    name = conn.execute('SELECT current_database()').fetchone()[0]
    if not name.endswith('_test'):
        raise RuntimeError('Fixture database name must end in _test')
store.initialize()
eid = 'web-test'
edition = {'edition_id': eid, 'publication_year': 1987}
state = {'edition': edition, 'person_uid_map': {}, 'people_updates': {}}
font_path = next(iter((Path(__file__).resolve().parents[2] / 'assets/fonts').glob('*.otf')), None)
if not font_path:
    font_path = next(iter((Path(__file__).resolve().parents[2] / 'assets/fonts').glob('*.ttf')), None)
font = ImageFont.truetype(str(font_path), 34) if font_path else ImageFont.load_default()
names = ['測試甲', '測試乙', '測試丙', '測試丁', '測試戊', '拒絕者', '待審者']
pages = []
for index, ids in enumerate(([1, 2, 3, 6, 7], [4, 5]), 1):
    name = f'{index:03}.png'
    image = Image.new('RGB', (900, 1100), '#e6d6ad')
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 50, 845, 1050), outline='#65583e', width=3)
    draw.text((350, 65), '測試族譜', font=font, fill='#55472f')
    draw.line((55, 150, 845, 150), fill='#65583e', width=2)
    candidates = []
    for position, i in enumerate(ids):
        x = 750 - position * 140
        bbox = {'x': x, 'y': 190, 'width': 48, 'height': 170}
        draw.line((x-40, 150, x-40, 1050), fill='#9d8a5e', width=1)
        for n, char in enumerate('子' + names[i-1]):
            draw.text((x, 190+n*40), char, font=font, fill='#30291d')
        for n, char in enumerate('生平事跡原本記錄'):
            draw.text((x-35, 450+n*38), char, font=font, fill='#5e5138')
        p = {'person_id':f'p{i}', 'source_page':name, 'raw_name_ocr':'子'+names[i-1],
             'name_hanja_candidate':'子'+names[i-1], 'bbox':bbox,
             'source_row_id':'row1', 'source_column_id':f'col{i}', 'review_status':'needs_review'}
        candidates.append(p)
        state['person_uid_map'][person_local_key(p, eid)] = f'PER_{i:032X}'
        state['people_updates'][p['person_id']] = {'transcribed_name_hanja':names[i-1],
            'review_status':'rejected' if i==6 else 'needs_review' if i==7 else 'confirmed',
            'information_review_status':'confirmed', 'birth_text':'甲子年生', 'office_title':'司直',
            'notes':'PRIVATE_NOTE_FOR_TEST', 'generation_number': i,
            'spouses': [{'type':'wife','name_and_record':'測試配偶','review_status':'needs_review'}] if i==1 else []}
    image.save(root / name)
    pages.append({'schema_version':1, 'source_image':str(root / name), 'source_page':name,
                  'image_size':{'width':900,'height':1100}, 'rows':[],
                  'people_candidates':candidates, 'relationship_candidates':[]})
for n, (parent, child, status) in enumerate([(1,2,'confirmed'),(1,3,'confirmed'),(2,4,'confirmed'),
                                           (3,4,'confirmed'),(4,5,'confirmed'),(1,6,'rejected'),(1,7,'needs_review')]):
    pages[0]['relationship_candidates'].append({'relationship_id':f'R{n}', 'parent_candidate_id':f'p{parent}',
                                                'child_candidate_id':f'p{child}', 'review_status':status})
# ROI-only page: source coordinates remain offset from the image shown in the browser.
folder = root / '003'
folder.mkdir(exist_ok=True)
cv2.imwrite(str(folder / 'table_roi.jpg'), np.full((100,200,3),220,np.uint8))
p = {'person_id':'roi-person','source_page':'003.png','raw_name_ocr':'子偏移',
     'name_hanja_candidate':'子偏移','bbox':{'x':120,'y':230,'width':30,'height':40},
     'review_status':'needs_review'}
pages.append({'schema_version':1,'source_image':str(root/'003.png'),'source_page':'003.png',
              'page_output_dir':str(folder),'table_roi':{'x':100,'y':200},'rows':[],
              'people_candidates':[p],'relationship_candidates':[]})
store.import_pages(pages, edition, root, state)
private = {**pages[0], 'people_candidates':[], 'relationship_candidates':[]}
store.import_pages([private], {'edition_id':'hidden-test','publication_year':1987}, root)
print('Synthetic fixture ready: web-test (3 pages), hidden-test (1 page)')
