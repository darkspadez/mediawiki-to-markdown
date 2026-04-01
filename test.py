import pytest
import sys
import os
import xml.etree.ElementTree as ET

# Patch sys.argv before importing convert, since parse_args() runs at module level
sys.argv = ['convert.py', '/dev/null']

import convert
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
    extract_wiki_domain,
    plan_pages,
    convert_pages,
    create_redirect_stubs,
    create_tag_indexes,
    outline_upload_documents,
    validate_local_links,
)


def build_outline_test_tree():
    xml_text = f"""<?xml version="1.0" encoding="utf-8"?>
<mediawiki xmlns="{convert.NS}">
  <siteinfo>
    <base>https://example.com/wiki/Main_Page</base>
  </siteinfo>
  <page>
    <title>Aragorn</title>
    <revision>
      <timestamp>2024-01-02T03:04:05Z</timestamp>
      <contributor><username>Elessar</username></contributor>
      <text xml:space="preserve">[[Category:Characters]][[Category:Fellowship]]
Aragorn carries [[Anduril]].</text>
    </revision>
  </page>
  <page>
    <title>Anduril</title>
    <revision>
      <timestamp>2024-01-03T03:04:05Z</timestamp>
      <contributor><username>Elrond</username></contributor>
      <text xml:space="preserve">[[Category:Artifacts]]
Sword of kings.</text>
    </revision>
  </page>
  <page>
    <title>Strider</title>
    <redirect title="Aragorn" />
    <revision>
      <timestamp>2024-01-04T03:04:05Z</timestamp>
      <text xml:space="preserve">#REDIRECT [[Aragorn]]</text>
    </revision>
  </page>
</mediawiki>
"""
    return ET.ElementTree(ET.fromstring(xml_text))

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

def test_fix_image_links_outline_relative_to_category_page():
    md = "Some text ![[images/photo.jpg]] more text"
    result = fix_image_links(
        md,
        output_format="outline",
        current_page_path="characters/Aragorn.md",
    )
    assert "![photo.jpg](../images/photo.jpg)" in result

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


def test_clean_wikilink_outline_uses_planned_relative_paths(monkeypatch):
    convert.reset_runtime_state()
    monkeypatch.setitem(convert.page_output_paths, "One Ring", "items/One_Ring.md")

    result = clean_wikilink(
        "One_Ring",
        output_format="outline",
        current_page_path="characters/Aragorn.md",
    )

    assert result == "[One Ring](../items/One_Ring.md)"


def test_plan_and_convert_outline_generates_secondary_indexes_redirects_and_metadata(tmp_path, monkeypatch):
    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "OUTPUT_FORMAT", "outline")
    monkeypatch.setattr(convert, "SKIP_REDIRECTS", False)
    monkeypatch.setattr(convert, "WIKI_DOMAIN", None)
    monkeypatch.setattr(convert, "WIKI_BASE_URL", None)
    monkeypatch.setattr(convert, "convert_with_pandoc", lambda text, title="", output_format=None: text)

    tree = build_outline_test_tree()

    extract_wiki_domain(tree)
    plan_pages(tree)
    convert_pages(tree)
    create_redirect_stubs()
    create_tag_indexes()

    aragorn_path = tmp_path / "characters" / "Aragorn.md"
    anduril_path = tmp_path / "artifacts" / "Anduril.md"
    redirect_path = tmp_path / "characters" / "Strider.md"
    fellowship_index = tmp_path / "fellowship" / "index.md"

    assert aragorn_path.exists()
    assert anduril_path.exists()
    assert redirect_path.exists()
    assert fellowship_index.exists()

    aragorn_content = aragorn_path.read_text(encoding="utf-8")
    redirect_content = redirect_path.read_text(encoding="utf-8")
    fellowship_content = fellowship_index.read_text(encoding="utf-8")

    assert "[Anduril](../artifacts/Anduril.md)" in aragorn_content
    assert "Source Last Modified" in aragorn_content
    assert "2024-01-02T03:04:05Z" in aragorn_content
    assert "Source Last Editor" in aragorn_content
    assert "Elessar" in aragorn_content
    assert "Source Url" in aragorn_content
    assert "https://example.com/wiki/Aragorn" in aragorn_content

    assert "Redirects to [Aragorn](./Aragorn.md)." in redirect_content
    assert "[Aragorn](../characters/Aragorn.md)" in fellowship_content
    assert validate_local_links() == []


