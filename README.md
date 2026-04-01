# MediaWiki to Markdown Converter 🧭

This script converts a MediaWiki XML dump into clean Markdown — supporting both **Obsidian** vaults and **[Outline](https://www.getoutline.com/)** wikis. Includes images, categories, infoboxes, and structured metadata.

🧭 If you're looking for a worldbuilding tool to connect your ideas, check out my app [Chronicler](https://chronicler.pro/) (source available [here](https://github.com/mak-kirkland/chronicler))

🗂️ If you want to organize your vault into folders based on tags, check out my [Markdown Vault Organizer](https://github.com/mak-kirkland/markdown-vault-organizer).

## ✨ Features

- ✅ Converts MediaWiki pages to Obsidian-compatible or Outline-compatible Markdown
- 🏷️ Extracts and normalizes categories as tags (YAML frontmatter for Obsidian, metadata table for Outline)
- 📦 Converts infoboxes into structured metadata
- 🔧 Infers tags from infobox types using noun inflection
- 🖼️ Downloads and embeds images (`![[images/Filename]]` for Obsidian, `![alt](./images/Filename)` for Outline)
- 🗄️ Optionally sources images from a local MediaWiki backup archive (`--images-archive`) instead of downloading them from the web
- 🔗 Converts internal links to `[[Wikilinks]]` (Obsidian) or `[text](file.md)` (Outline)
- 📚 Generates tag-based index files (`_indexes/` for Obsidian, collection folders for Outline)
- 🐢 Supports Pandoc for better Markdown rendering (with Outline-optimized output)
- 🔍 Verbose mode for detailed output and easier troubleshooting
- 🧹 Strips HTML artifacts, converts footnotes, and handles definition lists (Outline mode)
- ↪️ Preserves redirects as stub documents and resolves Outline links against planned output paths
- 🧾 Preserves source metadata such as the last editor, timestamp, and source URL in exported headers
- ✅ Validates generated local Markdown links after export
- 📤 Optional direct upload to Outline via API

## Support

If you find this script useful, please consider supporting me on Patreon:

☕️ [Buy Me a Coffee](https://buymeacoffee.com/chronicler)
❤️ [Support on Patreon](https://patreon.com/MichaelKirkland)

---

## 📦 Requirements

- Python 3.8+
- [`pandoc`](https://pandoc.org/) (optional, but recommended for better Markdown conversion)

Install Python dependencies with:

```bash
pip install -r requirements.txt
```

## 🚀 Usage

### Basic (Obsidian — default)

```bash
python convert.py INPUT_XML [OUTPUT_DIR] [--skip-redirects] [--verbose]
```

### Outline Mode

```bash
python convert.py INPUT_XML [OUTPUT_DIR] --output-format outline [--skip-redirects] [--verbose]
```

### Outline with API Upload

```bash
export OUTLINE_API_KEY=YOUR_API_KEY
python convert.py INPUT_XML --output-format outline \
  --outline-url https://wiki.example.com \
  [--outline-api-key-file /path/to/outline-api-key.txt] \
  [--collection-id COLLECTION_ID]
```

| Argument             | Description                                                    |
| -------------------- | -------------------------------------------------------------- |
| `INPUT_XML`          | Path to your MediaWiki XML dump                                |
| `OUTPUT_DIR`         | Optional output folder (default: `obsidian_vault/` or `outline_output/`) |
| `--output-format`    | `obsidian` (default) or `outline`                              |
| `--skip-redirects`   | Ignore redirect pages                                          |
| `--verbose`          | Enable verbose logging (disables progress bar)                 |
| `--outline-url`      | Outline instance URL for API upload                            |
| `OUTLINE_API_KEY`    | Environment variable used for Outline API authentication        |
| `--outline-api-key-file` | Optional file path containing the Outline API key          |
| `--collection-id`    | Outline collection ID (creates "Imported Wiki" if omitted)     |
| `--images-archive`   | Path to a MediaWiki images backup archive (e.g. `images.tar.gz`). Images are extracted from the archive instead of downloaded from the web. Accepts `.tar.gz`, `.tar.bz2`, `.tar.xz`, or plain `.tar`. |

## 📤 Exporting Your MediaWiki Content

This converter expects a **MediaWiki XML export** as input. During conversion it also tries to
download referenced images from the source wiki by using the `<base>` URL embedded in that XML dump.

If your wiki is still reachable, the simplest workflow is:

1. Export your pages to XML
2. Run this converter against that XML
3. Let the converter download images as it encounters `File:` / `Image:` links
4. Upload the generated Markdown to Outline

If your wiki is private, shutting down soon, or not publicly reachable, export the uploads/images
directory as well so you have a complete backup before you migrate.

### Option 1: Export from the MediaWiki Web UI

For smaller wikis or one-off migrations, use `Special:Export`:

1. Open `https://YOUR-WIKI.example.com/wiki/Special:Export`
2. Paste the page titles you want to export, one per line
3. Decide whether to export only current revisions or full history
4. Include templates if your pages depend on them
5. Download the resulting XML file

This is convenient, but it is not ideal for very large wikis and it does **not** export uploaded
files/images.

### Option 2: Export from the Server with `dumpBackup`

If you have shell access to the MediaWiki server, create a full XML dump from the maintenance tools.

Older MediaWiki installs typically use:

```bash
php maintenance/dumpBackup.php --current > mediawiki.xml
```

For full revision history:

```bash
php maintenance/dumpBackup.php --full > mediawiki-full-history.xml
```

Some newer MediaWiki installs route maintenance commands through `run.php` instead:

```bash
php maintenance/run.php dumpBackup --current > mediawiki.xml
```

Use `--current` for a migration-focused dump and `--full` only if you specifically need revision
history in your archive.

### Exporting Uploaded Images / Files

The converter can download images directly from the source wiki during conversion, but you should
still back up uploads separately if you are doing a serious migration.

#### Quick backup: copy the uploads directory

If you have filesystem access, archive the MediaWiki uploads directory directly.
MediaWiki stores uploads under an `images/` directory that is internally organised
into hash-based subdirectories (`images/a/ab/filename.ext`).  The converter only
needs the file **basenames** — it ignores the internal directory structure — so a
simple recursive archive of that folder is all you need:

```bash
# Run this from the directory that CONTAINS the MediaWiki images/ folder
tar -czf mediawiki-images.tar.gz images/
```

That produces a single `.tar.gz` file you can pass to `--images-archive` later.
The resulting archive contains paths like `images/a/ab/photo.jpg`; the converter
will find `photo.jpg` regardless of which subdirectory it lives in.

> **Tip:** run this command from the MediaWiki installation root (the directory
> that contains the `images/` folder), not from inside `images/` itself.  That
> way the archive preserves the full `images/…` prefix and nothing gets confused.

#### Selective backup: `dumpUploads`

If you only want the active uploaded files referenced by the wiki, use `dumpUploads` and copy the
reported files into a separate folder.

Older installs:

```bash
mkdir mediawiki-uploads
php maintenance/dumpUploads.php > uploads.txt
```

Newer installs may use:

```bash
mkdir mediawiki-uploads
php maintenance/run.php dumpUploads > uploads.txt
```

You can then review `uploads.txt` and copy or archive the listed files from the MediaWiki storage
backend or local `images/` directory.

### What to Keep Together

For a clean migration/backup, keep these artifacts together:

- `mediawiki.xml` (or your full-history XML dump)
- A backup of uploaded files/images
- The base URL of the original wiki
- Any credentials or API keys needed to access a private wiki during the conversion window

## 🧭 End-to-End Guide: MediaWiki → Markdown → Outline

### 1. Prepare the source wiki

- Confirm the source wiki still loads pages and file URLs correctly
- Generate your XML export
- If the wiki is private or may disappear soon, archive the uploads/images directory too
- Install `pandoc` if you want better Markdown output quality

### 2. Install this converter

```bash
git clone https://github.com/darkspadez/mediawiki-to-markdown.git
cd mediawiki-to-markdown
pip install -r requirements.txt
```

### 3. Run a local Outline-format export

**If the source wiki is still reachable**, the converter will download images automatically:

```bash
python convert.py mediawiki.xml outline_export --output-format outline --verbose
```

**If the source wiki is offline or private**, pass the images archive you created earlier so the converter can source images locally instead of hitting the network:

```bash
python convert.py mediawiki.xml outline_export \
  --output-format outline \
  --images-archive mediawiki-images.tar.gz \
  --verbose
```

> When `--images-archive` is provided, the archive is treated as the **authoritative** image source.
> If an image referenced in the wiki pages is not present in the archive, it is skipped rather than
> downloaded from the web.

What this does:

- Converts MediaWiki pages into Markdown files suitable for Outline
- Resolves internal links to real relative file paths
- Builds category/collection folder indexes
- Preserves redirects as stub pages
- Downloads referenced images into `outline_export/images/`
- Adds preserved source metadata to exported documents

### 4. Review the generated Markdown locally

Before uploading anything, inspect the output:

- Open a few representative pages
- Check internal links and redirect stubs
- Confirm images were downloaded into `images/`
- Spot check metadata tables, footnotes, and headings

If the wiki was reachable during conversion, the image directory should already be populated by the
converter. If not, restore or copy the required files before continuing.

### 5. Upload to Outline

Set your Outline API key:

```bash
export OUTLINE_API_KEY=YOUR_API_KEY
```

Then run the converter with Outline upload enabled:

```bash
python convert.py mediawiki.xml outline_export \
  --output-format outline \
  --outline-url https://outline.example.com \
  --collection-id YOUR_COLLECTION_ID
```

Or provide the API key from a file:

```bash
python convert.py mediawiki.xml outline_export \
  --output-format outline \
  --outline-url https://outline.example.com \
  --outline-api-key-file /path/to/outline-api-key.txt \
  --collection-id YOUR_COLLECTION_ID
```

If `--collection-id` is omitted, the script creates or reuses an `Imported Wiki` collection and
uploads documents there.

### 6. Verify the imported Outline workspace

After upload:

- Check a few collection folders
- Open pages that contain internal links and image embeds
- Verify redirects land on the expected target page
- Confirm duplicate retries did not create duplicate documents
- Spot check source metadata and formatting on complex pages

### 7. Recommended migration strategy

For a safer migration, use this order:

1. Export XML from MediaWiki (`dumpBackup --current`)
2. Back up uploads/images: `tar -czf mediawiki-images.tar.gz images/` (run from the MediaWiki root)
3. Run a local Outline-format export with the archive (no upload yet):
   ```bash
   python convert.py mediawiki.xml outline_export \
     --output-format outline \
     --images-archive mediawiki-images.tar.gz
   ```
4. Review the generated Markdown and confirm images landed in `outline_export/images/`
5. Run the Outline upload step
6. Validate the imported content in Outline

That gives you a reusable XML + uploads backup, a local Markdown snapshot, and a cleaner final
Outline import.

## 🗂️ Output Structure

### Obsidian Mode

```text
obsidian_vault/
├── _indexes/
│   ├── _people.md
│   ├── _locations.md
│   └── ...
├── images/
│   ├── Example.jpg
│   └── ...
├── Page_Title_1.md
├── Page_Title_2.md
└── ...
```

### Outline Mode

```text
outline_output/
├── characters/
│   ├── index.md
│   ├── Aragorn.md
│   └── ...
├── items/
│   ├── index.md
│   ├── One_Ring.md
│   └── ...
├── images/
│   ├── Example.jpg
│   └── ...
└── ...
```

## 🔄 Obsidian vs Outline: Key Differences

| Feature              | Obsidian                        | Outline                              |
| -------------------- | ------------------------------- | ------------------------------------ |
| Internal links       | `[[Page Title]]`                | `[Page Title](./Page_Title.md)`      |
| Image embeds         | `![[images/file.jpg]]`          | `![file.jpg](./images/file.jpg)`     |
| Metadata             | YAML frontmatter (`---`)        | `# Title` + metadata table           |
| Categories           | Tags in YAML                    | Collection subdirectories             |
| Index pages          | `_indexes/` with wikilinks      | `index.md` per collection folder     |
| Redirects            | Normal pages or skipped         | Redirect stub docs linking to targets |
| Link validation      | Not applicable                  | Post-export local markdown link check |
| HTML in output       | Preserved                       | Stripped (sup/sub → LaTeX)            |
| Footnotes            | Markdown footnotes              | Numbered references section           |
| Tables               | Pandoc Markdown tables          | Pipe tables (strict compatibility)    |

## 👤 Author

Created by Michael Kirkland
