import pytest
import sys
import os

# Patch sys.argv before importing convert, since parse_args() runs at module level
sys.argv = ['convert.py', '/dev/null']

import mwparserfromhell
from convert import (
    clean_wikilink,
    fix_wikilink_spacing,
    clean_heading_ids,
    extract_links_from_pandoc,
    extract_yaml_header,
    extract_infobox,
    clean_and_convert_text,
    strip_html_artifacts,
    convert_footnotes,
    convert_definition_lists,
    fix_image_links,
    _extract_outline_header,
)

# ── Obsidian-mode tests (existing behavior) ──────────────────────────

# Test 1: Wikilink formatting
def test_clean_wikilink_simple():
    assert clean_wikilink("Foo_Bar", output_format="obsidian") == "[[Foo Bar]]"

def test_clean_wikilink_with_alias():
    assert clean_wikilink("Foo_Bar|Alias", output_format="obsidian") == "[[Foo Bar|Alias]]"

def test_fix_wikilink_spacing():
    text = "This is a [[Foo_Bar]] and a [[Baz_Bat|Alias]] link."
    result = fix_wikilink_spacing(text, output_format="obsidian")
    assert result == "This is a [[Foo Bar]] and a [[Baz Bat|Alias]] link."

# Test 2: Heading cleanup
def test_clean_heading_ids():
    md = "# Heading 1 {#heading1}\n## Heading 2 {#heading2}"
    expected = "# Heading 1\n## Heading 2"
    assert clean_heading_ids(md) == expected

# Test 3: Pandoc-style link cleanup
def test_extract_links_from_pandoc_internal():
    md = 'This is a [Foo Bar](Foo_Bar "wikilink") and [Alias](Target_Page "wikilink").'
    expected = 'This is a [[Foo Bar]] and [[Target Page|Alias]].'
    assert extract_links_from_pandoc(md, output_format="obsidian") == expected

def test_extract_links_from_pandoc_external():
    md = 'Visit [Google](https://google.com) or contact [me](mailto:test@example.com).'
    assert extract_links_from_pandoc(md, output_format="obsidian") == md  # Should remain unchanged

# Test 4: YAML frontmatter generation
def test_extract_yaml_header_basic():
    title = "Sample_Page"
    tags = ["category_one", "tag_two"]
    result = extract_yaml_header(title, tags, output_format="obsidian")
    assert "---" in result
    assert "title: Sample Page" in result
    assert "tags:" in result
    assert "- category_one" in result
    assert "- tag_two" in result

# Test 5: Infobox parsing and tag inference
def test_extract_infobox_and_tags():
    wikitext = """
{{Infobox_character
| name = Aragorn
| race = [[Human]]
| weapon = [[Andúril]]
}}
[[Category:Characters]]
"""
    wikicode = mwparserfromhell.parse(wikitext)
    _cleaned_wikicode, infobox = extract_infobox(wikicode, output_format="obsidian")

    assert infobox["infobox"] == "Character"
    assert "name" in infobox
    assert "race" in infobox
    assert infobox["weapon"] == ["[[Andúril]]"]

def test_clean_and_convert_text_adds_infobox_tag():
    wikitext = """
{{Infobox_artifact
| name = One Ring
| creator = [[Sauron]]
}}
[[Category:Items]]
"""
    header, _text, tags = clean_and_convert_text(wikitext, "One_Ring", output_format="obsidian")
    assert "artifacts" in [t.lower() for t in tags]
    assert "items" in [t.lower() for t in tags]
    assert "---" in header


# ── Outline-mode tests ──────────────────────────────────────────────

# Test: Wikilink → standard markdown link in outline mode
def test_clean_wikilink_outline_simple():
    result = clean_wikilink("Foo_Bar", output_format="outline")
    assert result == "[Foo Bar](./Foo_Bar.md)"

def test_clean_wikilink_outline_with_alias():
    result = clean_wikilink("Foo_Bar|Alias", output_format="outline")
    assert result == "[Alias](./Foo_Bar.md)"

def test_fix_wikilink_spacing_outline():
    text = "This is a [[Foo_Bar]] and a [[Baz_Bat|Alias]] link."
    result = fix_wikilink_spacing(text, output_format="outline")
    assert "[Foo Bar](./Foo_Bar.md)" in result
    assert "[Alias](./Baz_Bat.md)" in result
    assert "[[" not in result

