from datetime import datetime,date,time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock,patch
import pytest
from PIL import Image
from attendance import TZ,build_report,select_rows,report_tables
from enrollment import save_registration
from hikvision import ApiResult,HikvisionError
from roster import load_roster,pending_employees,resolve_users
from security import hash_password,verify_password
from report_tables import export_docx,export_pdf,export_xlsx
R=load_roster();DAY=date(2026,11,9);NOW=datetime(2026,11,10,18,tzinfo=TZ)
def users():
    return [dict(employeeNo=e['terminal_id'],name=e['terminal_alias'] or e['name'],numOfFace=1,numOfFP=1) for e in R if e['terminal_id']]
def event(n,t,minor=75):
    return dict(employeeNoString=n,time=f'2026-11-09T{t}+03:00',major=5,minor=minor)
def jpeg():
    s=BytesIO();Image.new('RGB',(120,150),'green').save(s,'JPEG');return s.getvalue()
def test_roster_and_exclusions():
    assert len(R)==len({e['key'] for e in R})==163
    assert len({e['department'] for e in R})==42
    assert sum(e['already_registered'] for e in R)==15
    assert len(pending_employees(R))==148
    assert len(pending_employees(R,users()))==6
    assert all(set(e)=={'key','name','employee_number','terminal_id','department','department_path','already_registered','terminal_alias'} for e in R)
def test_leading_zeros_and_identity_matching():
    mapping,issues=resolve_users(R,users());assert not issues
    h=next(e for e in R if 'Hamza Mustafa' in e['name']);y=next(e for e in R if 'Koleleni' in e['name'])
    assert mapping[h['key']]=='037' and mapping[y['key']]=='37'
    rows,_=build_report(R,users(),[event('37','07:55:00'),event('037','08:15:00')],DAY,DAY,now=NOW)
    assert next(r for r in rows if r['Employee Name']==h['name'])['Minutes late']==15
    assert next(r for r in rows if r['Employee Name']==y['name'])['Check in']=='07:55:00'
    mapping,issues=resolve_users(R,[dict(employeeNo='215',name='Someone Else')]);assert not mapping and issues
def test_attendance_boundaries():
    e=R[0];n=e['terminal_id'];u=[dict(employeeNo=n,name=e['name'])]
    events=[event(n,'07:59:00'),event(n,'08:01:00'),event(n,'16:29:59'),event(n,'16:30:00'),event(n,'16:45:00'),event(n,'00:01:00',76)]
    rows,_=build_report([e],u,events,DAY,DAY,now=NOW)
    assert rows[0]['Check in']=='07:59:00' and rows[0]['Check out']=='16:30:00'
    assert rows[0]['Status']=='Present'
    assert len(select_rows(rows,'Early attendance'))==len(select_rows(rows,'Checked in only'))==1
    assert not select_rows(rows,'Absentees')
    single,_=build_report([e],u,[event(n,'08:00:00')],DAY,DAY,now=NOW)
    assert not single[0]['Check out'] and not select_rows(single,'Early attendance')
    absent,_=build_report([e],u,[],DAY,DAY,now=NOW);assert absent[0]['Status']=='Absent'
    assert len(select_rows(absent,'Absentees'))==1
    unmatched,_=build_report([e],[],[],DAY,DAY,now=NOW)
    assert unmatched[0]['Status']=='Not enrolled / unmatched' and not select_rows(unmatched,'Absentees')
    current,_=build_report([e],u,[],NOW.date(),NOW.date(),now=NOW);assert current[0]['Status']=='Absent (provisional)'
    with pytest.raises(ValueError):build_report([e],u,[],DAY,date(2026,12,1),now=NOW)
    utc=dict(employeeNoString=n,major=5,minor=38,time='2026-11-09T05:00:00Z')
    rows,_=build_report([e],u,[utc],DAY,DAY,now=NOW);assert rows[0]['Check in']=='08:00:00'
