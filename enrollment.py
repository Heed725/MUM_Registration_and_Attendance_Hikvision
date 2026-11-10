"""Save explicit credentials and confirm them before reporting success."""
from datetime import date
from io import BytesIO
from PIL import Image, ImageChops, ImageOps, ImageStat
from biometric_protocol import prepare_face_jpeg
from biometric_readback import read_face, read_fingerprints
from hikvision import HikvisionError, response_message
from roster import matches

def save_registration(client, employee, number, photo, fingerprint, finger_slot=1):
    if employee['already_registered']:
        raise HikvisionError('This employee is already registered and excluded from registration.')
    if not number or not number.isascii() or not number.isalnum() or len(number) > 32:
        raise HikvisionError('Enter a unique terminal employee number (1–32 letters or digits).')
    if not photo or not fingerprint:
        raise HikvisionError('Add a face photograph and capture a fingerprint before saving.')
    prepared = prepare_face_jpeg(photo)
    users = client.search_users()
    other_ids = [str(u['employeeNo']) for u in users if matches(employee, u) and str(u['employeeNo']) != number]
    if other_ids:
        raise HikvisionError('This employee already has a different terminal number. Refresh and use that number.')
    existing = next((u for u in users if str(u['employeeNo']) == number), None)
    if existing and not matches(employee, existing):
        raise HikvisionError('This terminal number belongs to another name. Nothing was changed.')
    if not existing:
        client.create_user(dict(employee_no=number, name=employee['name'], gender='unspecified',
            valid_from=date.today().isoformat(), valid_until='2036-12-31', access_plan=1))
    saved = client.get_user(number)
    if not saved or not matches(employee, saved):
        raise HikvisionError('Employee identity could not be verified; no biometrics were sent.')
    result = client.upload_face(number, prepared, name=saved['name'])
    if not result.ok:
        raise HikvisionError('Face was not saved: ' + response_message(result))
    actual = read_face(client, number)
    if not actual:
        raise HikvisionError('Face read-back was not confirmed. Registration is incomplete; retry Save.')
    with Image.open(BytesIO(prepared)) as before, Image.open(BytesIO(actual)) as after:
        difference = ImageStat.Stat(ImageChops.difference(
            ImageOps.exif_transpose(before).convert('RGB').resize((32,32)),
            ImageOps.exif_transpose(after).convert('RGB').resize((32,32))))
        if max(difference.mean) > 12:
            raise HikvisionError('The returned face photograph did not match. Registration is incomplete.')
    # A previous interrupted save may already have stored this exact template.
    # Reading first makes retries idempotent without overwriting another slot.
    try:
        existing_fingers = read_fingerprints(client, number)
    except HikvisionError:
        existing_fingers = []
    already_saved = any(str(f.get('fingerPrintID')) == str(finger_slot) and f.get('fingerData') == fingerprint
        for f in existing_fingers)
    if not already_saved:
        result = client.apply_fingerprint(number, fingerprint, finger_slot)
        if not result.ok:
            raise HikvisionError('Face saved; fingerprint was not saved: ' + response_message(result))
    if not any(str(f.get('fingerPrintID')) == str(finger_slot) and f.get('fingerData') == fingerprint
               for f in read_fingerprints(client, number)):
        raise HikvisionError('Fingerprint read-back was not confirmed. Registration is incomplete; retry Save.')
