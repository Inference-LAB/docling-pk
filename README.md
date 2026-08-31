# docling-pk

Extract structured data from Pakistani identity and education documents,
from a photo, without a cloud API.

Supported document types in v1: CNIC, Matric certificate, Intermediate
certificate. Degree/Transcript is not supported yet, see Known Limitations.

## Installation

```bash
pip install docling-pk
```

## Quickstart

```python
from docling_pk.extractor import extract

result = extract("path/to/cnic_photo.jpg", document_type="cnic")

print(result.confidence)
print(result.fields["name"].value)
print(result.warnings)
```

Or from the command line:

```bash
docling-pk cnic path/to/cnic_photo.jpg
```

## Supported Document Types

| Type | Fields extracted |
|---|---|
| `cnic` | name, father_name, cnic_number, date_of_birth, date_of_issue, date_of_expiry, gender, address |
| `matric` | serial_number, certificate_number, roll_number, registration_number, group, session_year, grade, name, father_name, institute, date_of_birth, total_marks_possible, total_marks_obtained |
| `intermediate` | same as matric, minus date_of_birth (not printed on this certificate type) |

`matric` and `intermediate` share a parser structure (both from Federal
Board Islamabad in current testing) and are told apart automatically from
the certificate's own title text, not from the document_type argument
alone.

## Known Limitations

- **Address on CNIC** is only extracted from the front of the card. The
  front of a Smart CNIC does not print an address at all, it is on the
  back, in Urdu (Nastaliq script). Back-of-card address extraction was
  investigated extensively and found to be a genuine, currently unsolved
  problem across every tool tested (see design doc for the full
  investigation). Not supported in v1.
- **Gender** on CNIC is unreliable. Some card sub-formats print it as
  plain text, others render it in a way that is not reliably recoverable
  from OCR output.
- **Grade** on Matric/Intermediate certificates is unreliable, for the
  same underlying reason as gender: the character is either dropped or
  misread by OCR.
- **Institute name** on Matric/Intermediate is not extracted. Tested and
  found too badly corrupted by OCR on real samples to parse reliably.
- **Deskew** (image rotation correction) assumes a plain background
  behind the document. Confirmed to fail against cluttered or textured
  backgrounds (e.g. a patterned surface behind the photo).
- **Blurry images** are rejected with a clear warning rather than
  processed, based on a sharpness threshold calibrated on a small number
  of real samples. This threshold may need adjustment as more real-world
  images are tested.
- **Degree/Transcript** is not implemented in v1.

## Requirements

- Python 3.9+
- A GPU is recommended for reasonable OCR speed, not required.

## License

TBD