def test_registration_guards():
    c=MagicMock();e=next(e for e in R if not e['already_registered'])
    c.search_users.return_value=[dict(employeeNo='123',name='Different Person')]
    with pytest.raises(HikvisionError,match='another name'):save_registration(c,e,'123',jpeg(),'test-template')
    c.upload_face.assert_not_called();c.create_user.assert_not_called()
    with pytest.raises(HikvisionError,match='already registered'):save_registration(c,next(e for e in R if e['already_registered']),'215',jpeg(),'test-template')
    with pytest.raises(HikvisionError,match='photograph and capture'):save_registration(c,e,'123',jpeg(),'')
def test_registration_requires_verified_readback():
    c=MagicMock();e=next(e for e in R if not e['already_registered'])
    c.search_users.return_value=[];c.get_user.return_value=dict(employeeNo='123',name=e['name'])
    c.upload_face.return_value=c.apply_fingerprint.return_value=ApiResult(True,200,{'statusCode':1})
    with patch('enrollment.read_face',return_value=jpeg()),patch('enrollment.read_fingerprints',return_value=[]):
        with pytest.raises(HikvisionError,match='read-back'):save_registration(c,e,'123',jpeg(),'test-template')
    with patch('enrollment.read_face',return_value=jpeg()),patch('enrollment.read_fingerprints',return_value=[dict(fingerPrintID=1,fingerData='test-template')]):
        save_registration(c,e,'123',jpeg(),'test-template')
def test_exports_and_text_safety():
    from openpyxl import load_workbook
    from docx import Document
    rows,_=build_report(R[:1],[],[],DAY,DAY,now=NOW);rows[0]['Employee Name']='=HYPERLINK("unsafe")'
    args=('Muslim University of Morogoro','Test attendance',report_tables(rows,True),'assets/mum_logo.png')
    w=load_workbook(BytesIO(export_xlsx(*args)));cells=[c for row in w.active for c in row]
    assert any(c.value==rows[0]['Employee Name'] and c.data_type=='s' for c in cells)
    assert any(c.fill.fgColor.rgb=='00006B3F' for c in cells)
    d=Document(BytesIO(export_docx(*args)));assert len(d.tables)==2 and len(d.inline_shapes)==1
    assert export_pdf(*args).startswith(b'%PDF-')
def test_salted_passwords():
    a=hash_password('correct horse battery staple');b=hash_password('correct horse battery staple')
    assert a!=b and verify_password('correct horse battery staple',a)
    assert not verify_password('wrong',a) and not verify_password('any','invalid')

def test_historical_event_name_mismatch_does_not_count_as_attendance():
    e=R[0];u=[dict(employeeNo=e['terminal_id'],name=e['name'])]
    wrong=event(e['terminal_id'],'07:45:00');wrong['name']='A previous employee'
    rows,issues=build_report([e],u,[wrong],DAY,DAY,now=NOW)
    assert not rows[0]['Check in'] and issues

def test_retry_does_not_resubmit_identical_fingerprint():
    c=MagicMock();e=next(e for e in R if not e['already_registered'])
    c.search_users.return_value=[dict(employeeNo='123',name=e['name'])]
    c.get_user.return_value=c.search_users.return_value[0]
    c.upload_face.return_value=ApiResult(True,200,{'statusCode':1})
    template=[dict(fingerPrintID=1,fingerData='test-template')]
    with patch('enrollment.read_face',return_value=jpeg()),patch('enrollment.read_fingerprints',return_value=template):
        save_registration(c,e,'123',jpeg(),'test-template')
    c.apply_fingerprint.assert_not_called()

def test_partial_registration_remains_available_to_retry():
    e=next(e for e in R if not e['already_registered'] and e['terminal_id'])
    u=dict(employeeNo=e['terminal_id'],name=e['name'],numOfFace=1,numOfFP=0)
    assert e in pending_employees(R,[u])

def test_numeric_event_id_cannot_collapse_leading_zeros():
    ambiguous=dict(employeeNo=37,major=5,minor=75,time='2026-11-09T08:00:00+03:00')
    rows,issues=build_report(R,users(),[ambiguous],DAY,DAY,now=NOW)
    assert not any(r['Check in'] for r in rows) and issues
