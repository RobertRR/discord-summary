# 🤖 Discord Summary Bot (Gemini-Powered)

A lightweight, Dockerized Discord bot that summarizes channel conversations and provides high-fidelity fact-checking using Google's Gemini AI. It features **intelligent API key rotation**, **isolated reasoning models**, and **autonomous GitHub synchronization**.

---

## 🌟 Features

* **Smart Summaries:** The `!tldr` command will group by user display name with clean headers and bulleted contributions.
* **Pro-Reasoning Fact-Checker:** The `!huh` command exclusively utilizes the **Gemini 3.1 Pro** model to analyze a single replied-to message for misinformation, providing a concise summary and credible sources.
* **Argument Resolution:** The `!arguments` command gives decisive adjudication of conflicts based on argument strength and wit.
* **👑 Multi-Server Moggboard:** A competitive dominance hierarchy. The AI analyzes arguments, declares winners, and assigns **Ranks** (Immortal, Divine, Ancient, etc.) based on win/loss ratios.
* **Autonomous Auto-Sync:** Every 5 minutes, the bot performs a background hash-check against your GitHub repository. If a change is detected, it automatically pulls the new code and restarts.
* **API Key Rotation:** Automatically cycles through multiple Gemini API keys to maximize free-tier quotas with aggressive cache-busting headers.
---

## 🛠 Commands

The `!tldr` and `!arguments` commands are flexible! You can type e.g. `!tldr today` for a summary of all conversations since 12am, or `!tldr 50 messages` or `!tldr 30 mins` for message count or time based. You can also reply to a message and just say `!tldr` or `!arguments` to use that message as the starting point for the bot's processing. The `!huh` command must be a reply to an existing message.

| Command | Description | Access |
| :--- | :--- | :--- |
| `!help` | Displays the help menu. | Everyone |
| `!tldr [val/links/today]` | Summaries history. | Everyone |
| `!arguments [val/links/today]` | Adjudicates conflicts and updates the Moggboard. | Everyone |
| `!huh` | **(Reply Required)** Isolated Pro-model fact-check of a single message. | Everyone |
| `!moggboard` | Displays the server's rank hierarchy and win/loss stats. | Everyone |
| `!keystatus` | Monitors API key health, daily quotas, and model usage. | Everyone |
| `!version` | Displays build info, uptime, and the latest changelog. | Everyone |
| `!botlog` | **(Admin Only)** Displays the last 10 lines of the high-precision log. | **Admins** |
| `!clearmogs` | **(Admin Only)** Resets Moggboard stats for the current server. | **Admins** |
| `!update` | **(Admin Only)** Manually triggers a GitHub sync and container restart. | **Admins** |

---

## 📋 Deployment and Setup

### 1. Discord Bot Setup
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a **New Application** and add a **Bot**.
3. Under the **Bot** tab, enable **Message Content Intent** and **Server Members Intent**.
4. Invite the bot to your server using the OAuth2 URL Generator with `Send Messages`, `Embed Links`, `Read Message History`, and `Add Reactions` permissions.

### 2. Gemini API Keys
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Create one or more API Keys. (Key rotation handles multiple accounts seamlessly).

### 3. Server Files
Create a project folder (e.g., `/projects/discord-summary`) containing:
* **`discordtoken.txt`**: Your Bot Token (one line).
* **`keys.txt`**: Your Gemini API Keys (one per line).
* **`admins.txt`**: Your Discord User ID (one per line).

---

## 🚀 Deployment

Launch the bot using the provided `docker-compose.yml`. The container is configured to automatically install required dependencies and enter the update-monitoring loop.

---

## ⚙️ Health & Updates

### 💓 Health Checks
The container monitors the `bot.py` process specifically:
* **Interval:** 1 Minute.
* **Start Period:** 4 Minutes (to allow for initial dependency installs on lower-power hardware).
* **Action:** Automatic restart if the process hangs or fails.

### 🔄 Dual-Update System
This bot features a custom handshake system to bypass CDN caching:
* **Manual Update:** Admins can use `!update` to force an immediate refresh. The bot confirms the trigger and reports success once online.
* **Auto-Update:** The bot detects GitHub changes every 5 minutes.
* **Intelligent Reporting:** On reboot, the bot distinguishes between manual and automatic updates in its status report, ensuring clarity for the community.
* **Robustness:** Uses a recursive restart check (`pending_update.txt`) to bypass GitHub CDN cache hits, ensuring the local code matches the remote hash exactly before reporting success.

> [!IMPORTANT]
> Ensure the `GITHUB_RAW_URL` in `bot.py` is updated to point to your specific repository for the Auto-Sync feature to function.
