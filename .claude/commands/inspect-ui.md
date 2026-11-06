# Inspect UI Elements

Run the UI element inspector against the currently connected Android device and print the results.

```bash
python inspect_ui.py $ARGUMENTS
```

After printing the output:

- If the user is debugging a locator failure, identify the best `class`, `content-desc`, or `text` attribute to use as a selector and suggest the corrected locator code.
- If multiple elements match a filter, highlight which one is most likely the intended target based on its bounds (position on screen) and clickable status.
- If no elements matched, suggest a broader filter to try next.
