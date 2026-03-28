# 🤖 Discord Summary Bot (Gemini-Powered)

A lightweight, Dockerized Discord bot that summarizes channel conversations using Google's Gemini AI. It features **intelligent API key rotation**, **multi-model fallback**, and **self-updating capabilities**.

---
## 🌟 Features

* **Smart Summaries:** Grouped by user with clean, underlined headers and bullet points.
* **Argument Resolution:** Have the bot check for an argument and determine who is right and check if anyone got mogged.
* **👑 Multi-Server Moggboard:** A competitive dominance hierarchy. The AI analyzes arguments, declares a winner, and ranks users based on their win/loss ratio. Data is partitioned by Server ID, allowing independent rankings across multiple servers.
* **Precision Anchors:** Use **Discord Message Links** to set exact start and end points for a summary.
* **Contextual Replies:** Simply **reply** to any message with `!tldr` to summarize everything from that specific point forward.
* **Token Safeguards:** Built-in limits (24h time cap / 300 message cap) to prevent runaway token usage and API exhaustion.
* **API Key Rotation:** Automatically cycles through multiple Gemini API keys to maximize free-tier quotas with a 65-second "cool-off" for rate-limited keys.
* **Model Fallback:** Automatically tries higher-tier models (e.g 3.1 Pro) before falling back to faster, lighter models.
* **Self-Updating:** Admin-only `!update` command pulls the latest code from GitHub and restarts the container instantly.
* **Flexible TLDR:** Supports message counts (`!tldr 50`), timeframes (`!tldr 30min`), or specific links.
---

## 🛠 Commands

| Command | Description | Access |
| :--- | :--- | :--- |
| `!help` | Displays the help menu and command list. | Everyone |
| `!tldr [val/links]` | Summarizes history. Supports **count**, **time**, **links**, or **replies**. | Everyone |
| `!arguments [val/links]` | Analyzes conflicts and updates the Moggboard. Supports **links/replies**. | Everyone |
| `!moggboard` | Displays the current server's dominance hierarchy and rankings. | Everyone |
| `!keystatus` | Shows API health, cooldown timers, and daily usage per model. | Everyone |
| `!version` | Displays the current build version (e.g., `v4.1`). | Everyone |
| `!botlog` | **(Admin Only)** Displays the last 10 lines of the terminal log. | **Admins** |
| `!clearmogs` | **(Admin Only)** Resets Moggboard stats for the **current server only**. | **Admins** |
| `!update` | **(Admin Only)** Pulls the latest code and restarts the bot. | **Admins** |


## 📋 Deployment and Setup

### 1. Discord Bot Setup
1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Create a **New Application** and add a **Bot**.
3.  Under the **Bot** tab, enable **Message Content Intent** (Required for reading chat).
4.  Copy your **Bot Token**.
5.  Invite the bot to your server using the OAuth2 URL Generator with the following **Permissions** (Do **NOT** use Administrator):
    * `View Channels`
    * `Send Messages`
    * `Read Message History`

### 2. Gemini API Keys
1.  Go to [Google AI Studio](https://aistudio.google.com/).
2.  Create one or more API Keys. 
    * *Note: Using multiple keys from different Google accounts allows you to bypass individual rate limits.*

### 3. Server Files
On your host machine (e.g., Debian), create a project folder (e.g., `/projects/discord-summary`) and create the following three text files:

* **`discordtoken.txt`**: Paste your Discord Bot Token here (one line).
* **`keys.txt`**: Paste your Gemini API Keys here, one per line.
* **`admins.txt`**: Paste your Discord User ID here (and any other admins), one per line. 
    * *To find your ID: Enable Developer Mode in Discord Settings > Right-click your name > Copy User ID.*

---

## 🚀 Deployment

Create a `docker-compose.yml` file in your project folder using the compose.yaml file in this project and start the container.

## ⚙️ Health & Updates

### 💓 Health Checks
The container includes a built-in health monitor to ensure maximum uptime:
* **Interval:** 30 seconds.
* **Action:** If the Python process is not detected (via `pgrep`), Docker marks the container as unhealthy and triggers a restart after 3 failed attempts.

### 🔄 Auto-Update System
This bot is designed for "headless" management. You can update the bot's code without ever touching your server's terminal:

1. **Push** your changes to your GitHub repository.
2. Type **`!update`** in any Discord channel the bot can see.
3. The bot will:
    * Terminate its current process.
    * Trigger a Docker container restart.
    * Wipe the old `bot.py` and `curl` the newest version from GitHub.
    * Re-initialize and send a DM to the admin once it's back online.

> [!NOTE]
> This feature requires `procps` and `curl` to be installed within the container environment (handled automatically by the provided `docker-compose.yml`).
