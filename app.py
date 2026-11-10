"""MUM's single-terminal registration and attendance application."""
import os
import time as clock
from datetime import datetime, timedelta, time
from pathlib import Path

import pandas as pd
import streamlit as st
from attendance import TZ, REPORT_TYPES, build_report, select_rows, report_tables
from enrollment import save_registration
from hikvision import HikvisionClient, HikvisionError
from roster import load_roster, pending_employees, resolve_users
from security import verify_password
from report_tables import export_docx, export_pdf, export_xlsx

ROOT=Path(__file__).parent
st.set_page_config(page_title='MUM · Registration & Attendance',page_icon=str(ROOT/'assets/mum_logo.png'),layout='wide')

def setting(key,default=''):
    try:
        return st.secrets.get(key,os.getenv(key,default))
    except st.errors.StreamlitSecretNotFoundError:
        return os.getenv(key,default)

def as_bool(value):
    return str(value).lower() in ('true','1','yes')

roster=load_roster()
left,right=st.columns([1,8])
with left: st.image(str(ROOT/'assets/mum_logo.png'),width=115)
with right:
    st.title('Muslim University of Morogoro')
    st.caption('STAFF REGISTRATION & ATTENDANCE · DAR ES SALAAM TIME (UTC+3)')
    st.markdown('One university. Every department. A clear daily record.')

admin_ready=bool(setting('ADMIN_USERNAME') and setting('ADMIN_PASSWORD_HASH'))
terminal_ready=all(setting(k) for k in ['HIKVISION_URL','HIKVISION_USERNAME','HIKVISION_PASSWORD'])
# Expire sessions and in-memory biometric buffers after 30 minutes.
if st.session_state.get('signed_in') and clock.time()-st.session_state.get('last_active',0)>1800:
    st.session_state.clear()
if st.session_state.get('signed_in'):
    st.session_state.last_active=clock.time()
with st.sidebar:
    st.header('MUM control desk')
    st.caption('Default workday: 08:00–16:30')
    if not admin_ready:
        st.info('Administrator setup is pending. Add the administrator credentials in Streamlit Secrets.')
    elif not st.session_state.get('signed_in'):
        with st.form('login'):
            username=st.text_input('Username')
            password=st.text_input('Password',type='password')
            login=st.form_submit_button('Sign in')
        if login:
            if clock.time()<st.session_state.get('retry_after',0):
                st.error('Please wait a minute before trying again.')
            elif username == setting('ADMIN_USERNAME') and verify_password(password,setting('ADMIN_PASSWORD_HASH')):
                st.session_state.signed_in=True
                st.session_state.last_active=clock.time()
                st.rerun()
            else:
                st.session_state.failures=st.session_state.get('failures',0)+1
                if st.session_state.failures>=5: st.session_state.retry_after=clock.time()+60
                st.error('Sign-in details were not accepted.')
    else:
        st.success('Administrator signed in')
        if st.button('Sign out'):
            st.session_state.clear()
            st.rerun()
    st.divider()
    st.caption('Terminal address: configured' if terminal_ready else 'Terminal address: not configured yet')
    if st.session_state.get('signed_in') and terminal_ready and st.button('Check terminal compatibility'):
        try:
            c=HikvisionClient(setting('HIKVISION_URL'),setting('HIKVISION_USERNAME'),setting('HIKVISION_PASSWORD'),
                verify_tls=as_bool(setting('HIKVISION_VERIFY_TLS',True)))
            st.json(c.terminal_diagnostics())
        except (HikvisionError, AttributeError): st.error('Could not read the terminal. Check the connection settings.')

if not terminal_ready:
    st.info('Ready for setup. Add your terminal’s public address and credentials in Streamlit Secrets when available. Live registration and reports will then be enabled.')
authorized=bool(st.session_state.get('signed_in'))
client=HikvisionClient(setting('HIKVISION_URL'),setting('HIKVISION_USERNAME'),setting('HIKVISION_PASSWORD'),
    verify_tls=as_bool(setting('HIKVISION_VERIFY_TLS',True))) if terminal_ready and authorized else None

if client and ('users' not in st.session_state or clock.time()-st.session_state.get('users_at',0)>300):
    try:
        st.session_state.users=client.search_users()
        st.session_state.users_at=clock.time()
    except HikvisionError:
        st.session_state.pop('users',None)
        st.warning('The terminal employee list could not be refreshed. Check its connection before registering staff.')

