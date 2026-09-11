# <img src="frontend/public/logo.png" alt="RedactPDF" width="40" align="center" /> RedactPDF

**Redact PDFs on your own machine.** Mark what has to go (a passage of text, an
image, a whole page, every phone number in the file) and get back a copy with
that content removed from the document, not hidden under a black rectangle.

Nothing is uploaded. No network calls, no account, no telemetry. Download a
binary for Windows or Linux, or `pipx install blankout` on any machine that has
Python. Nothing else to install, text recognition for images included.

<p align="center">
  <video src="https://github.com/user-attachments/assets/6b3baa14-75d3-45cb-883f-b8b7e1ef72cb" controls width="820">
    <a href="https://github.com/user-attachments/assets/6b3baa14-75d3-45cb-883f-b8b7e1ef72cb">▶ Watch the demo</a>
  </video>
</p>

<p align="center">
  <sub>
    Content is deleted from the file, not covered with a black box. Check it
    yourself with a different PDF library:
    <a href="docs/USAGE.md#check-the-output-yourself">Check the output yourself</a>.
  </sub>
</p>

---

## What it does

You open a PDF in your browser, mark content in one of five ways, and export:

| Way in | What it covers |
| --- | --- |
| **Select text** | highlight it in the viewer, redact the selection |
| **Draw a rectangle** | whatever the text layer cannot reach: a scan, a signature, a logo |
| **Censor a page** | wipes the page whole, images and vector graphics included |
| **Type a pattern** | an exact string or a regular expression, with options for word boundaries, accents and line breaks |
| **Pick a detector** | e-mail addresses, phone numbers validated with libphonenumber, card numbers filtered by Luhn |

Whatever you mark is deleted from the file. Images are handled as well: by
default only the pixels you targeted are blackened inside the bitmap itself,
which is what makes a flattened scan redactable without losing the rest of the
page.

## Every export is checked before you get it

After redacting, RedactPDF re-runs the rules you gave it **against the file it
just produced**. If anything you targeted is still findable in there, you do not
get the file. You get a report naming what survived, on which page, and whether
the engine was able to locate it at all.

There is a third answer, and it matters more than it looks. An audit can only
report that a target survived; it can never report that it was unable to look. A
name printed inside a scan is invisible to the rules and equally invisible to the
check, so the export used to succeed with the name plainly on screen. RedactPDF
now says so instead: an area it could not read stops the export and is shown to
you, one by one, to confirm. You can turn that off, but only by naming the
choice.

That check has caught real failures, and it has blind spots of its own. Both are
written down in [docs/SECURITY.md](docs/SECURITY.md) rather than left implied;
read it before trusting the tool with anything that matters. And if you would
rather not take its word for it, three commands from a different PDF library will
tell you independently: see
[Check the output yourself](docs/USAGE.md#check-the-output-yourself).

---

## Download

Take the file for your system from the
[latest release](https://github.com/theodubus/RedactPDF/releases/latest) and run
it. No Python, no Node, nothing to install. The app opens in your browser and
stops when you close the tab.

| System | File |
| --- | --- |
| Windows | `redactpdf-windows-x86_64.exe` |
| Linux (x86-64) | `redactpdf-linux-x86_64`, `chmod +x` it first |

**Windows shows "Windows protected your PC" on first run**, because the
executable is not signed with a paid code-signing certificate. Click **More
info**, then **Run anyway**. [docs/WINDOWS_BUILD.md](docs/WINDOWS_BUILD.md)
explains why. On Linux the binary needs a glibc at least as recent as
Ubuntu 22.04's.

Since the binary is unsigned, the release page gives you two ways to check it
yourself instead. `SHA256SUMS.txt` says the bytes are the ones that were built:

```bash
sha256sum --ignore-missing -c SHA256SUMS.txt
```

And the build attestation says *this repository* built them, at a known commit,
on GitHub's runners, which a hash alone cannot tell you:

```bash
gh attestation verify redactpdf-linux-x86_64 --repo theodubus/RedactPDF
```

### With Python: any OS, and the recommended path on macOS

```bash
pipx install blankout
blankout
```

Same app, same single command to run it. There is no macOS binary: a file
downloaded through a browser carries a quarantine attribute, and since macOS
Sequoia clearing it takes a trip through System Settings and an admin password.
`pipx` sidesteps that entirely, because nothing is downloaded by the browser and
Gatekeeper never applies. It also makes the install independent of the build
machine's glibc, which is what constrains the Linux binary above.

`uv tool install blankout` does the same job. Plain `pip install` works inside a
virtual environment you manage yourself, but into a system Python most current
Linux distributions refuse it outright (PEP 668).

### From source

```bash
git clone https://github.com/theodubus/RedactPDF.git
cd RedactPDF/frontend && npm ci && npm run build && cd ..
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cd ..
python launch.py
```

---

## Documentation

| Document | What is in it |
| --- | --- |
| [**Usage**](docs/USAGE.md) | The five kinds of rule, the three image modes, what the matching does that the UI does not show, and how to verify an export with software that is not this project. |
| [**Security model**](docs/SECURITY.md) | What is guaranteed, what is not, and the known limits, including the ones that are structural rather than bugs. Also covers exposing the API beyond a single local user. |
| [**Development**](docs/DEVELOPMENT.md) | Running the two halves with hot reload, the test suite and its PDF fixtures, building the binary and the wheel, and what CI checks. |
| [**Windows build**](docs/WINDOWS_BUILD.md) | The failure modes of the frozen Windows build, most of which produce no output at all. |

---

## License

RedactPDF is licensed under the **GNU Affero General Public License v3.0**
(AGPL-3.0). See [LICENSE.md](LICENSE.md) for the full text.

In short: you may use, study, modify, and redistribute it freely, but any
redistributed or network-hosted (SaaS) version, including modified ones, must
make its **complete corresponding source available under the same AGPL-3.0
terms**. This copyleft is also required by the core dependency PyMuPDF, which is
itself AGPL-3.0 (or commercial).

<div align="right" style="display: flex">
    <img src="https://api.visitorbadge.io/api/visitors?path=https%3A%2F%2Fgithub.com%2Ftheodubus%2FRedactPDF&countColor=%231182c2" height="20"/>
    <a href="https://github.com/theodubus" alt="https://github.com/theodubus"><img height="20" style="border-radius: 5px" src="https://img.shields.io/static/v1?style=for-the-badge&label=CREE%20PAR&message=theodubus&color=1182c2"></a>
    <a href="LICENSE.md" alt="licence"><img style="border-radius: 5px" height="20" src="https://img.shields.io/static/v1?style=for-the-badge&label=LICENSE&message=GNU+AGPL+V3&color=1182c2"></a>
</div>
