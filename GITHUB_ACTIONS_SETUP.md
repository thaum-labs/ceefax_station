# GitHub Actions Deployment Setup

## Step 1: Add Public Key to Server

SSH into your server and run:

```bash
ssh root@134.209.23.220
```

Then on the server, add the public key:

```bash
mkdir -p ~/.ssh
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILQ6zgDHK7u+5KZBqbJ2fVeK5oh6VTO8NVEPPEv7AnrM github-actions-deploy" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

## Step 2: Add Secrets to GitHub

Go to: https://github.com/thaum-labs/ceefax_station_website/settings/secrets/actions

Click "New repository secret" and add these three secrets:

### Secret 1: DO_HOST
- Name: `DO_HOST`
- Value: `134.209.23.220`

### Secret 2: DO_USER
- Name: `DO_USER`
- Value: `root`

### Secret 3: DO_SSH_KEY
- Name: `DO_SSH_KEY`
- Value: (see private key below)

## Private Key for DO_SSH_KEY Secret:

**On your local machine, run this command to get the private key:**

```powershell
Get-Content $env:USERPROFILE\.ssh\github_actions_deploy
```

**Important:** Copy the ENTIRE output (including the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines) and paste it as the value for `DO_SSH_KEY` in GitHub.

## Step 3: Test the Deployment

After adding the secrets, push any change to trigger the workflow:

```bash
git commit --allow-empty -m "Test automatic deployment"
git push
```

Then check: https://github.com/thaum-labs/ceefax_station_website/actions

