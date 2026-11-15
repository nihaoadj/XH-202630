# Platform-owned courseware assets

`theme.css` and `runtime.js` contain the final static sources embedded by the
renderer. They are maintained by the platform and are not model output.

T13 moved the previous Python concatenation/patch results here without changing
their bytes, override order, events, security rules or version 2.2. Existing CSS
cascade overrides remain in their original order; this extraction is not a
visual redesign or cascade cleanup. Edit the actual JS/CSS instead of restoring
Python string marker replacements.

`runtime.py` reads UTF-8 relative to its own file and normalizes Git checkout
line endings to LF. Keep the files in deployed backend source copies; the
current Docker `COPY backend ./backend` already includes this directory. Assets
are still embedded in HTML and do not create external requests or new URLs.

Validate asset changes against renderer/security/packaging, the frozen workflow
HTML baseline and browser gates. Intentional output changes need the relevant
version/fixture update and a separate behavior-change plan.
