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
- 🔗 Converts internal links to `[[Wikilinks]]` (Obsidian) or `[text](file.md)` (Outline)
- 📚 Generates tag-based index files (`_indexes/` for Obsidian, collection folders for Outline)
- 🐢 Supports Pandoc for better Markdown rendering (with Outline-optimized output)
- 🔍 Verbose mode for detailed output and easier troubleshooting
- 🧹 Strips HTML artifacts, converts footnotes, and handles definition lists (Outline mode)
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
python convert.py INPUT_XML --output-format outline \
  --outline-url https://wiki.example.com \
  --outline-api-key YOUR_API_KEY \
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
| `--outline-api-key`  | Outline API key for authentication                             |
| `--collection-id`    | Outline collection ID (creates "Imported Wiki" if omitted)     |

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
| HTML in output       | Preserved                       | Stripped (sup/sub → LaTeX)            |
| Footnotes            | Markdown footnotes              | Numbered references section           |
| Tables               | Pandoc Markdown tables          | Pipe tables (strict compatibility)    |

## 👤 Author

Created by Michael Kirkland
