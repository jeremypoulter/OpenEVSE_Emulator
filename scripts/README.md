# Scripts

This directory contains utility scripts for the OpenEVSE Emulator project.

## generate_wiki_docs.py

Generates GitHub Wiki documentation from the OpenAPI specification.

### Usage

```bash
python scripts/generate_wiki_docs.py
```

This script:

1. Reads `openapi.yaml` from the repository root
2. Generates Wiki pages in Markdown format
3. Outputs the pages to the `wiki/` directory

### Generated Pages

- **Home.md**: Overview and quick links
- **API-Reference.md**: Complete API endpoint documentation
- **Getting-Started.md**: Quick start guide with examples
- **Examples.md**: Comprehensive code examples in multiple languages
- **Authentication.md**: Security and authentication information

### Automated Updates

The GitHub Actions workflow `.github/workflows/wiki-update.yml` automatically:

- Runs when `openapi.yaml` or the generation script changes
- Generates fresh Wiki documentation
- Commits and pushes changes to the repository Wiki

### Manual Wiki Update

To manually update the Wiki:

1. Generate the documentation:

   ```bash
   python scripts/generate_wiki_docs.py
   ```

2. Clone the Wiki repository:

   ```bash
   git clone https://github.com/jeremypoulter/OpenEVSE_Emulator.wiki.git
   ```

3. Copy the generated files:

   ```bash
   cp wiki/* OpenEVSE_Emulator.wiki/
   ```

4. Commit and push:

   ```bash
   cd OpenEVSE_Emulator.wiki
   git add .
   git commit -m "Update API documentation"
   git push
   ```

### Dependencies

- Python 3.10+
- PyYAML: `pip install pyyaml`
