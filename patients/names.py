import re
import unicodedata


_NUMBER_PREFIX = re.compile(r'^\s*(?:\d+[\s.)-]+)+(?=[^\W\d_])')


def normalize_patient_name(value, *, remove_number_prefix=False):
    if remove_number_prefix:
        value = _NUMBER_PREFIX.sub('', value)
    return unicodedata.normalize('NFC', value).title()
