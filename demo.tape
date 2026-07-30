# Renders the demo GIF for the README.
#
#   brew install vhs
#   vhs demo.tape
#
# Produces demo.gif. Run it from the repository root.

Output demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1280
Set Height 900
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "cd $(pwd) && export PYTHONPATH=src FORCE_COLOR=1 && clear"
Enter
Show

Sleep 800ms
Type "# A small app, written entirely by an AI assistant."
Enter
Sleep 1200ms
Type "# It imports cleanly. It looks finished. Let's check it."
Enter
Sleep 1600ms

Type "vibelint examples/vibe_coded_app"
Sleep 600ms
Enter

Sleep 8s