registration,attendance=st.tabs(['Registration','Attendance'])
with registration:
    st.subheader('Register staff biometrics')
    st.caption('Select an employee, add a face photograph, capture a fingerprint at the terminal, then save.')
    if client and st.button('Refresh terminal employees'):
        try:
            st.session_state.users=client.search_users()
            st.session_state.users_at=clock.time()
            st.success('Terminal employee list refreshed.')
        except HikvisionError:
            st.session_state.pop('users',None)
            st.error('The terminal employee list could not be loaded. Check its connection and retry.')
    users=st.session_state.get('users',[]) if authorized else []
    candidates=pending_employees(roster,users)
    st.caption(f"{len(candidates)} registration candidates · 15 employees from the supplied terminal screenshot are already registered and excluded here.")
    departments=['All departments']+sorted({e['department'] for e in candidates})
    dept=st.selectbox('Registration department',departments)
    choices=[e for e in candidates if dept=='All departments' or e['department']==dept]
    selected=st.selectbox('Search and select employee',choices,index=None,
        format_func=lambda e:f"{e['name']} · {e['department']} · {e['employee_number'] or 'number needed'}",
        placeholder='Type a name to search…')
    if selected:
        key=selected['key']
        if st.session_state.get('selected_key')!=key:
            for k in ['fingerprint','fingerprint_slot']:
                st.session_state.pop(k,None)
            st.session_state.selected_key=key
        mapping,_=resolve_users(roster,users)
        number=st.text_input('Terminal employee number',value=mapping.get(key,selected['terminal_id']),key='id_'+key,
            help='Leading zeros are preserved. An existing number belonging to another person is rejected.')
        st.caption(selected['department_path'])
        photo=st.file_uploader('Face photograph (JPEG)',type=['jpg','jpeg'],key='photo_'+key)
        if photo: st.image(photo,width=150)
        slot=st.selectbox('Fingerprint slot',list(range(1,11)),key='slot_'+key)
        st.caption('The employee must be beside the terminal. Capture prepares the fingerprint; Save sends the registration.')
        if st.button('Capture fingerprint',disabled=client is None):
            st.session_state.pop('fingerprint',None)
            st.session_state.pop('fingerprint_slot',None)
            try:
                with st.spinner('Place the selected finger on the terminal reader…'):
                    captured=client.capture_fingerprint(slot)
                if captured.data:
                    st.session_state.fingerprint=captured.data
                    st.session_state.fingerprint_slot=slot
                    st.success('Fingerprint captured. Click Save registration to store it with the photograph.')
                else: st.error(captured.message or 'No fingerprint was captured. Please try again.')
            except HikvisionError:
                st.error('Capture could not complete. Check the terminal connection and compatibility.')
        ready=bool(st.session_state.get('fingerprint') and st.session_state.get('fingerprint_slot')==slot)
        if ready: st.caption('✓ Fingerprint ready for this employee and slot')
        if st.button('Save registration',type='primary',disabled=not(client and photo and ready)):
            try:
                with st.spinner('Saving and verifying face and fingerprint…'):
                    save_registration(client,selected,number.strip(),photo.getvalue(),st.session_state.fingerprint,slot)
                for k in ['fingerprint','fingerprint_slot','users','users_at']:
                    st.session_state.pop(k,None)
                # Clear uploaded photograph from memory following successful enrollment.
                st.session_state.pop('photo_'+key,None)
                st.session_state.saved_name=selected['name']
                st.rerun()
            except (HikvisionError,ValueError) as exc:
                # Never dump a network exception, request body or biometric template.
                text=str(exc)
                st.error(text if 'Could not connect' not in text else 'The connection was interrupted. Registration is not confirmed; retry Save.')
    if st.session_state.get('saved_name'):
        st.success(st.session_state.pop('saved_name')+' — face and fingerprint saved and verified.')
    if not client:
        st.caption('An administrator sign-in and terminal connection are required to capture or save.')

