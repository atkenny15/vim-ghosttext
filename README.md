# GhostText for Vim

Vim plugin for communicating with the [GhostText](https://github.com/GhostText/GhostText) browser plugin.

## Usage

To install the plugin it is recommended to use a Vim plugin manager such as [vim-plug](https://github.com/junegunn/vim-plug), [Vundle](https://github.com/VundleVim/Vundle.vim) or [Pathogen](https://github.com/tpope/vim-pathogen). Add the following line to your `.vimrc`:

```
Plug 'atkenny15/vim-ghosttext'
```

The following commands are proved:

- `GhostStart`: Start the GhostText HTTP server
- `GhostStop`: Stop the GhostText HTTP server (this is called on `QuitPre` if `GhostStart` has been called)

A detailed log can be found at: `<temp>/ghosttext-vim-log.txt`. Under Unix like systems this is typically `/tmp/ghosttext-vim-log.txt`. Please provide this log if you run into any issues.

## Design

### GhostText Interface

Launching GhostText from the web browser triggers a GET request to port 4001 (by default, configurable in the extension). It expects a response containing the JSON structure:

```
{
    "ProtocolVersion": 1,
    "WebSocketPort": <port>,
}
```

GhostText then acts as a WebSocket client on port `<port>` exchanging the following JSON packets:

```
{
    'text': <text>,
    'selections': [{'start': <start>, 'end': <end>}],
    'title': '',
    'url': '',
    'syntax': '',
}
```

`<text>` is the Unicode text data to be displayed. This plugin sets `<start>` and `<end>` to `len(<text>)`, `title` to `ghosttext-vim`, and does not change the other values. The other values seem to be specific to Sublime Text.  Some details are in the code [here](https://github.com/GhostText/GhostText-for-SublimeText/blob/master/GhostTextTools/OnSelectionModifiedListener.py):

```
changed_text = view.substr(sublime.Region(0, view.size()))
selections = OnSelectionModifiedListener._get_selections(view)
response = json.dumps({
    'title': view.name(),
    'text':  changed_text,
    'syntax': view.scope_name(0),
    'selections': selections
})
```

### GhostText for Vim Design

TODO

## Requirements

- Vim compiled with `+python` support
- Python2

## Rationale

The highly useful [it's All Text!](https://addons.mozilla.org/en-US/firefox/addon/its-all-text/) browser plugin is unsupported on Firefox Quantum. A couple other projects provide similar features, but for following reasons did not quite work for my use.

[(N)Vim Ghost](https://github.com/raghur/vim-ghost) uses [Neo-Vim](https://neovim.io/) specific features, and patching for Vim support is pretty much equivalent to a complete re-write. Additionally, this requires the [SimpleWebSocket](https://github.com/dpallot/simple-websocket-server) module installed, whereas this plugin has no non-core dependencies.

[Ghost Text Vim](https://github.com/falstro/ghost-text-vim) worked initially, but seems to have issues recently. Rather than try to modify a TCL program, it seemed easier and more interesting to just re-write the plugin in Python.

## Known Issues

- GhostText currently has problems if it is stopped and restarted, these are being addressed in a complete re-write of the browser plugin. To work around this, re-load the web page before running GhostText a second time. The two issues encountered so far are:
    - Multiple WebSocket connections are opened, but data is only sent on a single one
        - This plugin will cleanup any unused WebSockets that receive no post-handshake data within 3s, but the issue below prevents any further action
    - After the handshake and receiving valid data GhostText sends a close frame and no longer responds to any data sent to it
        - Sending data after receiving a valid frame does not do anything to mitigate this
        - There is no workaround available for this, a browser update is needed

## TODO

- [ ] Add better support for WebSocket
    - [ ] Support all valid frame opcodes
    - [ ] Client side support
        - [ ] Support mask generation in a Frame
    - [ ] Test payload lengths > 16-bit
    - [ ] Better validation of handshake header
- [ ] Vim Documentation
- [ ] Improve comments
- [ ] Allow HTTP port to be modified
- [ ] Better WebSocket port selection

## References

- [GhostText](https://github.com/GhostText/GhostText): Web browser plugin
- [GhostText for Sublime Text](https://github.com/GhostText/GhostText-for-SublimeText): Official plugin for Sublime Text
- [(N)Vim Ghost](https://github.com/raghur/vim-ghost): Plugin for for [Neo-Vim](https://neovim.io/)
- [Ghost Text Vim](https://github.com/falstro/ghost-text-vim): TCL plugin for Vim
- [RFC 6455](https://tools.ietf.org/html/rfc6455): The WebSocket Protocol
