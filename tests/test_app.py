from pathlib import Path
from datetime import datetime,time
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from attendance import TZ,build_report
from roster import load_roster

def test_unconfigured_app_has_controls_and_no_network():
    with patch('hikvision.requests.Session.request',side_effect=AssertionError('Unexpected network')):
        app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=30).run()
        assert not app.exception
        assert [t.label for t in app.tabs][:2]==['Registration','Attendance']
        assert app.selectbox[1].label=='Search and select employee'
        assert len(app.selectbox[1].options)==148
        assert app.selectbox[2].label=='Attendance report type'
        assert app.time_input[0].value==time(8) and app.time_input[1].value==time(16,30)
        assert app.button[0].disabled
        app.selectbox[1].select_index(0).run()
        assert not app.exception
        assert any(b.label=='Capture fingerprint' and b.disabled for b in app.button)
        assert any(b.label=='Save registration' and b.disabled for b in app.button)

def test_authenticated_report_exports_without_live_requests():
    today=datetime.now(TZ).date()
    with patch('hikvision.requests.Session.request',side_effect=AssertionError('Unexpected network')):
        app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=45)
        import time as clock
        app.session_state['signed_in']=True;app.session_state['last_active']=clock.time()
        rows,_=build_report(load_roster(),[],[],today,today)
        app.session_state['report']=dict(rows=rows,issues=[],start=today,end=today,shift_start=time(8),shift_end=time(16,30))
        app.run();assert not app.exception
        assert any(t.label=='Download Reports' for t in app.tabs)
        assert any(t.label=='View Reports' for t in app.tabs)
        assert len(app.get('download_button'))==3

def test_terminal_failure_never_generates_absence_report():
    import os,time as clock
    from hikvision import HikvisionError
    from unittest.mock import MagicMock
    c=MagicMock();c.search_users.side_effect=HikvisionError('offline')
    settings={'HIKVISION_URL':'https://terminal.test','HIKVISION_USERNAME':'test','HIKVISION_PASSWORD':'test'}
    with patch.dict(os.environ,settings),patch('hikvision.HikvisionClient',return_value=c):
        app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=20)
        app.session_state['signed_in']=True;app.session_state['last_active']=clock.time()
        app.run();assert not app.exception
        next(b for b in app.button if b.label=='Load live attendance').click().run()
        assert not app.exception
        assert any('No absence report was generated' in error.value for error in app.error)
        assert len(app.get('download_button'))==0
