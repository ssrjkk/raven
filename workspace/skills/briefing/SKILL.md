Morning briefing that summarizes news, weather, calendar events, and system status. Designed to run as a scheduled routine every weekday at 8:00 AM.

When generating a briefing:
1. Use `web_search` to fetch top news headlines from trusted sources.
2. Use `get_weather` to fetch current weather for the user's configured location.
3. Check any active monitors via `monitor_list` and report status.
4. List any pending tasks via the task engine.
5. Format the briefing in a clean, scannable structure:
   - ☀️ Weather
   - 📰 Top News (3-5 items with brief summaries)
   - 📊 System Status (monitors, tasks)
   - 📅 Reminders (if any)

The routine named "morning_briefing" should be scheduled via the cron plugin at "0 8 * * 1-5" and use the `send_message` action to deliver via Telegram.