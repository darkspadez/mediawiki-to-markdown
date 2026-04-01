import os
import re
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from collections import defaultdict
import mwparserfromhell
import sys
import json
import requests
import yaml
import argparse
import inflect
import logging
from urllib.parse import quote as url_quote, unquote as url_unquote
from tqdm import tqdm

p = inflect.engine()

# Constants
NS = "http://www.mediawiki.org/xml/export-0.11/"
IMAGE_DIR = "images"

# Pre-compiled regex patterns
INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')
HEADING_ID_REGEX = re.compile(r'^(#{1,6} .+?)\s*\{\#.*?\}', re.MULTILINE)
WIKILINK_REGEX = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
PANDOC_LINK_REGEX = re.compile(
    r'\[([^\]]+)\]\(((?:[^\(\)]+|\([^\)]*\))+)(?:\s+"wikilink")?\)'
)
# HTML artifact patterns for outline mode
HTML_BR_REGEX = re.compile(r'<br\s*/?>', re.IGNORECASE)
HTML_SUP_REGEX = re.compile(r'<sup>(.*?)</sup>', re.IGNORECASE | re.DOTALL)
HTML_SUB_REGEX = re.compile(r'<sub>(.*?)</sub>', re.IGNORECASE | re.DOTALL)
HTML_TAG_REGEX = re.compile(r'</?[a-zA-Z][^>]*>')
# Footnote patterns
FOOTNOTE_REF_REGEX = re.compile(r'\[\^(\w+)\](?!:)')
FOOTNOTE_DEF_REGEX = re.compile(r'^\[\^(\w+)\]:\s*(.+)$', re.MULTILINE)
# Obsidian image embed pattern (escaped or not)
OBSIDIAN_IMAGE_EMBED_REGEX = re.compile(r'\\?!\[\[([^\]]+)\]\]')
# Local markdown link target pattern
MARKDOWN_LINK_TARGET_REGEX = re.compile(r'!?\[[^\]]*\]\(([^)]+)\)')
MAX_BROKEN_LINK_WARNINGS = 10
# Image content type mapping
IMAGE_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "png": "image/png", "svg": "image/svg+xml", "webp": "image/webp",
}

def TAG(t):
    return f"{{{NS}}}{t}"

def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert MediaWiki XML to Markdown (Obsidian or Outline)"
    )
    parser.add_argument("input_xml", help="Input XML file")
    parser.add_argument("output_dir", nargs="?", default=None,
                        help="Output directory (default: obsidian_vault or outline_output)")
    parser.add_argument("--output-format", choices=["obsidian", "outline"],
                        default="obsidian",
                        help="Output format: 'obsidian' (default) or 'outline'")
    parser.add_argument("--skip-redirects", action="store_true",
                        help="Skip redirect pages")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose logging")
    # Outline API options
    parser.add_argument("--outline-url",
                        help="Outline instance URL (e.g. https://wiki.example.com)")
    parser.add_argument("--outline-api-key-file",
                        help="Path to a file containing the Outline API key")
    parser.add_argument("--collection-id",
                        help="Outline collection ID to import documents into")
    return parser.parse_args()

args = parse_args()

logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)


