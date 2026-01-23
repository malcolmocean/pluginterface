---
description: Unmute saywhen voice notifications
disable-model-invocation: true
---

# Unmute SayWhen Notifications

Unmute voice notifications by removing the mute file.

Run this command:

```bash
rm -f ~/.config/pluginterface/saywhen/mute
```

Then confirm to the user that notifications are unmuted. They can mute again with `/saywhen:mute`.
