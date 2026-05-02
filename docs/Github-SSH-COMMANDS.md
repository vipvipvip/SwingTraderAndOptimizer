# GitHub Authentication Setup for WSL

How we solved GitHub push/pull authentication on a fresh WSL machine.

---

## What We Tried First (Did Not Work)

### SSH Key Approach
The WSL machine and Ubuntu laptop have the same SSH key pair (`~/.ssh/id_rsa`), but neither had the key registered on GitHub:

```bash
# Test GitHub SSH — resulted in: Permission denied (publickey)
ssh -T git@github.com

# Add GitHub host key and retry — still failed
ssh-keyscan github.com >> ~/.ssh/known_hosts
ssh -T git@github.com
```

**Why it failed:** The SSH key was never added to the GitHub account at github.com/settings/keys.

---

## What Actually Works (How Ubuntu Does It)

Ubuntu uses **HTTPS with a stored credential token**, not SSH.

### Step 1: Discover How Ubuntu Authenticates

```bash
# Check how Ubuntu stores git credentials
ssh dikesh@192.168.1.232 "git config --global credential.helper"
# Returns: store

# See the stored credential (shows token)
ssh dikesh@192.168.1.232 "cat ~/.git-credentials"
# Returns: https://vipvipvip:<token>@github.com
```

### Step 2: Configure Credential Store on WSL

```bash
# Set git to use the credential store helper
git config --global credential.helper store
```

### Step 3: Store the GitHub Token

```bash
# Copy the credential directly from Ubuntu
echo "https://vipvipvip:<github_token>@github.com" > ~/.git-credentials
```

> **Token format:** GitHub OAuth token (`gho_...`) or Personal Access Token (`github_pat_...`)
> **Where to get a new token:** github.com → Settings → Developer settings → Personal access tokens

### Step 4: Fix Divergent Branches (if remote has new commits)

```bash
# If push is rejected because remote is ahead:
git pull --rebase origin main
git push origin main
```

---

## Verify It Works

```bash
# Should push without prompting for credentials
git push origin main

# Should pull without prompting
git pull origin main
```

---

## How Credentials Are Stored

The token is stored in plaintext at:
```bash
cat ~/.git-credentials
# https://vipvipvip:<token>@github.com
```

> **Security note:** This file is plaintext. Keep WSL filesystem access controlled.
> On a shared machine, use a credential manager instead of `store`.

---

## Setting Up on a New WSL Machine

```bash
# 1. Configure credential store
git config --global credential.helper store

# 2. Store token (get token from existing machine or GitHub)
echo "https://YOUR_GITHUB_USERNAME:<YOUR_TOKEN>@github.com" > ~/.git-credentials

# 3. Set git identity
git config --global user.email "dikeshchokshi@gmail.com"
git config --global user.name "dikeshchokshi"

# 4. Verify
git push origin main
```

---

## Getting a Fresh Token from GitHub

If the token expires or is lost:

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Set expiration and select scopes: `repo` (full control)
4. Copy the token
5. Update `~/.git-credentials`:
   ```bash
   echo "https://vipvipvip:<NEW_TOKEN>@github.com" > ~/.git-credentials
   ```

---

## Summary

| Method | Status | Notes |
|--------|--------|-------|
| SSH key | ❌ Not used | Key not registered on GitHub |
| HTTPS + PAT embedded in remote URL | ❌ Fragile | Token visible in `git remote -v` |
| HTTPS + credential store | ✅ **Works** | Same as Ubuntu setup |
