# docling-pk Design Document

## 1. Project Summary
_Owner: Lead Engineer - not yet filled in_

## 2. Problem Statement
_Not yet filled in_

## 3. Technical Approach - CNIC Extraction
Owner: Abdul Moiz Muhammad (Research / Implementation Engineer)

### OCR Library Choice

EasyOCR over pytesseract, per the brief. Confirmed this is the right call for two
reasons beyond what was already stated: it needs no system-level install (pytesseract
needs a separate Tesseract binary, which complicates the pip-install-only goal), and
it handles Arabic-script characters out of the box, which Urdu text on CNICs needs.

Tradeoff: EasyOCR's models are close to 500MB combined and load slowly on first run.
Accepted, since correctness matters more than install size for this use case, and the
reader is loaded once per process and reused, not reloaded per document.

### Preprocessing Pipeline

Six steps: load and validate, grayscale, blur check, deskew, denoise, adaptive
threshold. Deskew runs before denoise, since the rotation angle estimate is
cleaner on raw grayscale than on a denoised image.

#### Blur handling

Tested against two real samples deliberately shot out of focus. Neither the
preprocessing pipeline nor raw unprocessed OCR could extract anything usable
from either. Root cause: adaptive thresholding assumes a sharp edge between
ink and background; blur turns that edge into a wide gradient, and the
threshold traces a hollow outline of each letter instead of a filled shape.
A human can still read the outline; EasyOCR cannot.

Deblurring is a research problem on its own and out of scope for v1. Instead,
blur is detected up front using the variance of the Laplacian (a standard,
cheap sharpness measure), and the pipeline fails gracefully with a clear
warning instead of returning garbage output. Threshold picked from 4 real
samples: two failing blurry images scored 12.9 and 27.1, two working images
scored 48.2 and 54.9. The threshold (35) sits in that gap but is based on a
small sample and should be recalibrated as more images are tested.

#### Rotation handling

Deskew corrects small angles using the minimum-area bounding box of dark
pixels. Full 90/180/270-degree rotations are a separate, common problem with
phone photos: the OCR step runs at all four right-angle rotations and keeps
whichever result has the highest confidence times detection count. Confirmed
necessary on a real sample shot in portrait against a landscape card:
unusable output before this fix, correct output after.

Known unresolved gap: deskew fails against cluttered or textured backgrounds.
Tested directly on a real tilted sample photographed against striped fabric:
the angle detector reported 0.0 degrees on a visibly tilted card, because it
measures skew across every dark pixel in the frame, including the background
pattern, not the document specifically. The fix (detecting the card's actual
boundary before measuring its angle) is a different technique, not a patch
to this one, and is being explored separately rather than folded into v1.
Until then, v1's practical constraint is a plain background behind the
document.

Tested and rejected: 2x upscaling before OCR, on the theory that small
printed labels needed more pixels for the detector. Measured result was
worse, not better, on both original test samples (field extraction dropped
from 6/8 to 5/8 and 4/8). Likely cause is that upscaling amplifies
compression artifacts as much as it enlarges text. Not used in the current
pipeline.

### Raw OCR Output on Real Samples

Tested against two real Smart CNIC photos. Findings that shaped the parser:

- Label text is frequently misread in small, specific ways: "Gender" as "GenUer",
  "of" as "o{" or "o/", "Father Name" as "Fathgr Name" or "Father Namg". Label
  matching uses loose patterns on the stable part of each word rather than exact
  text.
- Date labels and date values are not adjacent in the OCR output. All three date
  labels (birth, issue, expiry) are read as a group, then all three values are read
  as a separate group further down. Matching "the line after the label" does not
  work for dates. Dates are instead extracted by format alone and assigned by fixed
  position (birth, issue, expiry, in that order), since NADRA prints them in that
  order consistently across both samples tested.
- The CNIC number separator is misread inconsistently: underscore, colon, and
  backtick have all appeared in place of the dash across two samples. All are
  normalized before matching.
- Gender is not reliably recoverable as text on both samples tested. On one card
  the value character was dropped by the detector entirely; on the other it read
  correctly as a plain "M" in a table cell. This appears to depend on the specific
  card's print quality or sub-format, not something fixable with better regex.
- A name that wraps across two lines can be split apart in the output, with the
  second line appearing far later in the reading order (near the signature section
  in one sample). This is a reading-order problem, not a text problem, and is not
  solved in the current version.

### cnic_number Extraction

Matched directly against the known format XXXXX-XXXXXXX-X after normalizing
common separator misreads (underscore, colon, backtick all mapped to dash).
Confidence set at 0.92 on a match, since the fixed format makes false positives
unlikely.

### Partial or Missing Fields

Every field extractor returns None with 0.0 confidence rather than raising or
guessing, matching the brief's fail-gracefully requirement. Document-level
confidence is the average across all 8 fields, including ones that were not
found, not just the ones that succeeded. An earlier version of this averaged only
the found fields, which reported 0.77 on a document that was actually missing 2 of
8 fields. Averaging across all fields dropped that same result to 0.58, which is
the more honest number and the one used going forward.

### Known Limitations (v1)

- Gender extraction is unreliable and not solved in this version.
- Address is not extracted. The front of a Smart CNIC does not print an address at
  all; it is on the back. Needs a scope decision: does v1 require back-of-card
  images, or is address deferred entirely.
- Multi-line values (a wrapped name) can be split and misordered in the output.
- Images below a measured sharpness threshold are rejected outright with a
  "please retake the photo" warning rather than processed. This is intentional,
  not a gap, but the threshold is based on 4 samples and should be recalibrated
  with more data.
- Deskew assumes a plain background behind the document. Tested and confirmed
  broken on a real sample with a textured (fabric) background. Practical
  constraint for v1 rather than a fix: document should be photographed against
  a plain surface.
- Both the gender and wrapped-name issues point toward the same underlying
  limitation: full-page OCR plus text matching has no way to recover text the
  detector missed or scattered. A more accurate approach would align the card to
  a fixed orientation and OCR small, known regions per field individually, rather
  than the whole card at once. This is a different architecture, not a fix to the
  current one, and is being explored separately rather than folded into v1 scope.

## 4. Module Ownership Table
_Owner: Lead Engineer - not yet filled in_

## 5. Evaluation Plan
_Owner: Integration Engineer - not yet filled in_

## 6. Known Risks
_Not yet filled in_

## 7. Definition of Done
_Owner: Lead Engineer - not yet filled in_