The scheduled time has arrived. It is now {{ current_time }}.
Execute this scheduled cron job now and report the result to the user in the
same session.

Treat the date above as authoritative: this turn may be a day or more after
the previous message in this conversation, so do not reuse a date you
established earlier in the session.

Rules:
- Speak directly to the user in their language.
- Do not narrate internal progress.
- Do not include user IDs.
- Do not add status reports like "Done" or "Reminded" unless they are the natural response.

Cron job: {{ message }}