def resolve_outline_api_key(parsed_args):
    if parsed_args.outline_api_key_file:
        try:
            with open(parsed_args.outline_api_key_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            logging.error(f"❌ Failed to read Outline API key file: {e}")
            return None
    return os.environ.get("OUTLINE_API_KEY")

INPUT_XML = args.input_xml
OUTPUT_FORMAT = args.output_format
OUTPUT_DIR = args.output_dir or ("outline_output" if OUTPUT_FORMAT == "outline" else "obsidian_vault")
SKIP_REDIRECTS = args.skip_redirects
OUTLINE_URL = args.outline_url
OUTLINE_API_KEY = resolve_outline_api_key(args)
COLLECTION_ID = args.collection_id

os.makedirs(OUTPUT_DIR, exist_ok=True)

tag_to_pages = defaultdict(list)
filename_counts = defaultdict(int)
# Mapping from category -> list of (title, filename) for outline collection organization
category_to_pages = defaultdict(list)

WIKI_DOMAIN = None
WIKI_BASE_URL = None
# Planned export metadata keyed by normalized page title.
page_output_paths = {}
# Collected normalized tags for each non-redirect page.
page_tags = {}
# Preserved source metadata for each non-redirect page.
page_source_metadata = {}
# Redirect source title -> canonical target title.
redirect_targets = {}
# Redirect source title -> generated stub output path.
redirect_output_paths = {}
# All reserved relative output paths, used to avoid filename collisions.
planned_output_paths = set()


def reset_runtime_state():
    tag_to_pages.clear()
    filename_counts.clear()
    category_to_pages.clear()
    page_output_paths.clear()
    page_tags.clear()
    page_source_metadata.clear()
    redirect_targets.clear()
    redirect_output_paths.clear()
    planned_output_paths.clear()


def normalize_page_title(title):
    return title.replace('_', ' ').strip()


def quote_path(path):
    return "/".join(url_quote(part) for part in path.split("/"))


def format_relative_link(path):
    path = path.replace(os.sep, '/')
    if not path.startswith(('./', '../', '/')):
        path = f"./{path}"
    return quote_path(path)


def build_relative_output_link(target_relpath, current_page_path=None):
    if current_page_path:
        current_dir = os.path.dirname(current_page_path) or "."
        relpath = os.path.relpath(target_relpath, start=current_dir)
    else:
        relpath = target_relpath
    return format_relative_link(relpath)


def allocate_output_path(base_name, subdir=""):
    suffix = 0
    while True:
        filename = f"{base_name}{'_' + str(suffix) if suffix else ''}.md"
        relpath = os.path.join(subdir, filename) if subdir else filename
        relpath = relpath.replace(os.sep, '/')
        if relpath not in planned_output_paths:
            planned_output_paths.add(relpath)
            return relpath
        suffix += 1


def build_asset_embed(image_name, local_filename, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    image_relpath = os.path.join(IMAGE_DIR, local_filename).replace(os.sep, '/')
    if fmt == "outline":
        link = build_relative_output_link(image_relpath, current_page_path=current_page_path)
        return f"![{image_name}]({link})"
    return f"![[{IMAGE_DIR}/{local_filename}]]"


def resolve_page_link(target, current_page_path=None, output_format=None):
    fmt = output_format or OUTPUT_FORMAT
    if fmt != "outline":
        return None

    page_target, _, anchor = target.partition('#')
    normalized_target = normalize_page_title(page_target)
    normalized_target = redirect_targets.get(normalized_target, normalized_target)
    target_relpath = page_output_paths.get(normalized_target)

    if target_relpath:
        link = build_relative_output_link(target_relpath, current_page_path=current_page_path)
    else:
        fallback_name = f"{clean_filename(page_target)}.md"
        link = format_relative_link(fallback_name)

    if anchor:
        normalized_anchor = slugify_heading_fragment(anchor)
        if normalized_anchor:
            return f"{link}#{url_quote(normalized_anchor)}"
    return link


def infer_infobox_tag(tags, infobox_data):
    updated_tags = list(tags)
    if infobox_data.get('infobox'):
        infobox_name = str(infobox_data['infobox'])

        if not p.singular_noun(infobox_name):
            infobox_name = p.plural(infobox_name)

        inferred_tag = normalize_tag(infobox_name)

        if inferred_tag not in updated_tags:
            updated_tags.append(inferred_tag)

    return updated_tags


def build_source_url(title):
    if not WIKI_BASE_URL:
        return None
    base_prefix = WIKI_BASE_URL.rstrip('/').rsplit('/', 1)[0]
    return f"{base_prefix}/{url_quote(title.replace(' ', '_'))}"


def extract_source_metadata(title, revision):
    metadata = {}

    timestamp_elem = revision.find(TAG("timestamp"))
    if timestamp_elem is not None and timestamp_elem.text:
        metadata["source_last_modified"] = timestamp_elem.text.strip()

    contributor = revision.find(TAG("contributor"))
    if contributor is not None:
        username = contributor.find(TAG("username"))
        ip_addr = contributor.find(TAG("ip"))
        if username is not None and username.text:
            metadata["source_last_editor"] = username.text.strip()
        elif ip_addr is not None and ip_addr.text:
            metadata["source_last_editor"] = "Anonymous"

    source_url = build_source_url(title)
    if source_url:
        metadata["source_url"] = source_url

    return metadata

def extract_wiki_domain(tree):
    global WIKI_DOMAIN, WIKI_BASE_URL
    ns = {"ns": NS}
    base_elem = tree.find(".//ns:siteinfo/ns:base", ns)
    if base_elem is not None and base_elem.text:
        base_url = base_elem.text.strip()
        WIKI_BASE_URL = base_url
        match = re.match(r"https?://([^/]+)/", base_url)
        if match:
            WIKI_DOMAIN = match.group(1)
            return
    raise ValueError("Could not extract wiki domain from <base> tag.")

def clean_filename(title):
    """Convert to safe filename with underscores"""
    return INVALID_FILENAME_CHARS.sub('_', title.strip())

def normalize_tag(tag):
    return tag.replace(" ", "_").lower()

def display_title(title):
    """Convert to human-readable title with spaces"""
    return title.replace('_', ' ')


def slugify_heading_fragment(fragment):
    fragment = url_unquote(unescape(fragment or ""))
    fragment = fragment.replace('_', ' ')
    fragment = re.sub(r'[^\w\s-]', '', fragment, flags=re.UNICODE).strip().lower()
    return re.sub(r'[-\s]+', '-', fragment)


def clean_wikilink(link_content, output_format=None, current_page_path=None):
    """Centralized wikilink cleaning.
    In obsidian mode: [[Target|Alias]] or [[Target]]
    In outline mode: [Alias](Target.md) or [Target](Target.md)
    """
    fmt = output_format or OUTPUT_FORMAT
    if '|' in link_content:
        target, alias = link_content.split('|', 1)
        clean_target = target.replace('_', ' ')
        if fmt == "outline":
            link = resolve_page_link(target, current_page_path=current_page_path, output_format=fmt)
            return f"[{alias}]({link})"
        return f"[[{clean_target}|{alias}]]"
    clean = link_content.replace('_', ' ')
    if fmt == "outline":
        link = resolve_page_link(link_content, current_page_path=current_page_path, output_format=fmt)
        return f"[{clean}]({link})"
    return f"[[{clean}]]"

def fix_wikilink_spacing(text, output_format=None, current_page_path=None):
    """Convert underscores to spaces in wikilinks using centralized cleaner"""
    fmt = output_format or OUTPUT_FORMAT
    return WIKILINK_REGEX.sub(
        lambda m: clean_wikilink(
            m.group(1),
            output_format=fmt,
            current_page_path=current_page_path,
        ),
        text
    )

def extract_categories(wikicode):
    categories = []
    for link in wikicode.ifilter_wikilinks():
        target = link.title.strip()
        if target.lower().startswith("category:"):
            cat = target[len("category:"):].strip()
            categories.append(normalize_tag(cat))
            wikicode.remove(link)
    return wikicode, categories

def extract_images(wikicode, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    images = set()
    nodes = list(wikicode.nodes)  # make a list copy because we'll modify

    for i, node in enumerate(nodes):
        if isinstance(node, mwparserfromhell.wikicode.Wikilink):
            target = node.title.strip()
            if target.lower().startswith(("file:", "image:")):
                image_name = target.split(":", 1)[1].strip()
                local_filename = download_image(image_name)

                if local_filename:
                    embed_link = build_asset_embed(
                        image_name,
                        local_filename,
                        output_format=fmt,
                        current_page_path=current_page_path,
                    )

                    # Replace the wikilink node in wikicode directly
                    wikicode.replace(node, embed_link)

                    images.add(embed_link)
    return wikicode

def get_image_url(wiki_domain, filename):
    url = f"https://{wiki_domain}/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": filename,
        "iiprop": "url"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            ii = page.get("imageinfo")
            if ii:
                return ii[0]["url"]
    except Exception as e:
        logging.error(f"❌ Failed to get image URL for {filename}: {e}")
    return None

def download_image(image_name):
    if not image_name:
        return None

    safe_name = clean_filename(image_name)
    filepath = os.path.join(OUTPUT_DIR, IMAGE_DIR, safe_name)
    if os.path.exists(filepath):
        logging.debug(f"🖼️ Skipping download (already exists): {safe_name}")
        return safe_name

    url = get_image_url(WIKI_DOMAIN, f"File:{image_name}")
    if not url:
        logging.warning(f"❌ Could not find URL for image: {image_name}")
        return None

    try:
        resp = requests.get(url, stream=True)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logging.debug(f"📥 Downloaded image: {safe_name}")
            return safe_name
        else:
            logging.error(f"❌ Failed to download image: {image_name} ({resp.status_code})")
            return None
    except Exception as e:
        logging.error(f"❌ Error downloading {image_name}: {e}")
        return None

def get_infobox_data(wikicode):
    """Return the first template node in the wikicode and its normalized data.

    Returns a `(template, data)` tuple where `template` is the first
    mwparserfromhell template node encountered in the page source or `None`,
    and `data` is a plain dict of extracted infobox fields.
    """
    infobox_data = {}
    infobox_template = None
    for template in wikicode.filter_templates():
        if template.name.strip():
            infobox_template = template
            break

    if not infobox_template:
        return None, {}

    raw_name = infobox_template.name.strip().lower()
    if raw_name.startswith("infobox_"):
        infobox_type = raw_name[len("infobox_"):].replace(' ', '_').title()
    else:
        infobox_type = infobox_template.name

    infobox_data['infobox'] = infobox_type

    for param in infobox_template.params:
        key = param.name.strip().replace(":", "").lower()
        val = param.value.strip()

        wikilinks = WIKILINK_REGEX.findall(val)
        if wikilinks:
            parts = []
            remaining = val
            for link in wikilinks:
                before, link_part, remaining = remaining.partition(f"[[{link}]]")
                if before.strip():
                    parts.append(before.strip())
                parts.append(f"[[{link}]]")
            if remaining.strip():
                parts.append(remaining.strip())
            infobox_data[key] = parts
        else:
            infobox_data[key] = val

    return infobox_template, infobox_data


def extract_infobox(wikicode, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    infobox_template, infobox_data = get_infobox_data(wikicode)

    if not infobox_template:
        return wikicode, {}

    wikicode.remove(infobox_template)

    # Extract the image from the infobox and inline it at top of markdown
    if image_name := infobox_data.get('image'):
        image_name = image_name.strip()
        local_filename = download_image(image_name)
        if local_filename:
            embed = build_asset_embed(
                image_name,
                local_filename,
                output_format=fmt,
                current_page_path=current_page_path,
            )
            wikicode.insert(0, f"{embed}\n\n")

    return wikicode, infobox_data

def sanitize_for_yaml(obj):
    if isinstance(obj, dict):
        return {sanitize_for_yaml(k): sanitize_for_yaml(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_yaml(i) for i in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)

def extract_yaml_header(title, tags, extra_fields=None, output_format=None):
    fmt = output_format or OUTPUT_FORMAT
    if fmt == "outline":
        return _extract_outline_header(title, tags, extra_fields)
    header = {
        'title': display_title(title),
        'tags': tags
    }
    if extra_fields:
        header.update(sanitize_for_yaml(extra_fields))

    return f"---\n{yaml.safe_dump(header, sort_keys=False)}---\n"


def _extract_outline_header(title, tags, extra_fields=None):
    """Generate an Outline-compatible document header.
    Uses an H1 title and an optional metadata info block.
    """
    lines = [f"# {display_title(title)}", ""]

    # Build metadata items
    meta_items = []
    if tags:
        meta_items.append(("Tags", ", ".join(f"`{t}`" for t in tags)))
    if extra_fields:
        sanitized = sanitize_for_yaml(extra_fields)
        for key, val in sanitized.items():
            if key in ('title', 'tags', 'infobox', 'image'):
                continue
            if isinstance(val, list):
                display_val = ", ".join(str(v) for v in val)
            else:
                display_val = str(val)
            if display_val:
                meta_items.append((key.replace('_', ' ').title(), display_val))

    if meta_items:
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for field, value in meta_items:
            # Escape pipes in values
            safe_value = value.replace("|", "\\|")
            lines.append(f"| **{field}** | {safe_value} |")
        lines.append("")

    return "\n".join(lines) + "\n"

def clean_heading_ids(md_text):
    return HEADING_ID_REGEX.sub(r'\1', md_text)

def extract_links_from_pandoc(md_text, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    def replacer(match):
        text = match.group(1).strip()
        target = match.group(2).replace(' "wikilink"', '').strip()

        if target.startswith(('http://', 'https://', 'mailto:')):
            return match.group(0)

        clean_target = display_title(target)

        if fmt == "outline":
            link = resolve_page_link(target, current_page_path=current_page_path, output_format=fmt)
            return f"[{text}]({link})"

        # Only include alias if it's actually different
        if text == clean_target:
            return f"[[{clean_target}]]"
        else:
            return f"[[{clean_target}|{text}]]"
    return PANDOC_LINK_REGEX.sub(replacer, md_text)

def clean_residual_wikilink_artifacts(md_text):
    return md_text.replace(' "wikilink"', '')

def fix_image_links(md, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    if fmt == "outline":
        # Convert any remaining Obsidian-style image embeds to standard markdown
        def _replace_obsidian_embed(m):
            path = m.group(1)
            name = path.split("/")[-1] if "/" in path else path
            link = build_relative_output_link(path, current_page_path=current_page_path)
            return f"![{name}]({link})"
        return OBSIDIAN_IMAGE_EMBED_REGEX.sub(_replace_obsidian_embed, md)
    return re.sub(r'\\(!\[\[)', r'\1', md)


def strip_html_artifacts(md_text):
    """Strip or convert HTML artifacts that Outline cannot render.
    - <br> → double newline
    - <sup>text</sup> → $^{text}$ (LaTeX)
    - <sub>text</sub> → $_{text}$ (LaTeX)
    - Remaining HTML tags → stripped
    """
    md_text = HTML_BR_REGEX.sub('\n\n', md_text)
    md_text = HTML_SUP_REGEX.sub(r'$^{\1}$', md_text)
    md_text = HTML_SUB_REGEX.sub(r'$_{\1}$', md_text)
    md_text = HTML_TAG_REGEX.sub('', md_text)
    return md_text


def convert_footnotes(md_text):
    """Convert markdown footnotes to inline parenthetical references
    and a References section at the bottom. Outline does not support footnotes.
    """
    # Collect footnote definitions
    definitions = {}
    for match in FOOTNOTE_DEF_REGEX.finditer(md_text):
        definitions[match.group(1)] = match.group(2).strip()

    if not definitions:
        return md_text

    # Remove footnote definition lines
    md_text = FOOTNOTE_DEF_REGEX.sub('', md_text)

    # Replace footnote references with numbered superscripts linking to references
    counter = [0]
    ref_map = {}

    def _replace_ref(match):
        key = match.group(1)
        if key not in ref_map:
            counter[0] += 1
            ref_map[key] = counter[0]
        num = ref_map[key]
        return f'$^{{{num}}}$'

    md_text = FOOTNOTE_REF_REGEX.sub(_replace_ref, md_text)

    # Append references section
    if ref_map:
        md_text = md_text.rstrip() + "\n\n---\n\n**References**\n\n"
        for key, num in sorted(ref_map.items(), key=lambda x: x[1]):
            text = definitions.get(key, "")
            md_text += f"{num}. {text}\n"

    return md_text


def convert_definition_lists(md_text):
    """Convert definition list syntax to bold-term + indented description.
    Pandoc may output definition lists as:
      Term
      :   Definition
    Convert to:
      **Term**
        Definition
    """
    lines = md_text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if next line is a definition (starts with `:   `)
        if (i + 1 < len(lines) and
                re.match(r'^:\s{3,}', lines[i + 1]) and
                line.strip() and
                not line.startswith('#') and
                not line.startswith('|') and
                not line.startswith('-') and
                not line.startswith('>')):
            # This line is a term
            result.append(f"**{line.strip()}**")
            i += 1
            # Collect all following definition lines
            while i < len(lines) and re.match(r'^:\s{3,}', lines[i]):
                defn = re.sub(r'^:\s{3,}', '', lines[i])
                result.append(f"  {defn}")
                i += 1
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)

def cleanup_markdown(md, output_format=None, current_page_path=None):
    fmt = output_format or OUTPUT_FORMAT
    md = clean_heading_ids(md)
    md = extract_links_from_pandoc(md, output_format=fmt, current_page_path=current_page_path)
    md = clean_residual_wikilink_artifacts(md)
    md = fix_wikilink_spacing(md, output_format=fmt, current_page_path=current_page_path)
    md = fix_image_links(md, output_format=fmt, current_page_path=current_page_path)
    if fmt == "outline":
        md = strip_html_artifacts(md)
        md = convert_footnotes(md)
        md = convert_definition_lists(md)
    return md

def convert_with_pandoc(text, title="", output_format=None):
    fmt = output_format or OUTPUT_FORMAT
    if fmt == "outline":
        pandoc_to = 'markdown_strict+pipe_tables+backtick_code_blocks+fenced_code_blocks+strikeout+task_lists'
    else:
        pandoc_to = 'markdown'
    try:
        result = subprocess.run(
            ['pandoc', '--from=mediawiki', f'--to={pandoc_to}', '--wrap=none'],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        md = result.stdout.decode("utf-8")
        md = md.replace("\\'", "'")
        return md
    except subprocess.CalledProcessError as e:
        logging.warning(f"⚠️ Pandoc failed for '{title}'. Using raw text.")
        logging.debug(e.stderr.decode())
        return text

def clean_and_convert_text(raw_text, title, output_format=None):
    return clean_and_convert_text_with_metadata(raw_text, title, output_format=output_format)


def collect_page_tags(raw_text):
    text = unescape(raw_text)
    wikicode = mwparserfromhell.parse(text)
    wikicode, tags = extract_categories(wikicode)
    _infobox_template, infobox_data = get_infobox_data(wikicode)
    return infer_infobox_tag(tags, infobox_data)


def clean_and_convert_text_with_metadata(
    raw_text,
    title,
    output_format=None,
    current_page_path=None,
    extra_fields=None,
):
    fmt = output_format or OUTPUT_FORMAT
    text = unescape(raw_text)
    wikicode = mwparserfromhell.parse(text)
    wikicode, tags = extract_categories(wikicode)
    wikicode = extract_images(
        wikicode,
        output_format=fmt,
        current_page_path=current_page_path,
    )
    wikicode, infobox_data = extract_infobox(
        wikicode,
        output_format=fmt,
        current_page_path=current_page_path,
    )

    tags = infer_infobox_tag(tags, infobox_data)

    cleaned_text = str(wikicode).strip()
    merged_fields = dict(infobox_data)
    if extra_fields:
        merged_fields.update(extra_fields)
    header = extract_yaml_header(title, tags, merged_fields, output_format=fmt)

    return header, cleaned_text, tags


def plan_pages(tree):
    ns = {"ns": NS}

    for page in tree.findall(".//ns:page", ns):
        title_elem = page.find("ns:title", ns)
        if title_elem is None or not title_elem.text:
            continue

        title = title_elem.text.strip()
        normalized_title = normalize_page_title(title)
        redirect_elem = page.find("ns:redirect", ns)

        if redirect_elem is not None:
            redirect_target = redirect_elem.attrib.get("title", "").strip()
            if redirect_target:
                redirect_targets[normalized_title] = normalize_page_title(redirect_target)
            continue

        revision = page.find(TAG("revision"))
        if revision is None:
            continue

        text_elem = revision.find(TAG("text"))
        if text_elem is None or not text_elem.text or not text_elem.text.strip():
            continue

        tags = collect_page_tags(text_elem.text)
        page_tags[normalized_title] = tags
        page_source_metadata[normalized_title] = extract_source_metadata(title, revision)

        for tag in tags:
            tag_to_pages[tag].append(title)

        subdir = ""
        if OUTPUT_FORMAT == "outline" and tags:
            subdir = clean_filename(tags[0])

        page_output_paths[normalized_title] = allocate_output_path(clean_filename(title), subdir=subdir)

    if SKIP_REDIRECTS:
        return

    for redirect_title, target_title in redirect_targets.items():
        target_path = page_output_paths.get(target_title, "")
        subdir = os.path.dirname(target_path)
        redirect_output_paths[redirect_title] = allocate_output_path(
            clean_filename(redirect_title),
            subdir=subdir,
        )


def convert_pages(tree):
    ns = {"ns": NS}
    total_pages = len(tree.findall(".//ns:page", {"ns": NS}))

    disable_tqdm = logging.getLogger().level <= logging.DEBUG

    with tqdm(total=total_pages, desc="Converting pages", disable=disable_tqdm) as pbar:
        for page in tree.findall(".//ns:page", ns):
            title_elem = page.find("ns:title", ns)
            if title_elem is None or not title_elem.text:
                pbar.update(1)
                continue

            if SKIP_REDIRECTS and (page.find("ns:redirect", ns) is not None):
                logging.debug(f"⏭️ Skipping redirect: {title_elem.text.strip()}")
                pbar.update(1)
                continue

            if page.find("ns:redirect", ns) is not None:
                pbar.update(1)
                continue

            title = title_elem.text.strip()
            normalized_title = normalize_page_title(title)
            logging.debug(f"✅ Found page: {title}")

            revision = page.find(TAG("revision"))
            if revision is None:
                logging.warning(f"⚠️ No revision for: {title}")
                pbar.update(1)
                continue

            text_elem = revision.find(TAG("text"))
            if text_elem is None or not text_elem.text or not text_elem.text.strip():
                logging.warning(f"⚠️ No content in: {title}")
                pbar.update(1)
                continue

            raw_text = text_elem.text
            current_page_path = page_output_paths.get(normalized_title)
            if not current_page_path:
                logging.warning(f"⚠️ No planned output path for: {title}")
                pbar.update(1)
                continue

            header_str, wikitext, _tags = clean_and_convert_text_with_metadata(
                raw_text,
                title,
                output_format=OUTPUT_FORMAT,
                current_page_path=current_page_path,
                extra_fields=page_source_metadata.get(normalized_title),
            )
            wikitext = convert_with_pandoc(wikitext, title)
            wikitext = cleanup_markdown(
                wikitext,
                output_format=OUTPUT_FORMAT,
                current_page_path=current_page_path,
            )
            markdown = f"{header_str}\n{wikitext.strip()}\n"
            filepath = os.path.join(OUTPUT_DIR, current_page_path)
            os.makedirs(os.path.dirname(filepath) or OUTPUT_DIR, exist_ok=True)

            with open(filepath, "w", encoding="utf-8") as f:
                logging.debug(f"✍️ Writing: {filepath}")
                f.write(markdown)

            pbar.update(1)

    logging.info("✅ Main articles converted")


def create_redirect_stubs():
    if SKIP_REDIRECTS:
        return

    for redirect_title, target_title in redirect_targets.items():
        target_relpath = page_output_paths.get(target_title)
        redirect_relpath = redirect_output_paths.get(redirect_title)
        if not target_relpath or not redirect_relpath:
            continue

        redirect_display = display_title(redirect_title)
        target_display = display_title(target_title)

        if OUTPUT_FORMAT == "outline":
            link = resolve_page_link(
                target_title,
                current_page_path=redirect_relpath,
                output_format=OUTPUT_FORMAT,
            )
            extra_fields = {"redirect_target": target_display}
            source_url = build_source_url(redirect_title)
            if source_url:
                extra_fields["source_url"] = source_url
            content = (
                extract_yaml_header(
                    redirect_display,
                    [],
                    extra_fields,
                    output_format=OUTPUT_FORMAT,
                )
                + f"\nRedirects to [{target_display}]({link}).\n"
            )
        else:
            content = (
                extract_yaml_header(
                    redirect_display,
                    [],
                    {"redirect_target": target_display},
                    output_format=OUTPUT_FORMAT,
                )
                + f"\nRedirects to [[{target_display}]].\n"
            )

        filepath = os.path.join(OUTPUT_DIR, redirect_relpath)
        os.makedirs(os.path.dirname(filepath) or OUTPUT_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    if redirect_output_paths:
        logging.info("↪️ Redirect stubs created")

def create_tag_indexes():
    if OUTPUT_FORMAT == "outline":
        _create_outline_collection_indexes()
        return
    index_dir = os.path.join(OUTPUT_DIR, "_indexes")
    os.makedirs(index_dir, exist_ok=True)
    for tag, pages in tag_to_pages.items():
        display_tag = display_title(tag)
        yaml_header = extract_yaml_header(f"Index: {display_tag}", tag)
        lines = [f"# {display_tag.title()} Index"]
        for page in sorted(pages):
            display_page = display_title(page)
            lines.append(f"- [[{display_page}]]")
        content = yaml_header + "\n".join(lines)
        with open(os.path.join(index_dir, f"_{tag}.md"), "w", encoding="utf-8") as f:
            f.write(content)
    logging.info("📚 Index pages created under _indexes/ with tag references")


def _create_outline_collection_indexes():
    """Create collection index documents for Outline mode.
    Each category gets an index page with standard markdown links to its documents.
    """
    for tag, pages in tag_to_pages.items():
        display_tag = display_title(tag)
        cat_dir = os.path.join(OUTPUT_DIR, clean_filename(tag))
        os.makedirs(cat_dir, exist_ok=True)
        index_relpath = os.path.join(clean_filename(tag), "index.md").replace(os.sep, '/')

        lines = [f"# {display_tag.title()}", ""]
        for page in sorted(pages):
            display_page = display_title(page)
            link = resolve_page_link(
                page,
                current_page_path=index_relpath,
                output_format="outline",
            )
            lines.append(f"- [{display_page}]({link})")

        content = "\n".join(lines) + "\n"
        index_path = os.path.join(cat_dir, "index.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)

    logging.info("📚 Collection index pages created for Outline")


def validate_local_links():
    broken_links = []

    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for filename in files:
            if not filename.endswith(".md"):
                continue

            filepath = os.path.join(root, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            for raw_target in MARKDOWN_LINK_TARGET_REGEX.findall(content):
                target = raw_target.strip()
                if not target or target.startswith(('http://', 'https://', 'mailto:', '#')):
                    continue

                target_path = target.split('#', 1)[0]
                target_path = url_unquote(target_path)
                candidate = os.path.normpath(os.path.join(root, target_path))
                if not os.path.exists(candidate):
                    broken_links.append((filepath, raw_target))

    if broken_links:
        for filepath, target in broken_links[:MAX_BROKEN_LINK_WARNINGS]:
            logging.warning(f"⚠️ Broken local link in {filepath}: {target}")
        logging.warning(f"⚠️ Found {len(broken_links)} broken local links")
    else:
        logging.info("🔗 Local link validation passed")

    return broken_links

def outline_api_request(endpoint, data=None, files=None):
    """Make an authenticated request to the Outline API."""
    if not OUTLINE_URL or not OUTLINE_API_KEY:
        return None
    url = f"{OUTLINE_URL.rstrip('/')}/api/{endpoint}"
    headers = {"Authorization": f"Bearer {OUTLINE_API_KEY}"}
    try:
        if files:
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=30)
        else:
            headers["Content-Type"] = "application/json"
            resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logging.error(f"❌ Outline API error ({endpoint}): {e}")
        return None


def outline_get_or_create_collection(name):
    """Get an existing collection by name or create a new one."""
    # List existing collections
    result = outline_api_request("collections.list", {"limit": 100})
    if result and result.get("data"):
        for col in result["data"]:
            if col.get("name", "").lower() == name.lower():
                logging.debug(f"📂 Found existing collection: {name}")
                return col["id"]

    # Create new collection
    result = outline_api_request("collections.create", {
        "name": name,
        "permission": "read_write"
    })
    if result and result.get("data"):
        logging.info(f"📂 Created collection: {name}")
        return result["data"]["id"]
    return None


def outline_upload_image(filepath):
    """Upload an image to Outline and return its URL."""
    filename = os.path.basename(filepath)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = IMAGE_CONTENT_TYPES.get(ext, "image/png")

    try:
        with open(filepath, "rb") as f:
            result = outline_api_request(
                "attachments.create",
                data={"name": filename, "documentId": ""},
                files={"file": (filename, f, content_type)}
            )
        if result and result.get("data"):
            return result["data"].get("url")
    except (OSError, IOError, requests.RequestException) as e:
        logging.error(f"❌ Failed to upload image {filename}: {e}")
    return None


def outline_upload_documents():
    """Upload all converted documents to Outline via API."""
    if not OUTLINE_URL or not OUTLINE_API_KEY:
        return

    logging.info("📤 Uploading documents to Outline...")

    # Upload images first and build URL mapping
    image_url_map = {}
    images_dir = os.path.join(OUTPUT_DIR, IMAGE_DIR)
    if os.path.isdir(images_dir):
        for img_file in os.listdir(images_dir):
            img_path = os.path.join(images_dir, img_file)
            if os.path.isfile(img_path):
                url = outline_upload_image(img_path)
                if url:
                    image_url_map[img_file] = url
                    logging.debug(f"📤 Uploaded image: {img_file}")

    # Determine collection IDs
    collection_ids = {}
    if COLLECTION_ID:
        default_collection = COLLECTION_ID
    else:
        default_collection = outline_get_or_create_collection("Imported Wiki")

    if not default_collection:
        logging.error("❌ Could not get or create Outline collection")
        return

    def _rewrite_uploaded_image(match):
        original_target = match.group(1)
        target = url_unquote(original_target.split("#", 1)[0])
        if re.match(r'^[a-z]+://', target) or target.startswith("data:"):
            return match.group(0)
        image_name = os.path.basename(target)
        image_url = image_url_map.get(image_name)
        if not image_url:
            return match.group(0)
        return match.group(0).replace(original_target, image_url)

    def _find_existing_outline_document(title, collection_id):
        result = outline_api_request("documents.search", {
            "query": title,
            "collectionId": collection_id,
        })
        if not result or not result.get("data"):
            return None

        for doc in result["data"]:
            doc_title = doc.get("title", "").strip().lower()
            doc_collection_id = doc.get("collectionId")
            if doc_title == title.strip().lower() and doc_collection_id == collection_id:
                return doc.get("id")
        return None

    # Walk through output directory and upload documents
    uploaded = 0
    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            # Rewrite image URLs to use Outline attachment URLs
            content = re.sub(
                r'!\[[^\]]*\]\(([^)]+)\)',
                _rewrite_uploaded_image,
                content,
            )

            # Extract title from first H1 heading
            title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
            title = title_match.group(1) if title_match else fname.replace(".md", "").replace("_", " ")

            # Determine collection
            rel_dir = os.path.relpath(root, OUTPUT_DIR)
            if rel_dir != "." and rel_dir != IMAGE_DIR:
                cat_name = display_title(rel_dir)
                if cat_name not in collection_ids:
                    cid = outline_get_or_create_collection(cat_name)
                    collection_ids[cat_name] = cid or default_collection
                col_id = collection_ids[cat_name]
            else:
                col_id = default_collection

            existing_doc_id = _find_existing_outline_document(title, col_id)
            if existing_doc_id:
                result = outline_api_request("documents.update", {
                    "id": existing_doc_id,
                    "title": title,
                    "text": content,
                    "collectionId": col_id,
                    "publish": True,
                })
            else:
                result = outline_api_request("documents.create", {
                    "title": title,
                    "text": content,
                    "collectionId": col_id,
                    "publish": True,
                })
            if result and result.get("data"):
                uploaded += 1
                logging.debug(f"📤 Uploaded: {title}")
            else:
                logging.warning(f"⚠️ Failed to upload: {title}")

    logging.info(f"📤 Uploaded {uploaded} documents to Outline")


def main():
    fmt_label = "Outline" if OUTPUT_FORMAT == "outline" else "Obsidian Vault"
    logging.info(f"🔄 Converting MediaWiki XML to {fmt_label}...")
    reset_runtime_state()
    try:
        tree = ET.parse(INPUT_XML)
    except ET.ParseError as e:
        logging.error(f"❌ Failed to parse XML: {e}")
        return

    try:
        extract_wiki_domain(tree)
    except ValueError as e:
        logging.error(f"❌ {e}")
        return

    plan_pages(tree)
    convert_pages(tree)
    create_redirect_stubs()
    create_tag_indexes()
    validate_local_links()

    if OUTPUT_FORMAT == "outline" and OUTLINE_URL and OUTLINE_API_KEY:
        outline_upload_documents()

    logging.info(f"✅ All done! Markdown ready at: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