with attendance:
    st.subheader('Attendance reports')
    st.caption('Includes the entire employee roster, including the 15 people already registered on the terminal.')
    with st.expander('Report options',expanded=True):
        a,b=st.columns(2)
        with a:
            report_type=st.selectbox('Attendance report type',REPORT_TYPES)
            today=datetime.now(TZ).date()
            start=st.date_input('From date',today,max_value=today)
            shift_start=st.time_input('Check-in time',time(8))
        with b:
            department=st.selectbox('Attendance department',['All departments']+sorted({e['department'] for e in roster}))
            end=st.date_input('To date',today,max_value=today)
            shift_end=st.time_input('Check-out time',time(16,30))
        breakdown=st.checkbox('Include department breakdown',True)
    st.caption('Early = before check-in time. Checked in only = everyone with an arrival. Checkout = first later scan at or after check-out time. Today’s absences are provisional. All calendar dates in the selected range are included.')
    if st.button('Load live attendance',type='primary',disabled=client is None):
        st.session_state.pop('report',None)
        try:
            if shift_end<=shift_start: raise ValueError('Check-out time must be after check-in time.')
            if end<start or (end-start).days>92: raise ValueError('Choose an ordered date range of at most 93 days.')
            with st.spinner('Reading the full terminal roster and attendance log…'):
                live_users=client.search_users()
                events=client.search_events(start,end)
                rows,issues=build_report(roster,live_users,events,start,end,shift_start,shift_end)
            st.session_state.report=dict(rows=rows,issues=issues,start=start,end=end,shift_start=shift_start,shift_end=shift_end)
        except (HikvisionError,ValueError) as exc:
            st.error(str(exc) if isinstance(exc,ValueError) else 'The complete attendance log could not be loaded. No absence report was generated. Check the connection and retry.')
    report=st.session_state.get('report') if authorized else None
    if report:
        if (report['start'],report['end'],report['shift_start'],report['shift_end'])!=(start,end,shift_start,shift_end):
            st.warning('Options changed. Load live attendance again to update the report.')
        else:
            rows=select_rows(report['rows'],report_type,shift_start)
            if department!='All departments': rows=[r for r in rows if r['Department']==department]
            for issue in report['issues']: st.warning(issue)
            st.caption('Unmatched or unenrolled staff are listed separately from absentees. Reconcile terminal names before treating reports as complete.')
            summary=pd.DataFrame(rows)
            if not summary.empty:
                a,b,c=st.columns(3)
                a.metric('Employee-days',len(rows))
                b.metric('Checked in',sum(bool(r['Check in']) for r in rows))
                c.metric('Absentees',sum(r['Status'].startswith('Absent') for r in rows))
            download,view=st.tabs(['Download Reports','View Reports'])
            tables=report_tables(rows,breakdown)
            with view:
                if not rows: st.info('No employees match these report options.')
                for heading,columns,records in tables:
                    st.markdown('**'+heading+'**')
                    st.dataframe(pd.DataFrame(records,columns=columns),hide_index=True,use_container_width=True)
            with download:
                if rows:
                    title='Muslim University of Morogoro'
                    subtitle=f'{report_type} · {start} to {end} · {department}'
                    context=[f'Shift: {shift_start:%H:%M}–{shift_end:%H:%M} · Africa/Dar_es_Salaam',
                        'Today’s absences are provisional. Unenrolled / unmatched employees are not classified as absent.']
                    for label,export,mime,ext in [('Excel',export_xlsx,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','xlsx'),
                        ('PDF',export_pdf,'application/pdf','pdf'),('Word',export_docx,'application/vnd.openxmlformats-officedocument.wordprocessingml.document','docx')]:
                        data=export(title,subtitle,tables,str(ROOT/'assets/mum_logo.png'),context_lines=context)
                        st.download_button('Download '+label,data,f'MUM_{start}_{end}.{ext}',mime=mime)
    elif not client:
        st.info('Reports become available after administrator and terminal setup. No attendance or absences are assumed while the terminal is offline.')
    with st.expander('Employee roster & department allocation'):
        st.dataframe(pd.DataFrame([{'Employee Number':e['employee_number'],'Terminal number':e['terminal_id'],
            'Employee Name':e['name'],'Department':e['department'],'Department path':e['department_path'],
            'Already registered':e['already_registered'],'Terminal display name':e['terminal_alias']} for e in roster]),hide_index=True,use_container_width=True)
        st.caption('The two supplied exports are matched by exact employee name. Only names, departments and employee numbers are stored. The screenshot numbers are retained for already registered staff; 37 and 037 remain separate. Missing numbers must be assigned at registration.')
st.divider()
st.caption('MUM · Registration & Attendance · One Hikvision terminal')
