# Setup guide

The [README](../README.md#setup-about-5-minutes) has the short version. This page adds the details.

## Before you start

- **Linux desktop session.** TuxPane v1 shows an **X11 (Xorg)** desktop. On Ubuntu or Fedora, click your name on the login screen, then the gear icon, and choose "Ubuntu on Xorg" / "GNOME on Xorg". Linux Mint uses X11 already. Wayland support is planned.
- **Someone logged in.** TuxPane shows the desktop that is already running, so the Linux user must be logged in.
- **Headless machines** (no monitor). Enable automatic login for your user and plug in an **HDMI dummy plug** (a few dollars online), so Linux has a screen to draw. Reboot once after setting this up.
- **Network.** The Mac and Linux machine must be on the same home network, or both on [Tailscale](https://tailscale.com). TuxPane refuses connections from the public internet.

## Opening a terminal or SSH

The installer runs in a terminal on the Linux machine, as the user who is logged in to the desktop. Don't use `sudo`.

- **At the Linux machine:** press **Ctrl + Alt + T** (Ubuntu, Mint, Fedora), or open *Terminal* / *Konsole* from the applications menu.
- **From your Mac:** open the **Terminal** app (⌘Space, type "Terminal") and connect with SSH, using your own Linux user name and address:

  ```bash
  ssh your-linux-user@192.168.1.20
  ```

  If the connection is refused, turn on SSH on Linux first (Ubuntu/Mint: `sudo apt install openssh-server`; Fedora: `sudo systemctl enable --now sshd`). With Tailscale, use the machine's Tailscale name or `100.x` address.

Then paste the install command shown in TuxPane:

```bash
curl -fsSL https://github.com/vinoth12940/tuxpane/releases/latest/download/install.sh | bash
```

## What the installer does

In order:

1. **Desktop session.** It finds your logged-in X11 desktop and stops with instructions if it's Wayland or nobody is logged in.
2. **Required packages.** It checks for `ffmpeg`, `xrandr`, `xclip`, `openssl` and the X11 libraries. If any are missing, it prints the exact `apt` / `dnf` / `pacman` / `zypper` command and asks before running it with `sudo`.
3. **Video encoder.** It test-encodes one second of your screen with AMD/Intel hardware (VAAPI), then NVIDIA (NVENC), then software (x265), and keeps the first that works.
4. **Security keys.** It creates a private key, a certificate and a secret token in `~/.config/tuxpane/`, readable only by you. Re-running the installer keeps them, so paired Macs keep working.
5. **Background service.** It installs and starts a systemd **user** service, `tuxpane.service`, that runs while you're logged in.
6. **Firewall.** If `ufw` or `firewalld` is on, it offers to allow TuxPane from your home network only: TCP 7300–7301 and UDP 7301. If you say no, it prints the commands to run later. Tailscale works either way.
7. **Pairing.** It waits up to 10 minutes for your Mac.

### Installer options

Add them after `bash -s --`, for example `curl … | bash -s -- --no-pair`:

| Option | Meaning |
|---|---|
| `--yes` | Accept the defaults without asking. It never runs `sudo` for firewall changes. |
| `--no-pair` | Install only; pair later with `tuxpane pair`. |
| `--port N` | Use a different port instead of 7300. It's kept on later updates. |
| `--reset` | Create new keys, which unpairs every Mac. |

## Pairing

1. In TuxPane, **choose your machine**. It appears when the installer or `tuxpane pair` is waiting and both are on the same network. Otherwise, type its name or Tailscale address.
2. Both screens show the **same 6-digit code**. If they match, type **y** and press **Enter** on Linux, then click **They Match** on the Mac.
3. The Mac saves the machine, and keeps its secret token in your Keychain.

**Why it's safe.** The code is calculated from the Linux machine's certificate and a random value from each side, and the Mac commits to its value first. A device pretending to be your Linux machine would make the two screens show different codes. The secret is only sent after both of you confirm.

**Pairing another Mac later:** run `tuxpane pair` in a terminal on Linux.

**No interactive terminal on Linux?** Run `tuxpane pair --code`, then in the Mac app choose **Paste a pairing code instead**. Treat that code like a password.

## Keyboard permission

Open **System Settings → Privacy & Security → Accessibility** and switch on **TuxPane**. This lets ⌘Tab, ⌘Space and other system shortcuts reach Linux; everything else works without it. If you rebuild the app yourself without an Apple certificate, macOS may ask again after each rebuild.

## Firewall commands (if you said no during install)

**ufw**, replacing the subnet with your home network:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 7300:7301 proto tcp comment TuxPane
sudo ufw allow from 192.168.1.0/24 to any port 7301 proto udp comment TuxPane
```

**firewalld:**

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.168.1.0/24 port port=7300-7301 protocol=tcp accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.168.1.0/24 port port=7301 protocol=udp accept'
sudo firewall-cmd --reload
```

## Building from source

The Mac app, until the notarized download is published:

```bash
git clone https://github.com/vinoth12940/tuxpane.git
cd tuxpane
./scripts/build-app.sh          # installs ~/Applications/TuxPane.app
```

The Linux agent, from a local build instead of the release (for development):

```bash
./scripts/package-agent.sh
scp dist/tuxpane-agent-1.0.0.tar.gz dist/install.sh you@linux:/tmp/
ssh -t you@linux 'TUXPANE_TARBALL=/tmp/tuxpane-agent-1.0.0.tar.gz bash /tmp/install.sh'
```
