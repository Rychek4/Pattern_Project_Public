# Reddit Integration Setup

Pattern can browse, post, comment, vote, and search on Reddit via the PRAW library.

## Prerequisites

- A Reddit account
- Python 3.7+ with PRAW installed (`pip install praw`)

## Step 1: Create a Reddit App

1. Log in to your Reddit account
2. Go to **https://www.reddit.com/prefs/apps**
3. Scroll to the bottom and click **"create another app..."**
4. Fill in the form:
   - **name**: `pattern-agent` (or any name you prefer)
   - **type**: Select **script**
   - **description**: Optional (e.g., "Pattern Project AI integration")
   - **about url**: Leave blank
   - **redirect uri**: `http://localhost:8080` (required but not used for script apps)
5. Click **"create app"**

After creation, you'll see your app listed. Note the two values you need:

- **Client ID**: The short string directly under "personal use script" (under the app name)
- **Client Secret**: The value labeled "secret"

## Step 2: Configure Environment Variables

Add the following to your `.env` file:

```bash
REDDIT_ENABLED=true
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USERNAME=your_reddit_username
REDDIT_PASSWORD=your_reddit_password
REDDIT_USER_AGENT=python:pattern-agent:v1.0 (by /u/your_reddit_username)
```

**Important**: Update the `REDDIT_USER_AGENT` to include your actual Reddit username. Reddit requires a descriptive User-Agent and will throttle requests with generic or missing agents.

## Step 3: Validate Credentials

Run the setup validation script:

```bash
python scripts/reddit_setup.py
```

This will:
- Check that all required environment variables are set
- Attempt to authenticate with the Reddit API
- Display your account info (username, karma) on success
- Show troubleshooting hints on failure

## Step 4: Restart Pattern

After validation succeeds, restart Pattern. The 8 Reddit tools will automatically appear in the AI's toolkit.

## Available Tools

Once enabled, the AI has access to these tools:

| Tool | Description |
|------|-------------|
| `reddit_feed` | Browse a subreddit's posts (hot/new/top/rising) |
| `reddit_post` | Get a single post with its comment tree |
| `reddit_create_post` | Create a text or link post |
| `reddit_comment` | Reply to a post or comment |
| `reddit_vote` | Upvote, downvote, or clear vote |
| `reddit_search` | Search posts across Reddit or within a subreddit |
| `reddit_subreddits` | Search for or list subscribed subreddits |
| `reddit_profile` | Get a user's public profile |

## Rate Limits

Rate limits are enforced client-side to stay well under Reddit's actual limits:

| Operation | Limit | Reddit's Actual Limit |
|-----------|-------|-----------------------|
| All requests | 30/minute | 60/minute |
| Posts | 1 per 30 minutes | ~1 per 10 minutes |
| Comments | 10/hour | No hard limit (anti-spam varies) |
| Votes | 30/hour | No hard limit |

These conservative limits prevent any automated-activity flags on the account.

## Troubleshooting

### "AUTHENTICATION FAILED" during setup

- **Wrong credentials**: Double-check `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` at https://www.reddit.com/prefs/apps. The client ID is the short string *under* the app name, not the app name itself.
- **2FA enabled**: Reddit's OAuth2 "script" flow does not support 2FA. Either disable 2FA on the account or use a dedicated account without 2FA.
- **Wrong password**: The password is your Reddit account password, not an app-specific password.
- **Account suspended**: Check that the Reddit account is in good standing.

### "PRAW not installed"

```bash
pip install praw
```

### Tools don't appear after restart

- Confirm `REDDIT_ENABLED=true` in your `.env` file (not `True` or `1`)
- Check Pattern's startup logs for any Reddit-related errors
- Run `python scripts/reddit_setup.py` again to re-validate

### Rate limit errors during use

The built-in rate limiter will block requests and tell the AI how long to wait. If you see frequent rate limiting, the AI is being too aggressive — it will naturally back off based on the error messages.

## Security Notes

- Your Reddit password is stored in the `.env` file. Ensure this file is in `.gitignore` and not committed to version control.
- The "script" app type is designed for single-user personal use. It authenticates directly with username/password — no OAuth browser flow needed.
- All API actions are performed under your Reddit account. The User-Agent identifies the requests as automated.
