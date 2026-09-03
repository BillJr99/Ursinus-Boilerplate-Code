#!/usr/bin/env python3
"""
canvas_submission_types.py -- the syllabus's submission_types tokens, and what
Canvas should be told about them.

This lives on its own, apart from ursinus_canvas.py where it used to sit, for one
reason: it is the contract between a deliverable in _pages/syllabus.md and the
Canvas assignment that deliverable becomes, and more than one script now needs to
honor it. ursinus_canvas.py cannot be the home for it, because importing that
module pulls in canvasapi, frontmatter, requests, pytz, and yaml, and
ursinus_canvas_inline_changes.py promises that its --check mode parses a change
document with none of those installed.

Nothing here imports anything. Keep it that way.
"""

# Upload extension sets, selected by the tokens in a deliverable's submission_types string.
# A deliverable naming none of these tokens is left unrestricted, so that any file type can
# be submitted; see get_submission_spec below.
EXTENSIONS_WRITTEN = ['pdf', 'doc', 'docx', 'txt']
EXTENSIONS_ARCHIVE = ['zip', 'bz2', 'tar', 'gz', 'rar', '7z']
EXTENSIONS_PRESENTATION = ['ppt', 'pptx']


def get_submission_spec(submissiontypes):
    """Map a deliverable's submission_types string onto Canvas submission types and extensions.

    Returns (submission_types, allowed_extensions), where allowed_extensions is None when no
    restriction should be sent at all.  The tokens are matched as substrings of one free-text
    string, so a deliverable may name more than one and their extension sets accumulate:
    "written presentation" accepts everything either tag allows.

    An unrecognized or empty string yields an unrestricted upload.  That is the deliberate
    default: a deliverable whose author did not think to tag it should not silently refuse the
    PDF, image, or notebook a student tries to hand in.

    onpaper       -> on_paper
    noupload      -> online_text_entry
    written       -> online_upload + online_text_entry; pdf doc docx txt + the archives
    presentation  -> online_upload; pdf doc docx txt ppt pptx
    zip           -> online_upload; zip bz2 tar gz rar 7z
    (none)        -> online_upload; no extension restriction
    """
    submissiontypes = str(submissiontypes or "").lower()

    # These two describe how the work arrives rather than what file it is, so they short-circuit
    if "onpaper" in submissiontypes:
        return (['on_paper'], None)

    if "noupload" in submissiontypes:
        return (['online_text_entry'], None)

    types = ['online_upload']
    extensions = []

    # Accumulate in a stable order, and let a deliverable name several tags at once
    if "written" in submissiontypes:
        types.append('online_text_entry')
        extensions = extensions + EXTENSIONS_WRITTEN + EXTENSIONS_ARCHIVE

    if "presentation" in submissiontypes:
        extensions = extensions + EXTENSIONS_WRITTEN + EXTENSIONS_PRESENTATION

    if "zip" in submissiontypes:
        extensions = extensions + EXTENSIONS_ARCHIVE

    # Preserve first-seen order while dropping the overlap between the sets above
    deduped = []
    for extension in extensions:
        if not (extension in deduped):
            deduped.append(extension)

    # None rather than [], so that callers omit the key entirely: what an empty list does on
    # the wire depends on how it is encoded, and "no restriction" has to be expressed by not
    # asking for one rather than by asking for an empty one
    if len(deduped) == 0:
        return (types, None)

    return (types, deduped)


# The tokens get_submission_spec recognizes, in the order the usage text lists them. Callers
# that want to tell a free-text token string apart from a Canvas submission_types list can ask
# whether any of these appears in it.
SUBMISSION_TOKENS = ("onpaper", "noupload", "written", "presentation", "zip")

# What Canvas itself calls its submission types. A change document naming one of these directly
# is passing Canvas's own vocabulary, not the syllabus's, and must not be run through the token
# mapping above.
CANVAS_SUBMISSION_TYPES = (
    "online_upload", "online_text_entry", "online_url", "online_quiz",
    "on_paper", "discussion_topic", "external_tool", "media_recording",
    "student_annotation", "none", "not_graded",
)
