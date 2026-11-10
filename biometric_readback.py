"""Read enrolled credentials back for confirmation; biometric data stays in memory."""
import uuid
import json
from io import BytesIO
from email import policy
from email.parser import BytesParser
from urllib.parse import urlsplit
from PIL import Image, UnidentifiedImageError
from hikvision import ApiResult, HikvisionError, response_message

def checked(result, action):
    if not result.ok:
        # Never fall back to a raw response containing biometric data or URLs.
        status = result.payload.get('ResponseStatus', result.payload)
        safe = {key: status[key] for key in ('statusString', 'subStatusCode')
                if isinstance(status, dict) and key in status}
        if 'FingerPrintStatus' in result.payload:
            safe['FingerPrintStatus'] = result.payload['FingerPrintStatus']
        reason = response_message(ApiResult(False, result.status_code, safe))
        raise HikvisionError(f'{action}: {reason}')
    return result.payload

def records(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise HikvisionError('The terminal returned an invalid credential list.')

def read_fingerprints(client, employee_no):
    payload = checked(client._request('POST', '/ISAPI/AccessControl/FingerPrintUpload?format=json',
        json={'FingerPrintCond': {'searchID': uuid.uuid4().hex, 'employeeNo': str(employee_no)}}),
        'Could not export fingerprints')
    info = payload.get('FingerPrintInfo')
    if not isinstance(info, dict) or info.get('status') not in ('OK', 'NoFP'):
        raise HikvisionError('The terminal did not confirm its fingerprint export results.')
    items = records(info.get('FingerPrintList', []))
    if info['status'] == 'OK' and not items:
        raise HikvisionError('The terminal returned an incomplete fingerprint export.')
    if info['status'] == 'NoFP' and items:
        raise HikvisionError('The terminal returned inconsistent fingerprint results.')
    found = {}
    for item in items:
        if 'employeeNo' in item and str(item['employeeNo']) != str(employee_no):
            raise HikvisionError('The terminal returned a fingerprint for a different employee.')
        finger_id = int(item.get('fingerPrintID', 0))
        if not 1 <= finger_id <= 10 or not item.get('fingerData'):
            raise HikvisionError('A fingerprint template could not be exported.')
        finger = {key: item[key] for key in ('fingerPrintID', 'fingerType', 'fingerData', 'leaderFP') if key in item}
        finger['fingerPrintID'] = finger_id
        finger.setdefault('fingerType', 'normalFP')
        if finger_id in found and found[finger_id] != finger:
            raise HikvisionError('Different reader templates use the same finger slot; registration cannot verify them.')
        found[finger_id] = finger
    return list(found.values())

def face_response(response):
    """Decode plain JSON and JSON+JPEG multipart responses without logging bytes."""
    content_type = response.headers.get('Content-Type', '')
    pictures = []
    if content_type.lower().startswith('multipart/'):
        message = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + response.content)
        payload = None
        for part in message.walk():
            if part.get_content_type() == 'application/json':
                try:
                    payload = json.loads(part.get_payload(decode=True))
                except (ValueError, TypeError):
                    raise HikvisionError('The terminal returned invalid face metadata.') from None
            elif part.get_content_type().startswith('image/'):
                pictures.append(part.get_payload(decode=True))
        if not isinstance(payload, dict):
            raise HikvisionError('The terminal did not return face metadata.')
    else:
        try:
            payload = response.json()
        except ValueError:
            raise HikvisionError('The terminal does not provide a supported face export response.') from None
        if not isinstance(payload, dict):
            raise HikvisionError('The terminal returned invalid face metadata.')
    return payload, pictures

def read_face(client, employee_no):
    response = client._send('POST', '/ISAPI/Intelligent/FDLib/FDSearch?format=json',
        json={'searchID': uuid.uuid4().hex, 'searchResultPosition': 0, 'maxResults': 1,
              'faceLibType': 'blackFD', 'FDID': '1', 'FPID': str(employee_no)})
    payload, pictures = face_response(response)
    checked(ApiResult(response.ok and client._is_success(payload), response.status_code, payload),
            'Could not export the face photograph')
    result = payload.get('FDSearch', payload)
    if not isinstance(result, dict) or 'numOfMatches' not in result:
        raise HikvisionError('The terminal did not confirm its face search results.')
    if int(result['numOfMatches']) == 0 and int(result.get('totalMatches', 0)) == 0:
        return b''
    matches = records(result.get('MatchList', []))
    if len(matches) != 1 or int(result.get('totalMatches', 1)) != 1:
        raise HikvisionError('Verification requires one face photograph per employee in library 1.')
    match = matches[0]
    if str(match.get('FPID', '')) != str(employee_no):
        raise HikvisionError('The terminal returned a face photograph for a different employee.')
    if match.get('modelStatus') in ('unmodeled', 'modelingFailed'):
        raise HikvisionError('The terminal has not built a working face model.')
    # A model alone is not a portable photograph; never silently omit the photo.
    if len(pictures) == 1:
        image = pictures[0]
    elif not pictures and (match.get('faceURL') or match.get('picURL')):
        location = urlsplit(match.get('faceURL') or match['picURL'])
        # Terminals often return a private LAN address. Keep the configured public
        # station origin and use only the returned path/query, with no redirects.
        if not location.path.startswith('/') or location.path.startswith('//'):
            raise HikvisionError('The terminal returned an invalid face photograph address.')
        path = location.path + ('?' + location.query if location.query else '')
        download = client._send('GET', path, allow_redirects=False)
        if download.status_code != 200:
            raise HikvisionError(f'Could not download the enrolled face photograph (HTTP {download.status_code}).')
        image = download.content
    else:
        raise HikvisionError('The terminal did not export the enrolled face photograph.')
    if not isinstance(image, bytes) or not image.startswith(b'\xff\xd8\xff') or len(image) > 5 * 1024 * 1024:
        raise HikvisionError('The terminal did not export a valid JPEG face photograph.')
    try:
        with Image.open(BytesIO(image)) as photograph:
            photograph.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HikvisionError('The terminal exported an unreadable face photograph.') from None
    return image
