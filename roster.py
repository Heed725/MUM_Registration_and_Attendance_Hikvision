"""University roster: only names, employee numbers and departments are imported."""
import json
import re
import unicodedata
from pathlib import Path

def normalize(name):
    text = unicodedata.normalize('NFKC', name or '').casefold()
    text = re.sub(r'\b(?:prof|dr|mr|mrs|ms)\.?', ' ', text)
    return ' '.join(re.findall(r'\w+', text))

def load_roster():
    return json.loads((Path(__file__).parent / 'data/employees.json').read_text())

def matches(employee, user):
    return normalize(user.get('name', '')) in {normalize(employee['name']), normalize(employee.get('terminal_alias', ''))} - {''}

def resolve_users(roster, users):
    """A terminal number alone never overrides a mismatched identity."""
    mapping, issues, claimed = {}, [], set()
    for employee in roster:
        candidates = [u for u in users if matches(employee, u)]
        if len(candidates) == 1:
            number = str(candidates[0]['employeeNo'])
            if number in claimed:
                issues.append(f"Ambiguous terminal identity for {employee['name']}")
            else:
                mapping[employee['key']] = number
                claimed.add(number)
        elif candidates:
            issues.append(f"Multiple terminal profiles match {employee['name']}; reconcile them before reporting.")
        elif any(str(u['employeeNo']) == employee['terminal_id'] for u in users):
            issues.append(f"Number {employee['terminal_id']} is assigned to another name; {employee['name']} is not matched.")
    return mapping, issues

def pending_employees(roster, users=()):
    mapping, _ = resolve_users(roster, users)
    by_id = {str(u['employeeNo']): u for u in users}
    return [e for e in roster if not e['already_registered'] and not (
        e['key'] in mapping and all(int(by_id[mapping[e['key']]].get(field, 0) or 0) > 0
            for field in ('numOfFace', 'numOfFP')))]
