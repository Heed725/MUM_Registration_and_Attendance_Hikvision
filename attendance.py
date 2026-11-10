from collections import defaultdict
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from roster import resolve_users, matches

TZ = ZoneInfo('Africa/Dar_es_Salaam')
REPORT_TYPES = ['Full attendance', 'Early attendance', 'Checked in only', 'Absentees']
COLUMNS = ['Date', 'Employee Number', 'Employee Name', 'Department', 'Check in', 'Check out', 'Status', 'Minutes late']
# Hikvision AccessControl successful identity verification events (major 5).
SUCCESS_MINORS = {1, 38, 75}

def build_report(roster, users, events, start, end, shift_start=time(8), shift_end=time(16,30), now=None):
    if end < start or (end-start).days > 92:
        raise ValueError('Choose a date range of at most 93 days, with the end after the start.')
    now = now or datetime.now(TZ)
    if start > now.date() or end > now.date():
        raise ValueError('Attendance cannot be generated for future dates.')
    mapping, issues = resolve_users(roster, users)
    reverse = {v:k for k,v in mapping.items()}
    by_key = {e['key']:e for e in roster}
    scans = defaultdict(set)
    ignored = 0
    for event in events:
        try:
            # Reject door alarms, denied access, invalid cards and remote-open events.
            if int(event.get('major', 0)) != 5 or int(event.get('minor', 0)) not in SUCCESS_MINORS:
                continue
            raw_number = event.get('employeeNoString') or event.get('employeeNo') or ''
            number = str(raw_number)
            # Numeric event fields can lose leading zeros; do not guess between 37 and 037.
            if not event.get('employeeNoString') and not isinstance(raw_number, str) and number.isdigit():
                equivalents = [n for n in reverse if n.isdigit() and int(n) == int(number)]
                if len(equivalents) > 1:
                    ignored += 1
                    continue
            if number not in reverse:
                ignored += 1
                continue
            if event.get('name') and not matches(by_key[reverse[number]],event):
                ignored += 1
                continue
            stamp = datetime.fromisoformat(event['time'].replace('Z','+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=TZ)
            stamp = stamp.astimezone(TZ)
            if start <= stamp.date() <= end and stamp <= now:
                scans[(reverse[number], stamp.date())].add(stamp)
        except (ValueError, TypeError, KeyError):
            ignored += 1
    rows=[]
    for offset in range((end-start).days+1):
        day = start+timedelta(days=offset)
        for employee in roster:
            values=sorted(scans[(employee['key'],day)])
            arrival=values[0] if values else None
            departures=[v for v in values[1:] if v.time().replace(tzinfo=None) >= shift_end]
            departure=departures[0] if departures else None
            status = ('Not enrolled / unmatched' if employee['key'] not in mapping else
                ('Absent (provisional)' if day == now.date() else 'Absent') if not arrival else
                'Present' if departure else 'Checked in — no checkout')
            late = max(0,int((arrival-datetime.combine(day,shift_start,TZ)).total_seconds()//60)) if arrival else ''
            rows.append(dict(zip(COLUMNS,[str(day),mapping.get(employee['key'], employee['terminal_id']),
                employee['name'],employee['department'],arrival.strftime('%H:%M:%S') if arrival else '',
                departure.strftime('%H:%M:%S') if departure else '',status,late])))
    if ignored:
        issues.append(f'{ignored} attendance events had unknown employee numbers or invalid timestamps; they were excluded.')
    return rows, issues

def select_rows(rows, report_type, shift_start=time(8)):
    if report_type == 'Early attendance':
        return [r for r in rows if r['Check in'] and time.fromisoformat(r['Check in']) < shift_start]
    if report_type == 'Checked in only':
        return [r for r in rows if r['Check in']]
    if report_type == 'Absentees':
        return [r for r in rows if r['Status'].startswith('Absent')]
    return rows

def report_tables(rows, breakdown):
    tables=[('Attendance report', COLUMNS, rows)]
    if breakdown:
        tables.extend((department,COLUMNS,[r for r in rows if r['Department']==department])
            for department in sorted({r['Department'] for r in rows}))
    return tables