# Test: Pandoc link cleanup in outline mode
def test_extract_links_from_pandoc_outline():
    md = 'This is a [Foo Bar](Foo_Bar "wikilink") and [Alias](Target_Page "wikilink").'
    result = extract_links_from_pandoc(md, output_format="outline")
    assert "[Foo Bar](./Foo_Bar.md)" in result
    assert "[Alias](./Target_Page.md)" in result
    assert "[[" not in result

def test_extract_links_from_pandoc_external_outline():
    md = 'Visit [Google](https://google.com) or contact [me](mailto:test@example.com).'
    assert extract_links_from_pandoc(md, output_format="outline") == md

# Test: Outline header (no YAML frontmatter)
def test_extract_yaml_header_outline():
    title = "Sample_Page"
    tags = ["category_one", "tag_two"]
    result = extract_yaml_header(title, tags, output_format="outline")
    assert "# Sample Page" in result
    # Should NOT have YAML frontmatter delimiters at the start
    assert not result.startswith("---")
    assert "`category_one`" in result
    assert "`tag_two`" in result

def test_extract_outline_header_with_extra_fields():
    title = "Test_Page"
    tags = ["test"]
    extra = {"name": "Aragorn", "race": ["[[Human]]"], "image": "hero.png", "infobox": "Character"}
    result = _extract_outline_header(title, tags, extra)
    assert "# Test Page" in result
    assert "| **Name** |" in result
    assert "| **Race** |" in result

def test_extract_outline_header_no_tags():
    result = _extract_outline_header("Page", [], None)
    assert "# Page" in result
    assert "| Field | Value |" not in result

# Test: Image links in outline mode
def test_fix_image_links_outline():
    md = "Some text ![[images/photo.jpg]] more text"
    result = fix_image_links(md, output_format="outline")
    assert "![photo.jpg](./images/photo.jpg)" in result
    assert "![[" not in result

def test_fix_image_links_outline_escaped():
    md = "Some text \\![[images/photo.jpg]] more text"
    result = fix_image_links(md, output_format="outline")
    assert "![photo.jpg](./images/photo.jpg)" in result

# Test: HTML artifact stripping
def test_strip_html_br():
    assert strip_html_artifacts("Hello<br>World") == "Hello\n\nWorld"
    assert strip_html_artifacts("Hello<br/>World") == "Hello\n\nWorld"
    assert strip_html_artifacts("Hello<br />World") == "Hello\n\nWorld"

def test_strip_html_sup():
    assert strip_html_artifacts("E=mc<sup>2</sup>") == "E=mc$^{2}$"

def test_strip_html_sub():
    assert strip_html_artifacts("H<sub>2</sub>O") == "H$_{2}$O"

def test_strip_html_tags():
    assert strip_html_artifacts("<div>Hello</div>") == "Hello"
    assert strip_html_artifacts("<span class='x'>text</span>") == "text"

# Test: Footnote conversion
def test_convert_footnotes():
    md = "Some text[^1] and more[^2].\n\n[^1]: First note\n[^2]: Second note"
    result = convert_footnotes(md)
    assert "$^{1}$" in result
    assert "$^{2}$" in result
    assert "**References**" in result
    assert "1. First note" in result
    assert "2. Second note" in result
    assert "[^1]" not in result

def test_convert_footnotes_no_footnotes():
    md = "Just regular text with no footnotes."
    assert convert_footnotes(md) == md

# Test: Definition list conversion
def test_convert_definition_lists():
    md = "Apple\n:   A fruit\n:   A company\nBanana\n:   A yellow fruit"
    result = convert_definition_lists(md)
    assert "**Apple**" in result
    assert "  A fruit" in result
    assert "  A company" in result
    assert "**Banana**" in result
    assert "  A yellow fruit" in result

def test_convert_definition_lists_no_defs():
    md = "Just a regular paragraph.\nAnother line."
    assert convert_definition_lists(md) == md

# Test: Outline header from clean_and_convert_text
def test_clean_and_convert_text_outline():
    wikitext = """
{{Infobox_artifact
| name = One Ring
| creator = [[Sauron]]
}}
[[Category:Items]]
"""
    header, _text, tags = clean_and_convert_text(wikitext, "One_Ring", output_format="outline")
    assert "# One Ring" in header
    assert "---\n" not in header.split("# ")[0]  # No YAML frontmatter before title
    assert "items" in [t.lower() for t in tags]