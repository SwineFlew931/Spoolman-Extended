# Installing Spoolman Extended

Two ways in. **Use a release zip** unless you intend to change the code — it
contains the web client already built, so nothing on the machine needs Node.

Everything here assumes Linux (a Raspberry Pi is the usual home) and a user who
can `sudo`.

---

## 1. Install Spoolman Extended

Download the latest release zip from
[Releases](https://github.com/SwineFlew931/Spoolman-Extended/releases), then:

```bash
cd ~
unzip ~/Downloads/spoolman.zip -d Spoolman
cd Spoolman
bash scripts/install.sh
```

The installer asks two questions: whether to install a systemd service (say
**y** — it starts Spoolman on boot) and which directory to install into. It
handles Python, dependencies and the `.env` file itself.

When it finishes, Spoolman is at `http://<this machine>:7912`.

At this point you have ordinary Spoolman. Everything below adds the NFC part.

---

## 2. Add the NFC reader

You need a **PN532 reader** connected by USB to *this* machine — the one running
Spoolman, not the computer you browse from — and NTAG stickers (NTAG216 for
preference; NTAG215 is usually fine).

Give the reader its own virtualenv and service:

```bash
cd ~/Spoolman
python3 -m venv nfcd/.venv
nfcd/.venv/bin/pip install -r nfcd/requirements.txt
```

Install its service, replacing the two CHANGEME values with your username and
the directory you installed into:

```bash
sudo cp nfcd/systemd/spoolman-nfc.service /etc/systemd/system/
sudoedit /etc/systemd/system/spoolman-nfc.service
sudo systemctl daemon-reload
sudo systemctl enable --now spoolman-nfc
```

The user it runs as must be in the `dialout` group, or it cannot open the
reader's serial port:

```bash
sudo usermod -aG dialout $USER
```

Then tell Spoolman it may use the reader, by adding two lines to `~/Spoolman/.env`:

```bash
printf '\nSPOOLMAN_NFC_ENABLED=TRUE\nSPOOLMAN_NFCD_URL=http://127.0.0.1:7913\n' >> ~/Spoolman/.env
sudo systemctl restart Spoolman
```

**Without those two lines the NFC features stay switched off** — which is the
right default for an installation with no reader.

Check it worked:

```bash
curl -s http://localhost:7912/api/v1/nfc/status
```

`{"enabled":true,"connected":true,...}` means you are done. Settings in the web
interface now has an **NFC** section showing the reader, and spools have a
**Write tag** button.

`"connected":false` with an error means the daemon cannot see the reader —
check the cable, and `journalctl -u spoolman-nfc -n 20`.

---

## 3. Optional: Snapmaker U1 sync

Only if you have a U1 running Paxx12 Extended Firmware. It keeps the printer's
per-channel spool state mirrored into Spoolman. See
[`integrations/snapmaker-u1/README.md`](integrations/snapmaker-u1/README.md) —
the install is the same shape as the reader's.

---

## 4. Updating

Download the new zip and unpack it over the top, keeping your `.env` and the
database (which lives outside the install directory, in
`~/.local/share/spoolman`):

```bash
sudo systemctl stop Spoolman spoolman-nfc
cd ~ && unzip -o ~/Downloads/spoolman.zip -d Spoolman
cd Spoolman && bash scripts/install.sh
sudo systemctl start Spoolman spoolman-nfc
```

**Then hard-refresh your browser** — Ctrl-Shift-R. The web client is served with
a long cache lifetime, and a half-cached page can render blank or quietly show
you the old interface. This catches people out more than anything else here.

---

## 5. Installing from source

Only if you intend to change the code. **The built web client is not in the
repository**, so a clone gives you a working backend and no user interface until
you build one, which needs Node 20 or newer.

```bash
git clone https://github.com/SwineFlew931/Spoolman-Extended.git
cd Spoolman-Extended
git checkout nfc-integration
```

Build the client, then install as above:

```bash
cd client_v2 && npm ci && npm run build && cd ..
bash scripts/install.sh
```

Building on a Pi is slow but works. Building on a faster machine and copying
`client_v2/build/` across is quicker.

### The two-step deploy

Because `client_v2/build` is not tracked by git, **`git pull` alone never
updates the web interface.** Pulling a change that touched the client and
restarting will leave the old interface in place with nothing obviously wrong.

Deploying from source is therefore always two steps — the code, then the client:

```bash
git pull && cd client_v2 && npm run build && cd .. && sudo systemctl restart Spoolman
```

Building also rewrites the translation files in `client_v2/locales/` as a side
effect (it strips empty placeholder entries). That is expected and must not be
committed:

```bash
git checkout -- client_v2/locales
```

---

## Removing it

The NFC parts are separable. To go back to ordinary Spoolman without
reinstalling, stop the reader and remove the two `.env` lines:

```bash
sudo systemctl disable --now spoolman-nfc
```

Spoolman then behaves exactly as upstream does. Your data is untouched either
way — it lives in `~/.local/share/spoolman`, outside the install directory.
