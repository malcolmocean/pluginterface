---
description: Mute saywhen voice notifications
disable-model-invocation: true
---

# Mute SayWhen Notifications

Mute voice notifications by creating the mute file.

Run this command:

```bash
mkdir -p ~/.config/pluginterface/saywhen && touch ~/.config/pluginterface/saywhen/mute
```

Then confirm to the user that notifications are muted. They can unmute with `/saywhen:unmute`.
