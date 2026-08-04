# LinkedIn Posting Tracker

## How to Use

### 1. Import to Google Sheets (Recommended)
- Copy the contents of `POSTING_TRACKER.csv`
- Create a new Google Sheet in your LinkedIn-Posts folder
- Paste as new sheet (Data → Import range or paste directly)
- Access from any device via Google Drive

### 2. Or Edit the CSV Directly
- Edit `POSTING_TRACKER.csv` in your editor
- Update columns as you post

## Column Guide

| Column | Purpose | Example |
|--------|---------|---------|
| **Week** | 1-24 schedule | 3 |
| **Post Title** | Full title for LinkedIn | "The 11-Year Journey..." |
| **Content File/Link** | Where to find the post | LINKEDIN_POSTS_FOUNDER_STORY.md#Post1 |
| **Post Date** | When you posted it | 2026-08-11 |
| **Category** | Content type | Founder Story, AI Focus, etc. |
| **Posted?** | Status (Yes/No or checkbox) | Yes |
| **LinkedIn URL** | Link to the posted content | https://linkedin.com/posts/... |
| **Notes** | Any special info | "Added video link", "Rescheduled" |

## Workflow

1. **Week X:** Check tracker for scheduled post
2. **Read** the post content (from linked file)
3. **Post to LinkedIn** (manual)
4. **Update tracker:**
   - `Posted?` → Yes
   - `Post Date` → actual date
   - `LinkedIn URL` → copy-paste from posted link
5. **Commit** changes to Git
6. **On other laptop:** `git pull` → tracker is up to date

## Cross-Machine Sync

- Laptop A: Update tracker, commit
- Laptop B: `git pull` → get latest tracker status
- Session memory in Git keeps everything in sync

## Tips

- Sort by Week to see upcoming posts
- Use filters to show only "Posted = No" for unfinished
- Keep LinkedIn URLs so you can reference posted content later
- Add notes for anything unusual (rescheduled, received strong engagement, etc.)