def test_plan_pages_handles_filename_collisions_for_links(monkeypatch):
    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_FORMAT", "outline")
    monkeypatch.setitem(convert.page_output_paths, "Alpha/Beta", "items/Alpha_Beta.md")
    monkeypatch.setitem(convert.page_output_paths, "Alpha:Beta", "items/Alpha_Beta_1.md")

    first = clean_wikilink(
        "Alpha/Beta",
        output_format="outline",
        current_page_path="items/Reference.md",
    )
    second = clean_wikilink(
        "Alpha:Beta",
        output_format="outline",
        current_page_path="items/Reference.md",
    )

    assert first == "[Alpha/Beta](./Alpha_Beta.md)"
    assert second == "[Alpha:Beta](./Alpha_Beta_1.md)"


def test_clean_wikilink_outline_slugifies_anchor(monkeypatch):
    convert.reset_runtime_state()
    monkeypatch.setitem(convert.page_output_paths, "One Ring", "items/One_Ring.md")

    result = clean_wikilink(
        "One_Ring#The_One_Ring?|The One Ring",
        output_format="outline",
        current_page_path="characters/Aragorn.md",
    )

    assert result == "[The One Ring](../items/One_Ring.md#the-one-ring)"


def test_extract_source_metadata_redacts_anonymous_ip():
    revision = ET.fromstring(f"""
    <revision xmlns="{convert.NS}">
      <timestamp>2024-01-02T03:04:05Z</timestamp>
      <contributor><ip>203.0.113.4</ip></contributor>
    </revision>
    """)

    metadata = convert.extract_source_metadata("Aragorn", revision)

    assert metadata["source_last_editor"] == "Anonymous"


def test_resolve_outline_api_key_prefers_file_then_env(tmp_path, monkeypatch):
    key_file = tmp_path / "outline-api-key.txt"
    key_file.write_text("file-secret\n", encoding="utf-8")
    monkeypatch.setenv("OUTLINE_API_KEY", "env-secret")

    class Args:
        def __init__(self, outline_api_key_file):
            self.outline_api_key_file = outline_api_key_file

    file_value = convert.resolve_outline_api_key(Args(str(key_file)))
    env_value = convert.resolve_outline_api_key(Args(None))

    assert file_value == "file-secret"
    assert env_value == "env-secret"


def test_outline_upload_documents_rewrites_nested_image_links_and_updates_existing_doc(
    tmp_path, monkeypatch
):
    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "OUTLINE_URL", "https://wiki.example.com")
    monkeypatch.setattr(convert, "OUTLINE_API_KEY", "secret")
    monkeypatch.setattr(convert, "COLLECTION_ID", None)

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "photo.jpg").write_bytes(b"image")

    characters_dir = tmp_path / "characters"
    characters_dir.mkdir()
    (characters_dir / "Aragorn.md").write_text(
        "# Aragorn\n\n![photo.jpg](../images/photo.jpg)\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        convert,
        "outline_upload_image",
        lambda filepath: f"https://cdn.example.com/{os.path.basename(filepath)}",
    )
    monkeypatch.setattr(
        convert,
        "outline_get_or_create_collection",
        lambda name: "default-col" if name == "Imported Wiki" else "characters-col",
    )

    calls = []

    def fake_outline_api_request(endpoint, data=None, files=None):
        calls.append((endpoint, data, files))
        if endpoint == "documents.search":
            return {
                "data": [
                    {"id": "doc-1", "title": "Aragorn", "collectionId": "characters-col"}
                ]
            }
        if endpoint == "documents.update":
            return {"data": {"id": "doc-1"}}
        if endpoint == "documents.create":
            pytest.fail("documents.create should not be called when an existing document is found")
        return None

    monkeypatch.setattr(convert, "outline_api_request", fake_outline_api_request)

    outline_upload_documents()

    search_calls = [call for call in calls if call[0] == "documents.search"]
    update_calls = [call for call in calls if call[0] == "documents.update"]

    assert len(search_calls) == 1
    assert len(update_calls) == 1
    assert update_calls[0][1]["text"].count("https://cdn.example.com/photo.jpg") == 1


