# GitHub Wiki Auto-Generation Setup

This repository includes an automated workflow that generates Wiki documentation from the
OpenAPI specification.

## How It Works

The workflow (`.github/workflows/wiki-update.yml`) automatically:

1. Triggers when `openapi.yaml` is updated on the `main` branch
2. Runs `scripts/generate_wiki_docs.py` to convert OpenAPI spec to Markdown
3. Clones the Wiki repository
4. Copies the generated pages to the Wiki
5. Commits and pushes the changes

## Initial Setup

**Important**: The GitHub Wiki must be initialized before the workflow can update it.

### One-Time Setup Steps

1. Go to the repository's Wiki tab on GitHub
2. Click "Create the first page"
3. Add any content (it will be replaced by the workflow)
4. Click "Save Page"

This creates the Wiki repository, allowing the workflow to push updates.

### Manual Trigger

You can manually trigger the workflow:

1. Go to Actions tab on GitHub
2. Select "Update Wiki Documentation"
3. Click "Run workflow"

## Workflow Permissions

The workflow uses `contents: write` permission to push to the Wiki repository. This
permission is granted to `GITHUB_TOKEN` by default for workflows triggered by push events
on the main branch.

## Generated Pages

The workflow generates these Wiki pages:

- **Home**: API overview and quick links
- **API-Reference**: Complete endpoint documentation
- **Getting-Started**: Quick start guide
- **Examples**: Code examples (Python, JavaScript, Bash)
- **Authentication**: Security information

## Customization

To modify the generated Wiki pages, edit:

- `scripts/generate_wiki_docs.py` - Generation logic
- `openapi.yaml` - API specification (source of truth)

## Troubleshooting

### Workflow fails with "repository not found"

- **Cause**: Wiki hasn't been initialized
- **Solution**: Create the first Wiki page manually (see Initial Setup above)

### Changes not appearing in Wiki

- **Cause**: Workflow might be disabled or failed
- **Solution**: Check the Actions tab for workflow runs and any errors

### Wiki content is outdated

- **Cause**: Workflow only runs when triggered files change
- **Solution**: Manually trigger the workflow from the Actions tab
