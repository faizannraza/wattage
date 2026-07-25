# Regenerate docs/assets/demo.gif:
#   brew install vhs
#   cd <repo root>
#   vhs docs/assets/demo.tape

Output docs/assets/demo.gif

Require uvx

Set Shell "zsh"
Set FontSize 18
Set Width 1200
Set Height 640
Set Theme "GitHub Dark"
Set Padding 24
Set TypingSpeed 45ms
Set WindowBar Colorful
Set BorderRadius 8

Type "uvx wattage report benchmarks/traces/any_agent_openai.otlp.json"
Sleep 500ms
Enter

Sleep 5s