# ---------------------------------------------------------------------------
# images archive tests
# ---------------------------------------------------------------------------

def test_download_image_from_archive_extracts_file(tmp_path, monkeypatch):
    """Images found in the archive are extracted to the output images dir."""
    import io
    import tarfile as _tarfile

    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # minimal fake PNG bytes

    # Build an in-memory tar.gz with a hashed path (as MediaWiki uses).
    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = _tarfile.TarInfo(name="images/a/ab/photo.png")
        info.size = len(image_data)
        tf.addfile(info, io.BytesIO(image_data))
    archive_path = tmp_path / "images.tar.gz"
    archive_path.write_bytes(buf.getvalue())

    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "IMAGES_ARCHIVE", str(archive_path))

    result = convert.download_image("photo.png")

    assert result == "photo.png"
    extracted = tmp_path / "images" / "photo.png"
    assert extracted.exists()
    assert extracted.read_bytes() == image_data


def test_download_image_archive_missing_image_returns_none(tmp_path, monkeypatch):
    """When the archive does not contain the requested image, return None."""
    import io
    import tarfile as _tarfile

    dummy_data = b"\x00" * 4
    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = _tarfile.TarInfo(name="images/a/ab/other.png")
        info.size = len(dummy_data)
        tf.addfile(info, io.BytesIO(dummy_data))
    archive_path = tmp_path / "images.tar.gz"
    archive_path.write_bytes(buf.getvalue())

    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "IMAGES_ARCHIVE", str(archive_path))

    result = convert.download_image("missing.png")

    assert result is None
    assert not (tmp_path / "images" / "missing.png").exists()


def test_download_image_skips_archive_when_not_set(tmp_path, monkeypatch):
    """When no archive is configured, the code falls back to network download."""
    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "IMAGES_ARCHIVE", None)

    network_called = []

    def fake_get_image_url(domain, filename):
        network_called.append(filename)
        return None  # Simulate no URL found.

    monkeypatch.setattr(convert, "get_image_url", fake_get_image_url)
    monkeypatch.setattr(convert, "WIKI_DOMAIN", "example.com")

    result = convert.download_image("photo.png")

    assert result is None
    assert network_called  # Confirm network path was attempted.


def test_download_image_archive_space_underscore_normalization(tmp_path, monkeypatch):
    """MediaWiki stores 'My Image.png' as 'My_Image.png'; the archive lookup must match."""
    import io
    import tarfile as _tarfile

    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # minimal fake PNG bytes

    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = _tarfile.TarInfo(name="images/a/ab/My_Image.png")
        info.size = len(image_data)
        tf.addfile(info, io.BytesIO(image_data))
    archive_path = tmp_path / "images.tar.gz"
    archive_path.write_bytes(buf.getvalue())

    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "IMAGES_ARCHIVE", str(archive_path))

    # The wikilink title uses a space; MediaWiki stored the file with an underscore.
    result = convert.download_image("My Image.png")

    assert result == "My Image.png"
    extracted = tmp_path / "images" / "My Image.png"
    assert extracted.exists()
    assert extracted.read_bytes() == image_data


def test_download_image_corrupt_archive_returns_none_no_network_fallback(tmp_path, monkeypatch):
    """A corrupt archive must return None and must NOT fall back to network downloads."""
    archive_path = tmp_path / "bad.tar.gz"
    archive_path.write_bytes(b"not a tar file at all")

    convert.reset_runtime_state()
    monkeypatch.setattr(convert, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(convert, "IMAGES_ARCHIVE", str(archive_path))

    network_called = []
    monkeypatch.setattr(convert, "get_image_url", lambda *a: network_called.append(a) or None)

    result = convert.download_image("photo.png")

    assert result is None
    assert not network_called  # Archive is authoritative; network must not be tried.
